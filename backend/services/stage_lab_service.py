"""Stage Testing Lab — Wave 2.

Lets admins run any pipeline stage on a synthetic input WITHOUT touching real
orders. Each run is recorded in `stage_test_runs` with the metadata the user
asked for: provider, model, prompt_hash, latency, estimated_cost, fallback,
output preview.

Supported stages:
  text — scenario_generation, production_planning   → real LLM call
  image — child_character_i2i                        → real I2I (requires source URL)
  preview-only — narration_generation, video_generation, music_generation,
                 scene_image_generation              → renders the prompt + the
                 provider/model that would be used. NOT executed (prevents
                 burning budget on stages that need a real order context).
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from datetime import datetime, timezone

from db import db
from services.config_service import (
    resolve_model, resolve_prompt, resolve_transport,
    PROVIDER_ENV_MAP,
)
from services.pricing_service import get_pricing_config

logger = logging.getLogger("stage_lab_service")

SUPPORTED_STAGES = (
    "scenario_generation",
    "production_planning",
    "child_character_i2i",
    "extra_character_i2i",
    "scene_image_generation",
    "book_page_image_generation",
    "narration_generation",
    "video_generation",
    "music_generation",
    "video_assembly",
    "pdf_assembly",
)

REAL_CALL_STAGES = {
    "scenario_generation",
    "production_planning",
    "child_character_i2i",
    "extra_character_i2i",
    # Phase K — narration_generation is real-call when the resolved provider
    # has credentials. The lab route checks this dynamically; we keep the
    # static set so other call sites (cost-acknowledge gate) include it.
    "narration_generation",
    # Phase L — video_generation via fal.ai Kling.
    "video_generation",
    # Phase M — music_generation via ElevenLabs Music.
    "music_generation",
}

# Phase G — `executor_status` classifies WHY a stage is callable or not:
#   real-call            — admin can run it live, burns API budget
#   preview-only         — has a real executor but lab won't run it without a real
#                          order context (scene_image needs scene_plans + plan)
#   not-yet-wired        — admin template exists, but no executor calls a provider yet
#                          (video_generation, music_generation today)
#   local-binary         — runs locally (ffmpeg/reportlab), no LLM provider, no
#                          editable prompt — visibility-only in lab
#   reuse-from-other-stage — stage exists but reuses another stage's output verbatim
#                          (book_page_image_generation today reuses scene_image)
EXECUTOR_STATUS: dict[str, str] = {
    "scenario_generation":      "real-call",
    "production_planning":      "real-call",
    "child_character_i2i":      "real-call",
    "extra_character_i2i":      "real-call",
    "scene_image_generation":   "preview-only",   # needs real order context
    "book_page_image_generation": "reuse-from-other-stage",
    "narration_generation":     "real-call-when-keyed",  # Phase K — ElevenLabs TTS executor wired
    "video_generation":         "real-call-when-keyed",  # Phase L — fal.ai Kling adapter wired
    "music_generation":         "real-call-when-keyed",  # Phase M — ElevenLabs Music adapter wired (plan-gated)
    "video_assembly":           "local-binary",
    "pdf_assembly":             "local-binary",
}

STAGE_NOTES_AR: dict[str, str] = {
    "scenario_generation":      "استدعاء حقيقي لـ Claude/GPT-5 — يستهلك رصيد API.",
    "production_planning":      "استدعاء حقيقي لـ Claude/GPT-5.2 (mega-JSON) — يستهلك رصيد API.",
    "child_character_i2i":      "استدعاء حقيقي لـ OpenAI gpt-image-1 — يستهلك رصيد API.",
    "extra_character_i2i":      "يستدعي نفس موفّر child_character_i2i لكل شخصية إضافية مرئيّة. يعيد استخدام قالب الـ child_character_i2i افتراضياً.",
    "scene_image_generation":   "استدعاء حقيقي عبر خط الإنتاج فقط — في lab معاينة فقط لأنها تحتاج سياق طلب فعلي.",
    "book_page_image_generation": "حالياً يُعاد استخدام صورة المشهد المقابلة (provider=reused). القالب جاهز لتوليد إيضاحات كتاب مستقلّة عند توصيل executor.",
    "narration_generation":     "تكامل ElevenLabs TTS فعلي عند توفّر ELEVENLABS_API_KEY (يُقرأ من /admin/secrets). بدون مفتاح يعود إلى المحاكاة تلقائياً.",
    "video_generation":         "تكامل fal.ai Kling فعلي عند توفّر FAL_KEY (يُقرأ من /admin/secrets). افتراضي: kling-video/v2.1/standard. قابل للتعديل من Stage Control. الاستراتيجية: I2V عند توفّر صورة المشهد، وإلا T2V.",
    "music_generation":         "تكامل ElevenLabs Music فعلي عند توفّر ELEVENLABS_API_KEY (يحتاج خطّة Creator+ على ElevenLabs). يحترم audio_background_mode (music | human_rhythm | none). human_rhythm مدعوم prompt-bias فقط — لا توجد قدرة أصلية على الإيقاع البشري في API.",
    "video_assembly":           "تجميع محلّي بـ ffmpeg (لا موفّر LLM، لا تكلفة API). الإعدادات تظهر للفحص فقط.",
    "pdf_assembly":             "تجميع محلّي بـ reportlab (لا موفّر LLM، لا تكلفة API). الإعدادات تظهر للفحص فقط.",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(text: str) -> str:
    return "sha256:" + hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


async def _estimated_cost_for(stage_key: str) -> float:
    cfg = await get_pricing_config()
    return float(cfg.get("per_stage_costs", {}).get(stage_key, 0.0))


def _fake_order(input_payload: dict) -> dict:
    """Build a synthetic order doc from the admin's lab input.

    Only the fields the underlying services actually read are populated.
    """
    child = {
        "name":   input_payload.get("child_name", "ليلى"),
        "age":    input_payload.get("child_age", 5),
        "gender": input_payload.get("child_gender", "female"),
        "image_url": input_payload.get("child_image_url") or None,
        "appearance_notes": input_payload.get("child_appearance_notes") or "",
        "hijab": False,
    }
    return {
        "id": f"lab-{uuid.uuid4().hex[:8]}",
        "user_id": "lab-admin",
        "data": {
            "child": child,
            "goal": {
                "context": input_payload.get("context", "اختبار مختبر المراحل"),
                "custom_subcategory": input_payload.get("subcategory") or "",
            },
            "characters": [],
            "personalization": {"favorites": {}, "custom_notes": ""},
            "audio_background": {"mode": "music"},
            "delivery": {"output_type": input_payload.get("output_type", "both")},
        },
        "enriched": {
            "category_name": input_payload.get("category", "تربوي"),
            "subcategory_name": input_payload.get("subcategory", ""),
            "type_name": input_payload.get("story_type", "تعليمي"),
            "tone_name": input_payload.get("tone", "دافئ"),
            "setting_name": input_payload.get("setting", "منزل"),
            "language_name": "عربية فصحى مبسطة",
        },
        "duration": {
            "seconds": int(input_payload.get("duration_seconds", 60)),
            "label": input_payload.get("duration_label", "دقيقة"),
            "scene_target": int(input_payload.get("scene_target", 5)),
            "scene_target_min": 5,
            "scene_target_max": 6,
            "scene_target_bucket": "medium",
            "cost_tier": "medium",
        },
    }


# ---------------------------------------------------------------------------
# Real executors (text)
# ---------------------------------------------------------------------------
async def _run_scenario_generation(input_payload: dict) -> dict:
    from services.scenario_service import _generate_via_claude  # local import — no cycles
    fake = _fake_order(input_payload)
    items = await _generate_via_claude(fake)
    preview = [{"title": s.get("title"), "angle": s.get("emotional_angle")} for s in items[:3]]
    return {"output_preview": preview, "result_summary": f"{len(items)} scenarios generated"}


async def _run_production_planning(input_payload: dict) -> dict:
    from services.production_service import _generate_via_claude
    fake = _fake_order(input_payload)
    scenario = {
        "title": input_payload.get("scenario_title", "اختبار اختياري"),
        "short_summary": input_payload.get("scenario_summary", "ملخص اختباري قصير"),
        "emotional_angle": "emotional",
        "learning_goal": input_payload.get("learning_goal", "المشاركة"),
        "visual_style_hint": "warm watercolor",
        "estimated_scene_count": fake["duration"]["scene_target"],
        "why_this_fits": "",
    }
    payload = await _generate_via_claude(fake, scenario, fake["duration"]["scene_target"])
    plan = payload.get("production_plan", {})
    return {
        "output_preview": {
            "title": plan.get("title"),
            "story_summary_preview": (plan.get("story_summary") or "")[:200],
            "scene_count": len(payload.get("scenes", [])),
            "story_keywords": (plan.get("story_keywords") or [])[:8],
        },
        "result_summary": f"{len(payload.get('scenes', []))} scenes planned",
    }


async def _run_child_character_i2i(input_payload: dict) -> dict:
    """Real I2I — requires `child_image_url` (an internal `/api/uploads/file/{id}` URL)."""
    src = input_payload.get("child_image_url")
    if not src:
        raise ValueError("child_image_url is required for child_character_i2i")
    from services.child_character_service import (
        _openai_generate, _fetch_source_bytes, _save_generated_png,
        DEFAULT_PROMPT,
    )
    src_tuple = await _fetch_source_bytes(src)
    if not src_tuple:
        raise ValueError("Failed to fetch source image from internal storage")
    src_bytes, src_mime = src_tuple
    # Prompt: admin template if any, else DEFAULT_PROMPT.
    prompt_admin, prompt_src, _reason = await resolve_prompt(
        "child_character_i2i", {
            "child_name": input_payload.get("child_name", "Child"),
            "child_age": str(input_payload.get("child_age", 5)),
            "child_gender": input_payload.get("child_gender", "female"),
        },
    )
    prompt = prompt_admin if (prompt_src == "admin" and prompt_admin) else DEFAULT_PROMPT
    res = await _openai_generate(src_bytes, src_mime, prompt, "gpt-image-1")
    if not res or not res.get("image_bytes"):
        raise RuntimeError("OpenAI did not return image bytes")
    url = await _save_generated_png("lab-admin", "lab-admin", res["image_bytes"])
    return {
        "output_preview": {"image_url": url, "prompt_used": prompt[:600]},
        "result_summary": f"image generated ({len(res['image_bytes'])} bytes)",
    }


async def _run_narration_generation(input_payload: dict) -> dict:
    """Phase K — real TTS call (ElevenLabs by default).

    Honest behavior:
      * If ELEVENLABS_API_KEY is configured (override or env) AND provider
        resolves to elevenlabs → makes a real call, saves audio to internal
        storage, returns a playable URL.
      * Otherwise → falls back to mock and reports it transparently in the
        meta. Lab UI will show `real_call=False` so the admin sees the truth.
    Text is hard-capped at 600 chars to keep lab spend predictable.
    """
    from services.tts_service import generate_tts
    import asyncio as _asyncio
    import uuid as _uuid
    from storage import put_object, APP_NAME
    from db import db

    raw = (input_payload.get("narration_text")
           or input_payload.get("text")
           or "هذه قصّة قصيرة عن طفل لطيف يتعلّم المشاركة مع أصدقائه.")
    text = str(raw)[:600]
    voice = input_payload.get("voice")
    language = input_payload.get("language") or "ar"
    model_id = input_payload.get("model_id")
    voice_settings = input_payload.get("voice_settings") if isinstance(
        input_payload.get("voice_settings"), dict
    ) else None

    audio_bytes, mime, meta = await generate_tts(
        text=text, voice=voice, language=language,
        model_id=model_id, voice_settings=voice_settings,
    )

    audio_url = None
    if audio_bytes:
        file_id = str(_uuid.uuid4())
        ext = "mp3" if "mpeg" in mime else "wav"
        storage_path = f"{APP_NAME}/lab/narration/{file_id}.{ext}"
        loop = _asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: put_object(storage_path, audio_bytes, mime),
            )
            await db.files.insert_one({
                "id": file_id,
                "user_id": "lab-admin",
                "scope": "lab-narration",
                "storage_path": result.get("path", storage_path),
                "original_filename": f"narration.{ext}",
                "content_type": mime,
                "size": result.get("size", len(audio_bytes)),
                "is_deleted": False,
                "created_at": _now(),
            })
            audio_url = f"/api/uploads/file/{file_id}"
        except Exception as e:  # noqa: BLE001
            meta["storage_error"] = f"{type(e).__name__}: {e}"

    summary_bits = [
        f"provider={meta.get('provider')}",
        f"real_call={meta.get('real_call')}",
        f"~{meta.get('duration_seconds') or 0}s",
    ]
    if meta.get("error"):
        summary_bits.append(f"err={meta['error'][:80]}")

    return {
        "output_preview": {
            "audio_url":        audio_url,
            "duration_seconds": meta.get("duration_seconds"),
            "provider":         meta.get("provider"),
            "model":            meta.get("model"),
            "voice":            meta.get("voice"),
            "real_call":        bool(meta.get("real_call")),
            "fallback_to_mock": bool(meta.get("fallback_to_mock")),
            "secret_source":    meta.get("secret_source"),
            "bytes":            meta.get("bytes"),
            "latency_ms":       meta.get("latency_ms"),
            "error":            meta.get("error"),
            "text_used":        text[:200],
        },
        "result_summary": " · ".join(summary_bits),
    }



async def _run_video_generation(input_payload: dict) -> dict:
    """Phase L — real fal.ai Kling video clip via submit→poll→download.

    Lab-only constraints:
      * single scene clip (not the whole batch)
      * hard cap on duration (5s) to control spend
      * max_wait_s defaults to 240s
      * if FAL_KEY is missing, returns honest fallback meta

    Inputs honored:
      prompt, image_url (optional → switches to T2V), duration, aspect_ratio,
      negative_prompt, cfg_scale, max_wait_s.
    """
    from services.video_generation_service import generate_clip_sync
    import asyncio as _asyncio
    import uuid as _uuid
    from storage import put_object, APP_NAME
    from db import db

    scene = {
        "prompt":          (input_payload.get("video_prompt")
                            or input_payload.get("prompt")
                            or "Cinematic gentle camera move on a warm-toned children's storybook scene"),
        "image_url":       input_payload.get("scene_image_url") or input_payload.get("image_url"),
        "duration":        min(int(input_payload.get("duration") or 5), 10),
        "aspect_ratio":    input_payload.get("aspect_ratio") or "16:9",
        "negative_prompt": input_payload.get("negative_prompt"),
        "cfg_scale":       input_payload.get("cfg_scale"),
    }
    max_wait_s = int(input_payload.get("max_wait_s") or 240)

    bytes_, mime, meta = await generate_clip_sync(
        scene, max_wait_s=max_wait_s, poll_interval_s=8,
    )

    clip_url = None
    if bytes_:
        file_id = str(_uuid.uuid4())
        storage_path = f"{APP_NAME}/lab/video/{file_id}.mp4"
        loop = _asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, lambda: put_object(storage_path, bytes_, mime),
            )
            await db.files.insert_one({
                "id": file_id,
                "user_id": "lab-admin",
                "scope": "lab-video",
                "storage_path": result.get("path", storage_path),
                "original_filename": "clip.mp4",
                "content_type": mime,
                "size": result.get("size", len(bytes_)),
                "is_deleted": False,
                "created_at": _now(),
            })
            clip_url = f"/api/uploads/file/{file_id}"
        except Exception as e:  # noqa: BLE001
            meta["storage_error"] = f"{type(e).__name__}: {e}"

    summary_bits = [
        f"provider={meta.get('provider')}",
        f"strategy={meta.get('clip_strategy')}",
        f"real_call={meta.get('real_call')}",
        f"~{scene['duration']}s",
    ]
    if meta.get("error"):
        summary_bits.append(f"err={str(meta['error'])[:80]}")

    return {
        "output_preview": {
            "clip_url":         clip_url,
            "duration":         scene["duration"],
            "aspect_ratio":     scene["aspect_ratio"],
            "provider":         meta.get("provider"),
            "model":            meta.get("model"),
            "clip_strategy":    meta.get("clip_strategy"),
            "real_call":        bool(meta.get("real_call")),
            "completed":        bool(meta.get("completed")),
            "fallback_to_mock": bool(meta.get("fallback_to_mock")),
            "secret_source":    meta.get("secret_source"),
            "request_id":       meta.get("request_id"),
            "elapsed_s":        meta.get("elapsed_s"),
            "bytes":            meta.get("bytes"),
            "error":            meta.get("error"),
            "prompt_used":      scene["prompt"][:300],
            "image_used":       bool(scene.get("image_url")),
        },
        "result_summary": " · ".join(summary_bits),
    }


async def _run_music_generation_lab(input_payload: dict) -> dict:
    """Phase M — real ElevenLabs Music sample (per-story background).

    Lab-only constraints:
      * single track preview, 30s default (cap 60s)
      * audio_background_mode honored ('none' returns skipped, no API call)
    """
    from services.music_generation_service import generate_music
    import asyncio as _asyncio
    import uuid as _uuid
    from storage import put_object, APP_NAME
    from db import db

    audio_mode = (input_payload.get("audio_background_mode") or "music").lower()
    duration = min(int(input_payload.get("duration_seconds") or 30), 60)
    prompt = (input_payload.get("base_prompt")
              or input_payload.get("prompt")
              or "Warm, hopeful children's storybook background.")
    keywords = input_payload.get("story_keywords") or ["warmth", "kindness", "wonder"]
    arc = input_payload.get("emotional_arc") or "gentle, hopeful"

    audio_bytes, mime, meta = await generate_music(
        audio_background_mode=audio_mode,
        base_prompt=prompt,
        duration_seconds=duration,
        story_keywords=keywords if isinstance(keywords, list) else [str(keywords)],
        emotional_arc=arc,
    )

    audio_url = None
    if audio_bytes:
        file_id = str(_uuid.uuid4())
        storage_path = f"{APP_NAME}/lab/music/{file_id}.mp3"
        loop = _asyncio.get_running_loop()
        try:
            stored = await loop.run_in_executor(
                None, lambda: put_object(storage_path, audio_bytes, mime),
            )
            await db.files.insert_one({
                "id": file_id, "user_id": "lab-admin", "scope": "lab-music",
                "storage_path": stored.get("path", storage_path),
                "original_filename": "music.mp3",
                "content_type": mime,
                "size": stored.get("size", len(audio_bytes)),
                "is_deleted": False, "created_at": _now(),
            })
            audio_url = f"/api/uploads/file/{file_id}"
        except Exception as e:  # noqa: BLE001
            meta["storage_error"] = f"{type(e).__name__}: {e}"

    summary = [
        f"mode={audio_mode}",
        f"impl={meta.get('mode_implementation')}",
        f"real_call={meta.get('real_call')}",
    ]
    if meta.get("skip_reason"):
        summary.append(f"skip={meta['skip_reason']}")

    return {
        "output_preview": {
            "audio_url":          audio_url,
            "duration_seconds":   meta.get("duration_seconds"),
            "provider":           meta.get("provider"),
            "model":              meta.get("model"),
            "real_call":          bool(meta.get("real_call")),
            "skip_reason":        meta.get("skip_reason"),
            "audio_background_mode": meta.get("audio_background_mode"),
            "mode_implementation":   meta.get("mode_implementation"),
            "secret_source":      meta.get("secret_source"),
            "latency_ms":         meta.get("latency_ms"),
            "bytes":              meta.get("bytes"),
            "error":              meta.get("error"),
            "prompt_used":        (meta.get("prompt_used") or "")[:300],
        },
        "result_summary": " · ".join(summary),
    }





# ---------------------------------------------------------------------------
# Preview-only executor — for stages we do not want to burn budget on or that
# need a real order's downstream context (scene image needs a real plan).
# ---------------------------------------------------------------------------
async def _run_preview_only(stage_key: str, input_payload: dict) -> dict:
    """Render the prompt template the live pipeline would have used; do NOT call the provider."""
    ctx = await _build_stage_context(stage_key, input_payload)
    rendered, source, reason = await resolve_prompt(stage_key, ctx)

    extra: dict = {}

    # Phase E — for scene_image_generation, dry-run the reference resolver if
    # the admin supplied a real `order_id` and `scene_index`. Shows what would
    # be injected, what would be skipped, and why — without touching provider.
    if stage_key == "scene_image_generation":
        order_id = input_payload.get("order_id")
        scene_index = input_payload.get("scene_index")
        if order_id and scene_index is not None:
            try:
                from services.scene_reference_service import resolve_scene_references
                order = await db.orders.find_one({"id": order_id}, {"_id": 0})
                if order:
                    plan = await db.production_plans.find_one(
                        {"id": order.get("production_plan_id")}, {"_id": 0},
                    )
                    scene = await db.scene_plans.find_one(
                        {"order_id": order_id, "scene_index": int(scene_index),
                         "is_archived": False},
                        {"_id": 0},
                    )
                    if plan and scene:
                        ref_pkg = await resolve_scene_references(order, plan, scene)
                        # Strip raw URLs we don't need to surface in the lab.
                        def _trim(r):
                            return {k: v for k, v in r.items() if k != "url"} if isinstance(r, dict) else r
                        extra["reference_dry_run"] = {
                            "child_ref":         _trim(ref_pkg.get("child_ref")),
                            "extra_char_refs":   [_trim(r) for r in (ref_pkg.get("extra_char_refs") or [])],
                            "toy_ref":           _trim(ref_pkg.get("toy_ref")),
                            "available":         ref_pkg.get("available"),
                            "skipped_reasons":   ref_pkg.get("skipped_reasons"),
                            "injected_count":    ref_pkg.get("injected_count"),
                            "prompt_augmentation": ref_pkg.get("prompt_augmentation"),
                            "scene_title":       scene.get("title"),
                        }
                    else:
                        extra["reference_dry_run_error"] = "scene or plan not found for order_id+scene_index"
                else:
                    extra["reference_dry_run_error"] = f"order {order_id} not found"
            except Exception as e:  # noqa: BLE001
                extra["reference_dry_run_error"] = f"{type(e).__name__}: {e}"

    return {
        "output_preview": {
            "rendered_prompt_preview": (rendered or "")[:1000],
            "prompt_source": source,
            "render_note": reason,
            **extra,
        },
        "result_summary": "preview-only (provider not called in lab)",
    }


# ---------------------------------------------------------------------------
# Phase F — Effective Prompt Preview (admin-only, no provider execution)
# ---------------------------------------------------------------------------
async def _build_stage_context(stage_key: str, input_payload: dict) -> dict:
    """Build the FULL variable context the live pipeline would have rendered with.

    If `order_id` (and `scene_index` for per-scene stages) is provided, real
    order/plan/scene fields are loaded and merged. Otherwise a synthetic
    context is built from `_fake_order` so admins can preview without a real
    order. Admin-supplied raw keys in `input_payload` win over both, allowing
    fast tweaking.
    """
    base: dict = {}
    fake = _fake_order(input_payload)
    base["child_name"]   = (fake["data"]["child"].get("name") or "")
    base["child_age"]    = str(fake["data"]["child"].get("age") or "")
    base["child_gender"] = "ولد" if fake["data"]["child"].get("gender") == "male" else "بنت"

    order_id = input_payload.get("order_id")
    scene_index = input_payload.get("scene_index")
    real_order = None
    real_plan = None
    real_scene = None
    if order_id:
        real_order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if real_order:
        real_plan = await db.production_plans.find_one(
            {"id": real_order.get("production_plan_id"), "is_archived": False},
            {"_id": 0},
        )
        if scene_index is not None and real_plan:
            try:
                real_scene = await db.scene_plans.find_one(
                    {"order_id": order_id,
                     "production_plan_id": real_plan["id"],
                     "scene_index": int(scene_index),
                     "is_archived": False},
                    {"_id": 0},
                )
            except (TypeError, ValueError):
                real_scene = None

    # Stage-specific enrichment.
    if stage_key in ("scene_image_generation", "book_page_image_generation",
                     "narration_generation", "video_generation",
                     "music_generation", "video_assembly"):
        try:
            from services.generation_orchestrator import _build_scene_image_context
            order_for_ctx = real_order or fake
            plan_for_ctx = real_plan or {"title": "اختبار", "style_guide": {}}
            scene_for_ctx = real_scene or {
                "scene_index": input_payload.get("scene_index", 1),
                "title": input_payload.get("scene_title", "مشهد تجريبي"),
                "scene_goal": input_payload.get("scene_goal", "تعليم المشاركة"),
                "narration_text": input_payload.get("narration_text", "نصّ سرد قصير."),
                "book_text": input_payload.get("book_text", "نصّ كتاب قصير."),
                "emotional_tone": input_payload.get("emotional_tone", "warm"),
                "visual_description": input_payload.get("visual_description", ""),
                "background_setting": input_payload.get("background_setting", "غرفة هادئة"),
                "key_objects": input_payload.get("key_objects", []),
                "continuity_notes": "",
                "image_prompt": {"prompt_text": "", "style_reference": "",
                                 "character_reference_note": ""},
            }
            scene_ctx = _build_scene_image_context(order_for_ctx, plan_for_ctx, scene_for_ctx)
            base.update(scene_ctx)
        except Exception:  # noqa: BLE001 — preview must never crash on context build
            pass

    # Phase G — book_page_image_generation extras (page metadata).
    if stage_key == "book_page_image_generation":
        # Try to derive page_number / total_pages from real plan when available.
        page_number = input_payload.get("page_number") or 1
        total_pages = input_payload.get("total_pages")
        if not total_pages and real_plan:
            try:
                total_pages = await db.book_pages.count_documents({
                    "production_plan_id": real_plan["id"], "is_archived": False,
                })
            except Exception:  # noqa: BLE001
                total_pages = None
        base["page_number"] = page_number
        base["total_pages"] = total_pages or 1
        # Style fields commonly referenced
        sg = (real_plan or {}).get("style_guide") or {}
        base.setdefault("art_direction", sg.get("art_direction", ""))
        base.setdefault("palette",       sg.get("palette", ""))
        base.setdefault("lighting",      sg.get("lighting", ""))

    # Phase G — extra_character_i2i extras.
    if stage_key == "extra_character_i2i":
        base.setdefault("character_name", input_payload.get("character_name", "صديق"))
        base.setdefault("character_type", input_payload.get("character_type", "friend"))
        base.setdefault("character_role", input_payload.get("character_role", "supporting"))
        base.setdefault("character_visual_description",
                        input_payload.get("character_visual_description", ""))
        sg = (real_plan or {}).get("style_guide") or {}
        base.setdefault("palette", sg.get("palette", ""))
        base.setdefault("art_direction", sg.get("art_direction", ""))

    # Phase G — assembly stages: surface output_dir + audio_background_mode.
    if stage_key in ("video_assembly", "pdf_assembly"):
        base.setdefault("output_dir", input_payload.get("output_dir", "/app/storage/exports"))
        # audio_background_mode already set by _build_scene_image_context for video_assembly
        if stage_key == "pdf_assembly":
            # PDF doesn't need audio mode but we keep base context safe.
            base.setdefault("audio_background_mode",
                            ((real_order or fake).get("data") or {}).get(
                                "audio_background", {}).get("mode", "music"))

    if stage_key in ("scenario_generation", "production_planning"):
        # These use ad-hoc Claude prompts hardcoded inside their services; admin
        # templates exist for completeness so render against the available
        # synthetic/real order fields.
        order_for_ctx = real_order or fake
        d = order_for_ctx.get("data") or {}
        base.update({
            "child_name":   (d.get("child") or {}).get("name") or "",
            "child_age":    str((d.get("child") or {}).get("age") or ""),
            "child_gender": "ولد" if (d.get("child") or {}).get("gender") == "male" else "بنت",
            "context":      (d.get("goal") or {}).get("context") or "",
            "category":     (order_for_ctx.get("enriched") or {}).get("category_name") or "",
            "story_type":   (order_for_ctx.get("enriched") or {}).get("type_name") or "",
            "tone":         (order_for_ctx.get("enriched") or {}).get("tone_name") or "",
            "setting":      (order_for_ctx.get("enriched") or {}).get("setting_name") or "",
        })

    # Phase J — common Arabic-aware conveniences for ALL prompt stages.
    order_for_ctx2 = real_order or fake
    d_data = order_for_ctx2.get("data") or {}
    enriched = order_for_ctx2.get("enriched") or {}
    child_d = d_data.get("child") or {}
    pers_d  = d_data.get("personalization") or {}
    chars_d = d_data.get("characters") or []
    duration_d = order_for_ctx2.get("duration") or {}

    base.setdefault("child_hijab_note", "(بحجاب)" if child_d.get("hijab") else "")
    base.setdefault("custom_notes", pers_d.get("custom_notes") or "لا يوجد")
    base.setdefault("language", enriched.get("language_name") or "العربية الفصحى المبسّطة")
    base.setdefault("voice", enriched.get("voice_name") or "")
    base.setdefault("output_type", (d_data.get("output_type") or {}).get("type") or "both")
    base.setdefault("audio_background_mode",
                    (d_data.get("audio_background") or {}).get("mode") or "music")
    base.setdefault("duration_label", duration_d.get("label") or "")
    base.setdefault("scene_target", str(duration_d.get("scene_target") or "5"))
    base.setdefault("target_duration", str(duration_d.get("target_seconds") or "90"))
    sr = duration_d.get("scene_target_range") or duration_d.get("scene_range") or []
    if isinstance(sr, list) and len(sr) == 2:
        base.setdefault("scene_range", f"{sr[0]}–{sr[1]}")
    else:
        base.setdefault("scene_range", "3–10")

    chars_brief = "، ".join(
        f"{c.get('type','')}"
        + (f" ({c.get('name')})" if c.get("name") else "")
        + (" — ظاهر" if c.get("role") == "visible" else "")
        for c in chars_d
    ) or "لا يوجد"
    base.setdefault("characters_brief", chars_brief)

    fav_brief = "، ".join(
        f"{k}: {(v or {}).get('name','')}"
        for k, v in (pers_d.get("favorites") or {}).items()
        if (v or {}).get("selected") and (v or {}).get("name")
    ) or "لا يوجد"
    base.setdefault("favorites_brief", fav_brief)

    # Style fields commonly referenced by image templates.
    sg_d = (real_plan or {}).get("style_guide") or {}
    base.setdefault("art_direction", sg_d.get("art_direction", ""))
    base.setdefault("palette",       sg_d.get("palette", ""))
    base.setdefault("lighting",      sg_d.get("lighting", ""))
    # `character_note` and `scene_prompt` are admin-template-friendly aliases
    # for the longer keys the live context provides.
    base.setdefault("character_note", base.get("character_reference_note") or
                                       base.get("continuity_notes") or "")
    base.setdefault("scene_prompt",   base.get("scene_title") or base.get("scene_goal") or "")

    if stage_key == "production_planning":
        sc = await db.scenarios.find_one(
            {"order_id": (real_order or {}).get("id"),
             "is_chosen": True, "is_archived": False},
            {"_id": 0},
        ) if real_order else None
        if sc:
            base.setdefault("scenario_title", sc.get("title") or "")
            base.setdefault("scenario_summary", sc.get("short_summary") or "")
            base.setdefault("scenario_emotional_angle", sc.get("emotional_angle") or "")
            base.setdefault("scenario_learning_goal", sc.get("learning_goal") or "")
        else:
            base.setdefault("scenario_title", "(لم يُختر بعد)")
            base.setdefault("scenario_summary", "")
            base.setdefault("scenario_emotional_angle", "")
            base.setdefault("scenario_learning_goal", "")

    # Final layer: explicit admin-supplied raw keys override everything (escape hatch).
    for k, v in (input_payload or {}).items():
        if k in ("order_id", "scene_index"):
            continue
        if isinstance(v, (str, int, float, bool)):
            base[k] = v

    return base


def _detect_unresolved(rendered: str | None) -> list[str]:
    """Return the list of `${var}` / `$var` placeholders still left in the
    rendered text — these are signs of a broken template or missing variable."""
    if not rendered:
        return []
    from services.config_service import _extract_placeholders
    return sorted(_extract_placeholders(rendered))


async def build_effective_prompt_preview(stage_key: str, input_payload: dict) -> dict:
    """Phase F — return everything an admin needs to inspect the FINAL prompt
    without calling the provider.

    Returns:
        {
          "stage_key": str,
          "provider": str, "model_name": str, "model_source": "admin"|"fallback",
          "transport": str, "env_key": str,
          "prompt_source": "admin"|"default",
          "template_id": str|None, "template_version": int|None,
          "template_text_preview": str (first 1000 chars of admin template, if any),
          "render_note": str,                  # template_id=... version=... | reason
          "fallback_would_happen": bool,
          "effective_prompt": str,             # the FINAL rendered text
          "prompt_hash": str,
          "unresolved_placeholders": list[str],
          "warnings": list[str],
          "context_source": "real_order" | "synthetic" | "mixed",
          "context_used": dict,                # what we rendered with
          "scene_image_extras": dict|None,     # for scene_image_generation only
          "estimated_cost": float, "currency": str,
        }
    """
    if stage_key not in SUPPORTED_STAGES:
        raise ValueError(f"Unsupported stage_key: {stage_key}")

    # 1. Resolve provider/model exactly as the live pipeline would.
    provider, model_name, model_source = await resolve_model(
        stage_key, "anthropic", "claude-sonnet-4-5-20250929",
    )
    transport = await resolve_transport(stage_key) \
        if stage_key in ("scenario_generation", "production_planning") else "n/a"
    env_key = PROVIDER_ENV_MAP.get(provider) or "—"

    # 2. Build the full variable context.
    ctx = await _build_stage_context(stage_key, input_payload)
    context_source = "real_order" if input_payload.get("order_id") else "synthetic"
    if context_source == "real_order" and not await db.orders.find_one(
        {"id": input_payload.get("order_id")}, {"_id": 1}
    ):
        context_source = "synthetic"  # order_id supplied but not found

    # 3. Pull the active admin template (if any) for full debug visibility.
    tpl_doc = await db.prompt_templates.find_one(
        {"stage_key": stage_key, "active": True},
        {"_id": 0, "id": 1, "template_text": 1, "version": 1, "variables": 1},
    )

    # 4. Render via the standard resolver (admin → admin text; default → None).
    rendered, prompt_source, render_note = await resolve_prompt(stage_key, ctx)

    # 5. The FINAL effective prompt: admin-rendered if available, else the
    #    deterministic default. To produce the default WITHOUT calling the
    #    provider, fall back to the template's own text if present, otherwise
    #    a stage-specific "would use service default" placeholder.
    fallback_would_happen = (prompt_source != "admin")
    if rendered:
        effective_prompt = rendered
    elif tpl_doc and tpl_doc.get("template_text"):
        # Render with safe_substitute so the admin sees what the template
        # WOULD have produced, with `${var}` left in place for missing vars.
        from string import Template
        try:
            effective_prompt = Template(tpl_doc["template_text"]).safe_substitute(
                {k: str(v) for k, v in ctx.items() if v is not None}
            )
        except Exception:  # noqa: BLE001
            effective_prompt = tpl_doc["template_text"]
    else:
        effective_prompt = (
            f"[NO ADMIN TEMPLATE — service-internal default for "
            f"`{stage_key}` will be used at runtime.]"
        )

    unresolved = _detect_unresolved(effective_prompt)

    warnings: list[str] = []
    if not tpl_doc:
        warnings.append("لا يوجد قالب admin مفعّل لهذه المرحلة — سيتم استخدام prompt افتراضي من الكود")
    if fallback_would_happen and tpl_doc:
        # Template exists but resolve_prompt rejected it — surface why.
        warnings.append(f"القالب موجود لكنه لم يُستخدم: {render_note}")
    if unresolved:
        warnings.append(f"متغيّرات غير محلولة في الناتج: {', '.join(unresolved[:5])}")
    if provider in ("mock",) and stage_key in ("narration_generation",):
        warnings.append("الموفّر الحالي mock — لن تُولَّد صوتيات حقيقية في خط الإنتاج")
    if env_key and isinstance(env_key, dict):
        env_key_label = env_key.get("env_key") or env_key.get("label") or "—"
    else:
        env_key_label = env_key

    out: dict = {
        "stage_key": stage_key,
        "provider": provider,
        "model_name": model_name,
        "model_source": model_source,
        "transport": transport,
        "env_key": env_key_label,
        "prompt_source": prompt_source,
        "template_id": (tpl_doc or {}).get("id"),
        "template_version": (tpl_doc or {}).get("version"),
        "template_text_preview": ((tpl_doc or {}).get("template_text") or "")[:1000],
        "render_note": render_note,
        "fallback_would_happen": fallback_would_happen,
        "effective_prompt": effective_prompt,
        "prompt_hash": _hash(effective_prompt),
        "unresolved_placeholders": unresolved,
        "warnings": warnings,
        "context_source": context_source,
        "context_used": {k: (v if isinstance(v, (str, int, float, bool, list)) else str(v))
                         for k, v in ctx.items()},
        "estimated_cost": await _estimated_cost_for(stage_key),
        "currency": "SAR",
    }

    # Stage-specific extras.
    if stage_key == "scene_image_generation":
        order_id = input_payload.get("order_id")
        scene_index = input_payload.get("scene_index")
        extras: dict | None = None
        if order_id and scene_index is not None:
            try:
                from services.scene_reference_service import resolve_scene_references
                order = await db.orders.find_one({"id": order_id}, {"_id": 0})
                plan = await db.production_plans.find_one(
                    {"id": (order or {}).get("production_plan_id"), "is_archived": False},
                    {"_id": 0},
                ) if order else None
                scene = await db.scene_plans.find_one(
                    {"order_id": order_id, "scene_index": int(scene_index),
                     "is_archived": False},
                    {"_id": 0},
                ) if plan else None
                if order and plan and scene:
                    pkg = await resolve_scene_references(order, plan, scene)
                    def _trim(r):
                        return {k: v for k, v in r.items() if k != "url"} if isinstance(r, dict) else r
                    extras = {
                        "child_ref": _trim(pkg.get("child_ref")),
                        "extra_char_refs": [_trim(r) for r in (pkg.get("extra_char_refs") or [])],
                        "toy_ref": _trim(pkg.get("toy_ref")),
                        "available": pkg.get("available"),
                        "skipped_reasons": pkg.get("skipped_reasons"),
                        "injected_count": pkg.get("injected_count"),
                        "prompt_augmentation": pkg.get("prompt_augmentation"),
                        "support_true_refs": True,
                    }
            except Exception as e:  # noqa: BLE001
                extras = {"error": f"{type(e).__name__}: {e}"}
        out["scene_image_extras"] = extras

    return out


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------
async def run_stage_test(stage_key: str, input_payload: dict, admin_id: str | None,
                         preview_only: bool = False) -> dict:
    if stage_key not in SUPPORTED_STAGES:
        raise ValueError(f"Unsupported stage_key: {stage_key}")
    started = time.monotonic()
    started_iso = _now()
    provider, model_name, model_source = await resolve_model(stage_key, "anthropic", "claude-sonnet-4-5-20250929")
    transport = await resolve_transport(stage_key) if stage_key in ("scenario_generation", "production_planning") else "n/a"
    env_key = PROVIDER_ENV_MAP.get(provider) or "—"

    # Resolve the prompt the live pipeline would use, then hash it.
    prompt_admin, prompt_src, _ = await resolve_prompt(stage_key, dict(input_payload))
    prompt_used_for_hash = prompt_admin or ""
    prompt_hash = _hash(prompt_used_for_hash)
    estimated_cost = await _estimated_cost_for(stage_key)

    fallback_used = False
    error_message: str | None = None
    output_preview: dict | str | None = None
    result_summary = ""
    status = "success"

    # Phase F — Effective Prompt Preview short-circuits ALL executors.
    # No provider call, no API budget, no acknowledged_cost requirement.
    if preview_only:
        try:
            preview = await build_effective_prompt_preview(stage_key, input_payload)
            output_preview = preview
            prompt_used_for_hash = preview.get("effective_prompt", "")
            prompt_hash = preview.get("prompt_hash") or prompt_hash
            prompt_src = preview.get("prompt_source", prompt_src)
            status = "preview-only"
            result_summary = "effective prompt preview (no provider call)"
        except Exception as e:  # noqa: BLE001
            status = "failed"
            error_message = f"{type(e).__name__}: {e}"
            output_preview = None
            result_summary = error_message[:200]
    else:
        try:
            if stage_key == "scenario_generation":
                res = await _run_scenario_generation(input_payload)
            elif stage_key == "production_planning":
                res = await _run_production_planning(input_payload)
            elif stage_key == "child_character_i2i":
                res = await _run_child_character_i2i(input_payload)
            elif stage_key == "narration_generation":
                res = await _run_narration_generation(input_payload)
            elif stage_key == "video_generation":
                res = await _run_video_generation(input_payload)
            elif stage_key == "music_generation":
                res = await _run_music_generation_lab(input_payload)
            else:
                res = await _run_preview_only(stage_key, input_payload)
                status = "preview-only"
            output_preview = res.get("output_preview")
            result_summary = res.get("result_summary", "")
        except Exception as e:  # noqa: BLE001
            status = "failed"
            error_message = f"{type(e).__name__}: {e}"
            fallback_used = False  # the lab does not auto-fallback — admin sees the truth
            output_preview = None
            result_summary = error_message[:200]

    latency_ms = int((time.monotonic() - started) * 1000)

    record = {
        "id": str(uuid.uuid4()),
        "stage_key": stage_key,
        "created_at": started_iso,
        "completed_at": _now(),
        "created_by": admin_id,
        "input_summary": _sanitize_input(input_payload),
        "provider": provider,
        "model_name": model_name,
        "model_source": model_source,
        "transport": transport,
        "env_key": env_key,
        "prompt_source": prompt_src,
        "prompt_hash": prompt_hash,
        "prompt_preview": prompt_used_for_hash[:500],
        "latency_ms": latency_ms,
        "estimated_cost": estimated_cost,
        "fallback_used": fallback_used,
        "status": status,
        "error_message": error_message,
        "output_preview": output_preview,
        "result_summary": result_summary,
    }
    await db.stage_test_runs.insert_one(record)
    record.pop("_id", None)
    return record


def _sanitize_input(payload: dict) -> dict:
    """Trim long fields before storing for display."""
    out = {}
    for k, v in (payload or {}).items():
        if isinstance(v, str):
            out[k] = v[:500]
        elif isinstance(v, (int, float, bool)):
            out[k] = v
        elif isinstance(v, list):
            out[k] = v[:10]
        elif isinstance(v, dict):
            out[k] = {kk: (vv if not isinstance(vv, str) else vv[:200]) for kk, vv in v.items()}
        else:
            out[k] = str(v)[:200]
    return out


async def list_stage_test_runs(stage_key: str | None, limit: int = 30) -> list[dict]:
    q: dict = {}
    if stage_key:
        q["stage_key"] = stage_key
    rows = await db.stage_test_runs.find(q, {"_id": 0}).sort("created_at", -1).to_list(int(limit))
    return rows


async def get_stage_test_run(run_id: str) -> dict | None:
    return await db.stage_test_runs.find_one({"id": run_id}, {"_id": 0})
