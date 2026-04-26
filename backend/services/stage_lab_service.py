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
    "scene_image_generation",
    "narration_generation",
    "video_generation",
    "music_generation",
)

REAL_CALL_STAGES = {
    "scenario_generation",
    "production_planning",
    "child_character_i2i",
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


# ---------------------------------------------------------------------------
# Preview-only executor — for stages we do not want to burn budget on or that
# need a real order's downstream context (scene image needs a real plan).
# ---------------------------------------------------------------------------
async def _run_preview_only(stage_key: str, input_payload: dict) -> dict:
    """Render the prompt template the live pipeline would have used; do NOT call the provider."""
    ctx = dict(input_payload)
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
# Public entry
# ---------------------------------------------------------------------------
async def run_stage_test(stage_key: str, input_payload: dict, admin_id: str | None) -> dict:
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

    try:
        if stage_key == "scenario_generation":
            res = await _run_scenario_generation(input_payload)
        elif stage_key == "production_planning":
            res = await _run_production_planning(input_payload)
        elif stage_key == "child_character_i2i":
            res = await _run_child_character_i2i(input_payload)
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
