"""Generation orchestrator — Phase 6A.

Responsibilities:
  * Create generation_jobs (cover + scene_image × N + narration × N + book_asset × N).
  * Process jobs sequentially with retry (max_attempts=3) and simple backoff.
  * Persist outputs into scene_images / narration_assets / book_assets collections.
  * Update order status: production_approved → assets_generating → assets_ready / media_failed.

Design principles:
  * Every provider call is abstracted (image_generation_service / audio_generation_service).
  * Every job records: attempt_count, provider, error_message, target_id.
  * Failures are isolated; order fails only if mandatory assets can't complete after retries.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from db import db
from models import OrderStatus, ORDER_STATUS_AR, get_order_output_type
from storage import put_object, APP_NAME
from services.image_generation_service import generate_image
from services.audio_generation_service import generate_audio, estimate_duration_seconds
from services.config_service import resolve_prompt
from services.child_character_service import safe_run as run_child_character_stage, _fetch_source_bytes
from services.extra_characters_service import safe_run as run_extra_characters_stage
from services.scene_reference_service import resolve_scene_references
from services.video_generation_service import (
    submit_all_then_poll, video_real_call_available,
)
from services.config_service import get_pipeline_config

logger = logging.getLogger("generation_orchestrator")

MAX_ATTEMPTS = 3


async def _run_video_generation_stage(order: dict, plan: dict, run_id: str) -> dict:
    """Phase L — fal.ai Kling per-scene video generation.

    Honest gates:
      * output_type must include video
      * pipeline_config.video_generation.enabled must be True
      * video_real_call_available() must be True (provider+key resolved)
    On any miss, returns {"ran": False, "reason": ...} — the assembly stage
    will fall back to the existing slideshow path automatically.
    """
    output_type = get_order_output_type(order)
    if output_type not in ("video", "both"):
        return {"ran": False, "reason": "output_type does not include video"}

    cfg = await get_pipeline_config()
    stage_cfg = (cfg.get("stages") or {}).get("video_generation") or {}
    if not stage_cfg.get("enabled", False):
        return {"ran": False, "reason": "video_generation disabled in pipeline_config"}

    if not await video_real_call_available():
        return {"ran": False, "reason": "FAL_KEY missing or provider not callable"}

    scenes = await db.scene_plans.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "is_archived": False},
        {"_id": 0},
    ).sort("scene_index", 1).to_list(50)
    if not scenes:
        return {"ran": False, "reason": "no scenes"}

    # Build scene packages — hybrid I2V/T2V driven by whether a scene image exists.
    sis = await db.scene_images.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "kind": "scene"},
        {"_id": 0, "scene_index": 1, "image_url": 1},
    ).to_list(50)
    img_by_idx = {int(s.get("scene_index") or 0): s.get("image_url") for s in sis}

    base = (os.environ.get("EXTERNAL_PUBLIC_URL")
            or os.environ.get("REACT_APP_BACKEND_URL")
            or "").rstrip("/")

    payloads: list[dict] = []
    for s in scenes:
        idx = int(s.get("scene_index") or 0)
        local_img = img_by_idx.get(idx)
        # fal.ai needs a publicly fetchable URL; stitch base + relative path.
        public_img = None
        if local_img and base:
            public_img = local_img if local_img.startswith("http") else f"{base}{local_img}"
        ip = (s.get("image_prompt") or {}).get("prompt_text") or ""
        vp = (s.get("video_prompt") or {}).get("prompt_text") or ""
        prompt = (vp or ip or s.get("visual_description") or s.get("scene_goal") or "warm storybook scene")
        # Include emotional_tone + camera hint to help motion direction.
        cam = (s.get("video_prompt") or {}).get("camera_motion_hint") or ""
        if cam:
            prompt = f"{prompt}. Camera: {cam}"
        payloads.append({
            "prompt":        prompt[:480],
            "image_url":     public_img,
            "duration":      5,
            "aspect_ratio":  "16:9",
            "_scene_index":  idx,
            "_scene_id":     s.get("id"),
        })

    logger.info(f"[video_generation] submitting {len(payloads)} clips order={order['id']}")
    results = await submit_all_then_poll(payloads, max_wait_s=900, poll_interval_s=10)

    # Persist clips and per-scene results.
    saved = 0
    for r, sc in zip(results, payloads):
        clip_url: str | None = None
        if r.get("bytes"):
            file_id = str(uuid.uuid4())
            storage_path = f"{APP_NAME}/orders/{order['id']}/generated/clips/{file_id}.mp4"
            loop = asyncio.get_running_loop()
            try:
                stored = await loop.run_in_executor(
                    None, lambda: put_object(storage_path, r["bytes"], r["mime"]),
                )
                await db.files.insert_one({
                    "id": file_id,
                    "user_id": order.get("user_id"),
                    "scope": "generated-video-clip",
                    "storage_path": stored.get("path", storage_path),
                    "original_filename": f"scene-{sc['_scene_index']:02d}.mp4",
                    "content_type": r["mime"],
                    "size": stored.get("size", len(r["bytes"])),
                    "is_deleted": False,
                    "created_at": _now(),
                })
                clip_url = f"/api/uploads/file/{file_id}"
                saved += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[video_generation] storage failed: {e}")

        await db.video_clips.update_one(
            {"order_id": order["id"], "scene_index": sc["_scene_index"]},
            {"$set": {
                "id":                str(uuid.uuid4()),
                "order_id":          order["id"],
                "production_plan_id": plan["id"],
                "scene_plan_id":     sc["_scene_id"],
                "scene_index":       sc["_scene_index"],
                "run_id":            run_id,
                "provider":          (r.get("meta") or {}).get("provider"),
                "model":             (r.get("meta") or {}).get("model"),
                "clip_strategy":     (r.get("meta") or {}).get("clip_strategy"),
                "request_id":        r.get("request_id"),
                "state":             r.get("state"),
                "video_url":         clip_url,
                "remote_video_url":  r.get("video_url"),
                "duration_seconds":  sc.get("duration") or 5,
                "aspect_ratio":      sc.get("aspect_ratio") or "16:9",
                "fallback_to_mock":  bool((r.get("meta") or {}).get("fallback_to_mock")),
                "real_call":         bool((r.get("meta") or {}).get("real_call")),
                "error":             (r.get("meta") or {}).get("error"),
                "updated_at":        _now(),
            }, "$setOnInsert": {"created_at": _now()}},
            upsert=True,
        )

    await db.orders.update_one(
        {"id": order["id"]},
        {"$set": {
            "video_generation_summary": {
                "total":    len(payloads),
                "saved":    saved,
                "failed":   len(payloads) - saved,
                "run_id":   run_id,
                "ran_at":   _now(),
            },
        }},
    )
    return {"ran": True, "saved": saved, "total": len(payloads)}


BACKOFF_SECONDS = [1, 3, 7]  # between attempts (index = attempt_count - 1)


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _append_status(order_id, from_status, to_status, by, actor_id=None, reason=None):
    entry = {"from": from_status, "to": to_status, "at": _now(),
             "by": by, "actor_id": actor_id, "reason": reason}
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": to_status, "updated_at": _now()},
         "$push": {"status_history": entry}},
    )


# ---------------- Job creation ----------------
async def _plan_jobs(order: dict) -> list[dict]:
    """Inspect approved plan and return a list of job descriptors to create."""
    plan_id = order.get("production_plan_id")
    plan = await db.production_plans.find_one({"id": plan_id}, {"_id": 0}) if plan_id else None
    if not plan:
        return []
    scenes = await db.scene_plans.find(
        {"order_id": order["id"], "production_plan_id": plan_id, "is_archived": False},
        {"_id": 0},
    ).sort("scene_index", 1).to_list(50)
    pages = await db.book_pages.find(
        {"order_id": order["id"], "production_plan_id": plan_id, "is_archived": False},
        {"_id": 0},
    ).sort("page_number", 1).to_list(50)

    jobs = []
    output_type = get_order_output_type(order)
    needs_video = output_type in ("video", "both")
    needs_pdf = output_type in ("pdf", "both")

    # 1 cover image — always (used by both video and PDF cover page)
    jobs.append({
        "job_type": "cover_image",
        "target_id": plan["id"],
        "meta": {"plan_id": plan["id"]},
    })
    # scene images (1 per scene) — always (shared by video frames and book pages)
    for s in scenes:
        jobs.append({"job_type": "scene_image", "target_id": s["id"], "meta": {"scene_index": s["scene_index"]}})
    # narration audio (1 per scene) — only when video is requested.
    # (Wave 1 PDF is text + image; narration is only consumed by the video.)
    if needs_video:
        for s in scenes:
            jobs.append({"job_type": "narration_audio", "target_id": s["id"], "meta": {"scene_index": s["scene_index"]}})
    # book_asset (1 per page) — only when PDF is requested.
    if needs_pdf:
        for p in pages:
            jobs.append({"job_type": "book_page_asset", "target_id": p["id"], "meta": {"page_number": p["page_number"]}})
    return jobs


async def _insert_jobs(order_id: str, run_id: str, jobs: list[dict]) -> list[dict]:
    docs = []
    for j in jobs:
        docs.append({
            "id": str(uuid.uuid4()),
            "order_id": order_id,
            "run_id": run_id,
            "job_type": j["job_type"],
            "target_id": j["target_id"],
            "meta": j.get("meta", {}),
            "status": "queued",
            "provider": None,
            "attempt_count": 0,
            "max_attempts": MAX_ATTEMPTS,
            "error_message": None,
            "output_url": None,
            "output_metadata": None,
            "created_at": _now(),
            "updated_at": _now(),
        })
    if docs:
        await db.generation_jobs.insert_many(docs)
    return docs


async def _update_job(job_id: str, patch: dict):
    patch["updated_at"] = _now()
    await db.generation_jobs.update_one({"id": job_id}, {"$set": patch})


async def _save_image_to_storage(order_id: str, kind: str, image_bytes: bytes, mime: str, user_id: str) -> str:
    """Save image bytes to object storage + files collection, return served URL."""
    file_id = str(uuid.uuid4())
    ext = "png" if "png" in mime else "jpg"
    storage_path = f"{APP_NAME}/orders/{order_id}/generated/{kind}/{file_id}.{ext}"
    # put_object is synchronous (requests); run in threadpool to avoid blocking loop
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: put_object(storage_path, image_bytes, mime))
    await db.files.insert_one({
        "id": file_id,
        "user_id": user_id,
        "scope": f"generated-{kind}",
        "storage_path": result.get("path", storage_path),
        "original_filename": f"{kind}.{ext}",
        "content_type": mime,
        "size": result.get("size", len(image_bytes)),
        "is_deleted": False,
        "created_at": _now(),
    })
    return f"/api/uploads/file/{file_id}"


# ---------------- Per-job executors ----------------
async def _execute_cover_image(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    prompt = plan.get("cover_prompt") or f"Book cover for children's story: {plan.get('title','')}"
    image_bytes, mime, meta = await generate_image(
        scene_prompt=prompt,
        style_guide=plan.get("style_guide"),
        character_note="",
        session_hint=f"cover-{order['id'][:6]}",
    )
    url = await _save_image_to_storage(order["id"], "cover", image_bytes, mime, order["user_id"])
    # Store in scene_images with scene_plan_id=None marks it as cover
    # Actually we'll use a separate field in the plan snapshot or a dedicated record.
    # Keep it clean: put cover into scene_images with scene_plan_id=null and a kind marker.
    await db.scene_images.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "scene_plan_id": None,
        "generation_job_id": job["id"],
        "kind": "cover",
        "image_url": url,
        "prompt_used": meta.get("prompt_used"),
        "provider": meta.get("provider"),
        "source_type": meta.get("provider"),
        "created_at": _now(),
    })
    return url, meta


def _build_scene_image_context(order: dict, plan: dict, scene: dict) -> dict:
    """Flat variable context for admin-configurable scene_image_generation prompt.

    Only fields that are actually available are exposed — no invented values.
    Lists are joined into comma-separated strings so $vars always stringify cleanly.
    """
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    duration = order.get("duration", {}) or {}
    child = data.get("child", {}) or {}
    pers = data.get("personalization", {}) or {}
    chars = data.get("characters", []) or []
    audio_bg = (data.get("audio_background") or {}).get("mode") or "music"

    img_prompt_obj = scene.get("image_prompt") or {}

    # Phase D.3 — include auto-extracted visuals for uploaded assets.
    toy_desc = pers.get("toy_description_auto") or ""
    toy_name = ((pers.get("favorites") or {}).get("toy") or {}).get("name") or ""
    toy_block = ""
    if toy_desc or toy_name:
        toy_block = (f"{toy_name}: " if toy_name else "") + (toy_desc or "")
    extra_chars_visuals = "; ".join(
        f"{c.get('name') or c.get('type')}: {c['visual_description_auto']}"
        for c in chars
        if c.get("role") == "visible" and c.get("visual_description_auto")
    )

    return {
        # Child
        "child_name":         child.get("name", ""),
        "child_age":          child.get("age", ""),
        "child_gender":       "ولد" if child.get("gender") == "male" else "بنت",
        "child_appearance_notes": child.get("appearance_notes", "") or "",
        "child_hijab":        "نعم" if child.get("hijab") else "لا",
        # Scene
        "scene_index":        scene.get("scene_index", ""),
        "scene_title":        scene.get("title", ""),
        "scene_goal":         scene.get("scene_goal", ""),
        "narration_text":     scene.get("narration_text", ""),
        "book_text":          scene.get("book_text", ""),
        "emotional_tone":     scene.get("emotional_tone", ""),
        "visual_description": scene.get("visual_description", ""),
        "background_setting": scene.get("background_setting", ""),
        "key_objects":        ", ".join(scene.get("key_objects", []) or []) or "لا يوجد",
        "continuity_notes":   scene.get("continuity_notes", ""),
        # Plan-level
        "selected_scenario_title":           plan.get("title", ""),
        "selected_scenario_emotional_angle": plan.get("emotional_angle", "") or "",
        "selected_scenario_visual_style":    (plan.get("style_guide") or {}).get("art_direction", ""),
        "style_guide":                       ", ".join(f"{k}:{v}" for k, v in (plan.get("style_guide") or {}).items()) or "",
        "character_reference_note":          img_prompt_obj.get("character_reference_note", ""),
        # Style
        "story_type":  enriched.get("type_name", "") or "",
        "tone":        enriched.get("tone_name", "") or "",
        "setting":     enriched.get("setting_name", "") or "",
        "language":    enriched.get("language_name", "") or "",
        "voice":       enriched.get("voice_name", "") or "",
        # Duration
        "duration_label":   duration.get("label", ""),
        "duration_seconds": duration.get("seconds", ""),
        "scene_target":     duration.get("scene_target", ""),
        # Extras
        "favorites_summary":  "، ".join(
            f"{k}:{(v or {}).get('name','')}"
            for k, v in (pers.get("favorites") or {}).items() if (v or {}).get("selected")
        ) or "لا يوجد",
        "characters_summary": "، ".join(
            f"{c.get('type','')}:{c.get('name','')}" for c in chars if c.get("name")
        ) or "لا يوجد",
        "extra_characters_visuals": extra_chars_visuals or "لا يوجد",
        "toy_summary":             toy_block or "لا يوجد",
        "audio_background_mode":   audio_bg,
    }


async def _resolve_scene_image_prompt(order: dict, plan: dict, scene: dict) -> tuple[str | None, str, str]:
    """Try admin template; returns (rendered, source, reason). On any failure
    the caller uses the hardcoded `scene.image_prompt.prompt_text` from DB.
    """
    try:
        ctx = _build_scene_image_context(order, plan, scene)
    except Exception as e:  # noqa: BLE001 — never crash the pipeline
        return None, "default", f"context_error:{type(e).__name__}"
    return await resolve_prompt("scene_image_generation", ctx)


async def _execute_scene_image(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    scene = await db.scene_plans.find_one({"id": job["target_id"]}, {"_id": 0})
    if not scene:
        raise ValueError(f"scene_plan {job['target_id']} not found")
    default_prompt = (scene.get("image_prompt") or {}).get("prompt_text") or scene.get("visual_description") or ""
    char_note = (scene.get("image_prompt") or {}).get("character_reference_note") or ""

    # Phase B.3 — admin prompt override (scene-level, falls back cleanly).
    admin_prompt, prompt_src, reason = await _resolve_scene_image_prompt(order, plan, scene)
    if prompt_src == "admin":
        logger.info(f"[config] stage=scene_image_generation prompt_source=admin {reason}")
        img_prompt = admin_prompt
    else:
        logger.info(f"[config] stage=scene_image_generation prompt_source=default reason={reason}")
        img_prompt = default_prompt

    # Phase D.3 — auto-inject uploaded toy/object and extra-character visual
    # descriptions so they appear in scenes. Appended only when present;
    # legacy orders with no uploads are unaffected.
    data = order.get("data") or {}
    pers = data.get("personalization") or {}
    toy_desc = pers.get("toy_description_auto") or ""
    toy_name = ((pers.get("favorites") or {}).get("toy") or {}).get("name") or ""
    if toy_desc or toy_name:
        if toy_name and toy_name.lower() in (img_prompt or "").lower():
            # toy is already referenced in the prompt — only inject the visual detail
            img_prompt = (img_prompt or "") + f" Visual reference for {toy_name}: {toy_desc}" if toy_desc else img_prompt
        else:
            pref = f" Important recurring object: {toy_name + ' — ' if toy_name else ''}{toy_desc}".rstrip()
            img_prompt = (img_prompt or "") + pref
    extra_visuals = [
        f"{(c.get('name') or c.get('type'))}: {c['visual_description_auto']}"
        for c in (data.get("characters") or [])
        if c.get("role") == "visible" and c.get("visual_description_auto")
    ]
    if extra_visuals:
        img_prompt = (img_prompt or "") + " Extra characters visual hints — " + " | ".join(extra_visuals)

    # Phase E — Reference Asset Injection -----------------------------------
    # Resolve which existing reference images (child/extras/toy) belong in this
    # scene, then fetch their bytes from internal storage. Failures are
    # recorded as granular `skipped_reasons` so the storyboard shows the truth.
    ref_pkg = await resolve_scene_references(order, plan, scene)
    ref_payload: list[dict] = []
    ref_skipped: list[dict] = list(ref_pkg.get("skipped_reasons") or [])

    async def _attach(kind: str, ref: dict | None):
        if not ref or not ref.get("url"):
            return
        bytes_tuple = await _fetch_source_bytes(ref["url"])
        if not bytes_tuple:
            ref_skipped.append({
                "kind": kind, "id": ref.get("character_id"),
                "character_index": ref.get("character_index"),
                "name": ref.get("name"),
                "reason": "reference_fetch_failed",
            })
            return
        ref_payload.append({
            "image_bytes": bytes_tuple[0],
            "mime_type":   bytes_tuple[1],
            "kind":        kind,
            "name":        ref.get("name"),
        })

    await _attach("child", ref_pkg.get("child_ref"))
    for r in ref_pkg.get("extra_char_refs") or []:
        await _attach("extra", r)
    await _attach("toy", ref_pkg.get("toy_ref"))

    image_bytes, mime, meta = await generate_image(
        scene_prompt=img_prompt,
        style_guide=plan.get("style_guide"),
        character_note=char_note,
        session_hint=f"scene-{scene.get('scene_index')}-{order['id'][:6]}",
        references=ref_payload,
        support_true_refs=True,
        prompt_augmentation=ref_pkg.get("prompt_augmentation", ""),
    )
    url = await _save_image_to_storage(order["id"], "scene", image_bytes, mime, order["user_id"])

    # Phase E — record reference usage on scene_plans for storyboard + cost.
    log_extra_ids = [r.get("character_id") for r in ref_pkg.get("extra_char_refs", []) if r.get("character_id")]
    log_extra_idxs = [r.get("character_index") for r in ref_pkg.get("extra_char_refs", [])
                      if r.get("character_index") is not None]
    scene_ref_log = {
        "available": ref_pkg.get("available", {}),
        "child_reference_used":             bool(ref_pkg.get("child_ref")),
        "extra_character_reference_ids_used":   log_extra_ids,
        "extra_character_reference_indexes_used": log_extra_idxs,
        "toy_reference_used":               bool(ref_pkg.get("toy_ref")),
        "references_injected_count":        meta.get("references_count", 0) if meta.get("references_used") else 0,
        "references_attempted":             bool(meta.get("references_attempted")),
        "references_used":                  bool(meta.get("references_used")),
        "fallback_path":                    meta.get("fallback_path"),
        "fallback_reason":                  meta.get("fallback_reason"),
        "skipped_reasons":                  ref_skipped,
        "final_effective_image_prompt":     meta.get("prompt_used"),
        "updated_at":                       _now(),
    }
    await db.scene_plans.update_one(
        {"id": scene["id"]},
        {"$set": {"scene_reference_log": scene_ref_log}},
    )

    await db.scene_images.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "scene_plan_id": scene["id"],
        "generation_job_id": job["id"],
        "kind": "scene",
        "scene_index": scene.get("scene_index"),
        "image_url": url,
        "prompt_used": meta.get("prompt_used"),
        "provider": meta.get("provider"),
        "source_type": meta.get("provider"),
        "references_used": bool(meta.get("references_used")),
        "references_count": meta.get("references_count", 0),
        "reference_fallback_path": meta.get("fallback_path"),
        "created_at": _now(),
    })
    return url, meta


async def _execute_narration_audio(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    scene = await db.scene_plans.find_one({"id": job["target_id"]}, {"_id": 0})
    if not scene:
        raise ValueError(f"scene_plan {job['target_id']} not found")
    text = scene.get("narration_text") or ""
    voice = (order.get("enriched") or {}).get("voice_name")
    language = (order.get("enriched") or {}).get("language_name") or "ar"
    audio_bytes, mime, meta = await generate_audio(text=text, voice=voice, language=language)
    # In mock mode audio_bytes is None. Persist metadata-only record with URL=None.
    url = None
    if audio_bytes:
        # (Reserved for real provider): upload bytes to storage.
        file_id = str(uuid.uuid4())
        ext = "mp3" if "mpeg" in mime else "wav"
        storage_path = f"{APP_NAME}/orders/{order['id']}/generated/audio/{file_id}.{ext}"
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: put_object(storage_path, audio_bytes, mime))
        await db.files.insert_one({
            "id": file_id,
            "user_id": order["user_id"],
            "scope": "generated-audio",
            "storage_path": result.get("path", storage_path),
            "original_filename": f"narration.{ext}",
            "content_type": mime,
            "size": result.get("size", len(audio_bytes)),
            "is_deleted": False,
            "created_at": _now(),
        })
        url = f"/api/uploads/file/{file_id}"
    duration = meta.get("duration_seconds") or estimate_duration_seconds(text)
    await db.narration_assets.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "scene_plan_id": scene["id"],
        "generation_job_id": job["id"],
        "scene_index": scene.get("scene_index"),
        "text": text,
        "voice_type": meta.get("voice"),
        "language": language,
        "audio_url": url,
        "duration_seconds": duration,
        "provider": meta.get("provider"),
        "created_at": _now(),
    })
    return url or f"(mock) {duration}s", meta


async def _execute_book_page_asset(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    page = await db.book_pages.find_one({"id": job["target_id"]}, {"_id": 0})
    if not page:
        raise ValueError(f"book_page {job['target_id']} not found")
    # Reuse scene image for the same scene_index (Phase 6A rule).
    scene_img = await db.scene_images.find_one(
        {"order_id": order["id"], "production_plan_id": plan["id"],
         "scene_index": page.get("scene_index"), "kind": "scene"},
        {"_id": 0},
    )
    illustration_url = scene_img.get("image_url") if scene_img else None
    provider = "reused" if illustration_url else "pending"
    await db.book_assets.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "book_page_id": page["id"],
        "generation_job_id": job["id"],
        "page_number": page.get("page_number"),
        "scene_index": page.get("scene_index"),
        "illustration_url": illustration_url,
        "page_text": page.get("text"),
        "provider": provider,
        "created_at": _now(),
    })
    return illustration_url or "(pending reuse)", {"provider": provider}


# ---------------- Job dispatcher ----------------
JOB_EXECUTORS = {
    "cover_image": _execute_cover_image,
    "scene_image": _execute_scene_image,
    "narration_audio": _execute_narration_audio,
    "book_page_asset": _execute_book_page_asset,
}


async def _process_job_with_retry(job: dict, order: dict, plan: dict) -> bool:
    executor = JOB_EXECUTORS.get(job["job_type"])
    if not executor:
        await _update_job(job["id"], {"status": "failed", "error_message": f"unknown job_type {job['job_type']}"})
        return False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        await _update_job(job["id"], {"status": "processing", "attempt_count": attempt})
        try:
            output, meta = await executor(job, order, plan)
            await _update_job(job["id"], {
                "status": "completed",
                "provider": meta.get("provider"),
                "output_url": output if isinstance(output, str) else None,
                "output_metadata": meta,
                "error_message": None,
            })
            return True
        except Exception as e:
            err = f"attempt {attempt} failed: {type(e).__name__}: {e}"
            logger.warning(f"job {job['id']} ({job['job_type']}) {err}")
            await _update_job(job["id"], {"error_message": err})
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
            else:
                await _update_job(job["id"], {"status": "failed"})
                return False
    return False


# ---------------- Run (entrypoint) ----------------
async def run_asset_generation(order_id: str, run_id: str):
    """Full pipeline — sequential dispatch of all jobs."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    if not order.get("production_approved"):
        logger.warning(f"run_asset_generation called for unapproved order {order_id}")
        return

    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0})
    if not plan:
        await _append_status(order_id, order.get("status"), OrderStatus.MEDIA_FAILED.value, "system",
                             reason="no production plan found")
        return

    # Create jobs
    job_descriptors = await _plan_jobs(order)
    if not job_descriptors:
        await _append_status(order_id, order.get("status"), OrderStatus.MEDIA_FAILED.value, "system",
                             reason="no jobs could be planned")
        return
    jobs = await _insert_jobs(order_id, run_id, job_descriptors)

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "asset_generation_run_id": run_id,
            "asset_generation_started_at": _now(),
            "asset_generation_summary": {
                "total": len(jobs),
                "queued": len(jobs),
                "processing": 0,
                "completed": 0,
                "failed": 0,
            },
        }},
    )
    await _append_status(order_id, order.get("status"), OrderStatus.ASSETS_GENERATING.value, "system",
                         reason=f"start assets generation (run {run_id[:8]}, {len(jobs)} jobs)")

    # --- Phase C: child_character_i2i (OPTIONAL, disabled by default) -------
    # Runs BEFORE any scene image generation. Never blocks the pipeline — even
    # if it fails, downstream stages proceed with the existing text-only flow.
    try:
        cc_result = await run_child_character_stage(order, plan)
        if cc_result.get("ran") and cc_result.get("status") == "failed":
            logger.warning(
                f"[child_character_i2i] stage failed but pipeline continues "
                f"(order={order_id}, reason={cc_result.get('reason')})"
            )
    except Exception as e:  # noqa: BLE001 — safe_run should never raise, defense-in-depth
        logger.exception(f"[child_character_i2i] unexpected crash (ignored): {e}")

    # --- Phase D: extra_character_i2i (OPTIONAL, disabled by default) -------
    # Processes every visible extra character that has an uploaded image.
    # Always safe: per-character try/except in the service, plus the outer
    # try/except here. If no eligible character exists, early-return.
    try:
        ec_result = await run_extra_characters_stage(order)
        if ec_result.get("ran"):
            logger.info(
                f"[extra_character_i2i] processed count={ec_result.get('count')} "
                f"results={[r.get('status') for r in (ec_result.get('results') or [])]}"
            )
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[extra_character_i2i] unexpected crash (ignored): {e}")

    # Process in order: cover first, then scene_images, then narration, then book assets
    priority = {"cover_image": 0, "scene_image": 1, "narration_audio": 2, "book_page_asset": 3}
    jobs.sort(key=lambda j: (priority.get(j["job_type"], 9), j.get("meta", {}).get("scene_index", 0)))

    completed = 0
    failed = 0
    for job in jobs:
        ok = await _process_job_with_retry(job, order, plan)
        if ok:
            completed += 1
        else:
            failed += 1
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"asset_generation_summary.completed": completed,
                      "asset_generation_summary.failed": failed,
                      "asset_generation_summary.queued": len(jobs) - completed - failed,
                      "asset_generation_summary.processing": 0,
                      "updated_at": _now()}},
        )

    # --- Phase L: video_generation (OPTIONAL, real fal.ai Kling) -----------
    # Runs ONLY when video output is requested AND the stage is enabled in
    # pipeline_config AND fal.ai key resolves. Always safe — failures
    # degrade silently to the slideshow assembly path.
    try:
        await _run_video_generation_stage(order, plan, run_id)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[video_generation] unexpected crash (ignored): {e}")

    # Decide terminal status
    # Mandatory job set depends on the requested deliverable:
    #   * video only → cover + scene_images + narration
    #   * pdf   only → cover + scene_images + book_assets
    #   * both       → cover + scene_images + narration + book_assets
    output_type = get_order_output_type(order)
    mandatory_types: set[str] = {"cover_image", "scene_image"}
    if output_type in ("video", "both"):
        mandatory_types.add("narration_audio")
    if output_type in ("pdf", "both"):
        mandatory_types.add("book_page_asset")
    failed_mandatory = await db.generation_jobs.count_documents({
        "order_id": order_id,
        "run_id": run_id,
        "job_type": {"$in": list(mandatory_types)},
        "status": "failed",
    })
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"asset_generation_completed_at": _now()}},
    )
    if failed_mandatory == 0:
        await _append_status(order_id, OrderStatus.ASSETS_GENERATING.value, OrderStatus.ASSETS_READY.value, "system",
                             reason=f"all assets ready ({completed}/{len(jobs)})")
    else:
        await _append_status(order_id, OrderStatus.ASSETS_GENERATING.value, OrderStatus.MEDIA_FAILED.value, "system",
                             reason=f"{failed_mandatory} mandatory jobs failed after retries")


async def retry_single_job(job_id: str) -> dict:
    """Admin endpoint can call this to retry a single failed job fresh."""
    job = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        return {"ok": False, "error": "job not found"}
    order = await db.orders.find_one({"id": job["order_id"]}, {"_id": 0})
    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0})
    # Reset counters and run
    await _update_job(job_id, {"status": "queued", "attempt_count": 0, "error_message": None, "output_url": None})
    # Re-fetch
    job = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    ok = await _process_job_with_retry(job, order, plan)
    return {"ok": ok}
