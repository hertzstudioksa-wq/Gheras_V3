"""Admin Storyboard / Pipeline Trace — READ-ONLY debug view.

Aggregates existing data from multiple collections into a single response
that powers `/admin/orders/{id}/storyboard` in the UI.

RULES (enforced here):
  1. We NEVER invent fields. Anything not stored is omitted or marked as an
     estimate (e.g. `latency_is_estimate=true`).
  2. We NEVER create new collections. Read-only aggregation only.
  3. We NEVER change business logic. This layer must not call any executor.
  4. Disabled stages are returned with `status="skipped"` (NOT hidden).
  5. Admin API keys are never returned. Prompt text IS returned (admin only).
"""
import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from auth import require_admin
from db import db
from models import ORDER_STATUS_AR
from services.config_service import (
    DEFAULT_MODELS,
    STAGE_DISPLAY_NAMES,
    get_pipeline_config,
)

router = APIRouter(
    prefix="/admin", tags=["admin-storyboard"], dependencies=[Depends(require_admin)]
)


# --- helpers ---------------------------------------------------------------
STAGE_ORDER = [
    "scenario_generation",
    "production_planning",
    "child_character_i2i",
    "extra_character_i2i",
    "scene_image_generation",
    "narration_generation",
    "book_assets_generation",
    "video_assembly",
    "pdf_assembly",
]

# Extra display names for stages that aren't in STAGE_DISPLAY_NAMES.
EXTRA_STAGE_NAMES = {
    "book_assets_generation": {"ar": "صفحات الكتاب", "en": "Book Assets"},
    "video_assembly":         {"ar": "تجميع الفيديو", "en": "Video Assembly"},
    "pdf_assembly":           {"ar": "تجميع الـ PDF", "en": "PDF Assembly"},
}


def _display_name(stage_key: str) -> dict:
    return STAGE_DISPLAY_NAMES.get(stage_key) or EXTRA_STAGE_NAMES.get(stage_key) or {
        "ar": stage_key, "en": stage_key
    }


def _prompt_hash(prompt: str | None) -> str | None:
    if not prompt:
        return None
    try:
        return "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
    except Exception:  # noqa: BLE001
        return None


def _parse_iso(s: str | None):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None


def _latency_ms(start: str | None, end: str | None) -> int | None:
    a, b = _parse_iso(start), _parse_iso(end)
    if a and b and b >= a:
        return int((b - a).total_seconds() * 1000)
    return None


def _status_from_order_stage(status: str, stage_key: str, stage_enabled: bool) -> str:
    """Derive a coarse status for the stage based on the order lifecycle.

    We only use it as a fallback when the stage has no jobs/records to
    authoritatively report status.
    """
    if not stage_enabled:
        return "skipped"
    order_status = status or ""
    # Map order status → which stages should be considered done at that point.
    DONE_AFTER = {
        "scenario_generation":   {"scenarios_ready", "scenario_selected", "ready_for_ai",
                                   "production_planning", "production_ready", "production_approved",
                                   "assets_generating", "assets_ready", "assembling",
                                   "delivered", "media_failed"},
        "production_planning":   {"production_ready", "production_approved", "assets_generating",
                                   "assets_ready", "assembling", "delivered", "media_failed"},
        "child_character_i2i":   {"assets_generating", "assets_ready", "assembling",
                                   "delivered", "media_failed"},
        "scene_image_generation":{"assets_ready", "assembling", "delivered", "media_failed"},
        "narration_generation":  {"assets_ready", "assembling", "delivered", "media_failed"},
        "book_assets_generation":{"assets_ready", "assembling", "delivered", "media_failed"},
        "video_assembly":        {"delivered"},
        "pdf_assembly":          {"delivered"},
    }
    IN_PROGRESS = {
        "scenario_generation":   {"scenarios_generating"},
        "production_planning":   {"production_planning"},
        "child_character_i2i":   {"assets_generating"},
        "scene_image_generation":{"assets_generating"},
        "narration_generation":  {"assets_generating"},
        "book_assets_generation":{"assets_generating"},
        "video_assembly":        {"assembling"},
        "pdf_assembly":          {"assembling"},
    }
    if order_status in DONE_AFTER.get(stage_key, set()):
        return "completed"
    if order_status in IN_PROGRESS.get(stage_key, set()):
        return "running"
    if order_status == "media_failed":
        return "failed"
    return "pending"


async def _resolve_model_current(stage_key: str) -> tuple[str, str, str]:
    """Return the currently-configured model for a stage (admin override if any)."""
    doc = await db.model_registry.find_one(
        {"stage_key": stage_key, "active": True},
        {"_id": 0, "provider": 1, "model_name": 1},
    )
    defaults = DEFAULT_MODELS.get(stage_key, {})
    if doc and doc.get("provider") and doc.get("model_name"):
        return doc["provider"], doc["model_name"], "admin"
    return (
        defaults.get("provider") or "—",
        defaults.get("model_name") or "—",
        "fallback",
    )


async def _resolve_prompt_current(stage_key: str) -> dict:
    """Return info about the currently-configured active template (if any)."""
    doc = await db.prompt_templates.find_one(
        {"stage_key": stage_key, "active": True},
        {"_id": 0, "id": 1, "version": 1, "name": 1},
    )
    if doc:
        return {
            "prompt_source": "admin",
            "prompt_template_id": doc.get("id"),
            "prompt_template_version": doc.get("version"),
            "prompt_template_name": doc.get("name"),
        }
    return {
        "prompt_source": "default",
        "prompt_template_id": None,
        "prompt_template_version": None,
        "prompt_template_name": None,
    }


def _history_for_stage(history: list[dict], stage_key: str) -> list[dict]:
    """Filter order.status_history into events relevant to the stage."""
    if not history:
        return []
    MAP_STATUSES = {
        "scenario_generation":   {"scenarios_generating", "scenarios_ready", "scenario_selected"},
        "production_planning":   {"production_planning", "production_ready", "production_approved"},
        "child_character_i2i":   {"assets_generating"},
        "scene_image_generation":{"assets_generating", "assets_ready"},
        "narration_generation":  {"assets_generating", "assets_ready"},
        "book_assets_generation":{"assets_generating", "assets_ready"},
        "video_assembly":        {"assembling", "delivered", "media_failed"},
        "pdf_assembly":          {"assembling", "delivered", "media_failed"},
    }
    target = MAP_STATUSES.get(stage_key, set())
    out = []
    for e in history:
        if e.get("to") in target or e.get("from") in target:
            out.append({
                "at":   e.get("at"),
                "type": "status",
                "message": f"{e.get('from')} → {e.get('to')} ({e.get('by') or '—'})"
                            + (f" · {e.get('reason')}" if e.get("reason") else ""),
            })
    return out


def _job_events(jobs: list[dict]) -> list[dict]:
    """Convert generation_jobs to event entries (errors/attempts)."""
    out = []
    for j in jobs:
        meta = j.get("output_metadata") or {}
        if j.get("error_message"):
            out.append({
                "at": j.get("updated_at"),
                "type": "job_error",
                "message": f"[{j.get('job_type')}] attempt {j.get('attempt_count')}: {j['error_message']}",
            })
        if j.get("status") == "completed" and meta.get("provider"):
            out.append({
                "at": j.get("updated_at"),
                "type": "job_completed",
                "message": f"[{j.get('job_type')}] provider={meta.get('provider')} model={meta.get('model','—')}",
            })
    return out


# --- per-stage builders ----------------------------------------------------
async def _stage_scenario_generation(order: dict, pipeline_cfg: dict) -> dict:
    sg = order.get("scenarios_generation") or {}
    # Get all scenarios for this order (latest batch first)
    scenarios = await db.scenarios.find({"order_id": order["id"]}, {"_id": 0}).sort(
        [("created_at", -1), ("scenario_index", 1)]
    ).to_list(50)
    current_batch = order.get("current_scenario_batch_id")
    current = [s for s in scenarios if s.get("scenario_batch_id") == current_batch]
    enabled = (pipeline_cfg.get("stages", {}).get("scenario_generation") or {}).get("enabled", True)
    # Find timing: first scenario.created_at within current batch = started; sg.completed_at = ended
    started_at = None
    if current:
        started_at = min((s.get("created_at") for s in current if s.get("created_at")), default=None)
    ended_at = sg.get("completed_at")
    # Status: prefer source-based; "fallback" indicates LLM failure but content generated.
    raw_source = sg.get("source")  # "ai" | "fallback" | None
    if current:
        status = "completed"
    elif order.get("status") == "scenarios_generating":
        status = "running"
    elif sg.get("error"):
        status = "failed"
    else:
        status = "pending"
    model = await _resolve_model_current("scenario_generation")
    prompt_info = await _resolve_prompt_current("scenario_generation")
    prompt_used = order.get("ai_prompt_snapshot")

    input_summary = {
        "child_name":    ((order.get("data") or {}).get("child") or {}).get("name"),
        "child_age":     ((order.get("data") or {}).get("child") or {}).get("age"),
        "category":      ((order.get("data") or {}).get("category") or {}).get("name"),
        "subcategory":   ((order.get("data") or {}).get("subcategory") or {}).get("name"),
        "duration_label": (order.get("duration") or {}).get("label"),
        "scene_target":  (order.get("duration") or {}).get("scene_target"),
        "scene_target_bucket": (order.get("duration") or {}).get("scene_target_bucket"),
        "output_type":   ((order.get("data") or {}).get("delivery") or {}).get("output_type") or "both",
        "regeneration_count": order.get("regeneration_count", 0),
    }
    output_summary = {
        "total_scenarios_all_batches": len(scenarios),
        "current_batch_count": len(current),
        "current_batch_id": current_batch,
        "selected_scenario_id": order.get("selected_scenario_id"),
        "scenarios": [
            {
                "id":           s.get("id"),
                "index":        s.get("scenario_index"),
                "title":        s.get("title"),
                "summary_preview": (s.get("summary") or "")[:140],
                "source":       s.get("source"),
                "is_selected":  s.get("is_selected", False),
                "batch_id":     s.get("scenario_batch_id"),
            }
            for s in current[:3]
        ],
    }
    events = _history_for_stage(order.get("status_history", []), "scenario_generation")
    if sg.get("error"):
        events.append({"at": ended_at, "type": "error", "message": sg["error"][:500]})

    return {
        "stage_key": "scenario_generation",
        "name_ar": _display_name("scenario_generation")["ar"],
        "name_en": _display_name("scenario_generation")["en"],
        "config_enabled": enabled,
        "status": status if enabled else "skipped",
        "started_at": started_at,
        "ended_at": ended_at,
        "latency_ms_estimate": _latency_ms(started_at, ended_at),
        "latency_is_estimate": True,
        "attempts": order.get("regeneration_count", 0) + 1 if current else 0,
        "provider": model[0],
        "model_name": model[1],
        "model_source": model[2],
        **prompt_info,
        "prompt_used": prompt_used,
        "prompt_hash": _prompt_hash(prompt_used),
        "fallback_used": raw_source == "fallback",
        "error_message": sg.get("error"),
        "mock_mode": False,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "events": events,
        "actions": {
            "regenerate_endpoint": f"POST /api/admin/orders/{order['id']}/scenarios/regenerate",
            "supports_copy_prompt": bool(prompt_used),
            "download_url": None,
        },
    }


async def _stage_production_planning(order: dict, pipeline_cfg: dict) -> dict:
    pg = order.get("production_generation") or {}
    plan_id = order.get("production_plan_id")
    plan = await db.production_plans.find_one({"id": plan_id}, {"_id": 0}) if plan_id else None
    scenes = await db.scene_plans.find(
        {"order_id": order["id"], "is_archived": False}, {"_id": 0}
    ).sort("scene_index", 1).to_list(50) if plan_id else []
    pages = await db.book_pages.count_documents(
        {"order_id": order["id"], "is_archived": False}
    ) if plan_id else 0
    chars = await db.character_profiles.count_documents(
        {"order_id": order["id"], "is_archived": False}
    ) if plan_id else 0
    enabled = (pipeline_cfg.get("stages", {}).get("production_planning") or {}).get("enabled", True)

    started_at = plan.get("created_at") if plan else None
    ended_at = pg.get("completed_at") or (plan.get("created_at") if plan else None)

    if plan:
        status = "completed"
    elif order.get("status") == "production_planning":
        status = "running"
    elif pg.get("error"):
        status = "failed"
    else:
        status = "pending"
    model = await _resolve_model_current("production_planning")
    prompt_info = await _resolve_prompt_current("production_planning")
    input_summary = {
        "selected_scenario_title": (order.get("selected_scenario_snapshot") or {}).get("title"),
        "duration_seconds": (order.get("duration") or {}).get("seconds"),
        "scene_target":     (order.get("duration") or {}).get("scene_target"),
        "scene_target_bucket": (order.get("duration") or {}).get("scene_target_bucket"),
        "audio_background": ((order.get("data") or {}).get("audio_background") or {}).get("mode"),
        "output_type":      ((order.get("data") or {}).get("delivery") or {}).get("output_type") or "both",
    }
    output_summary = {
        "plan_id": plan_id,
        "title":   (plan or {}).get("title"),
        "story_summary_preview": ((plan or {}).get("story_summary") or "")[:200],
        "main_message_preview":  ((plan or {}).get("main_message") or "")[:200],
        "scene_count": len(scenes),
        "book_pages_count": pages,
        "character_profiles_count": chars,
        "style_guide": (plan or {}).get("style_guide") or {},
        "cover_prompt_preview": ((plan or {}).get("cover_prompt") or "")[:240],
        # Phase D.4 — story-level downstream fields
        "story_keywords":       (plan or {}).get("story_keywords") or [],
        "story_music_prompt":   (plan or {}).get("story_music_prompt") or "",
        "story_music_keywords": (plan or {}).get("story_music_keywords") or [],
        "story_voice_prompt":   (plan or {}).get("story_voice_prompt") or "",
        "scenes_detail": [
            {
                "scene_index":        s.get("scene_index"),
                "title":              s.get("title"),
                "scene_goal":         s.get("scene_goal"),
                "emotional_tone":     s.get("emotional_tone"),
                "narration_preview":  (s.get("narration_text") or "")[:160],
                "book_text_preview":  (s.get("book_text") or "")[:160],
                "key_objects":        s.get("key_objects") or [],
                "video_prompt":       s.get("video_prompt") or "",
                "voice_prompt":       s.get("voice_prompt") or "",
                "music_prompt":       s.get("music_prompt") or "",
                "music_keywords":     s.get("music_keywords") or [],
                "camera_motion_hint": s.get("camera_motion_hint") or "",
                "estimated_duration_seconds": s.get("estimated_duration_seconds"),
                "word_count":         s.get("word_count"),
            }
            for s in scenes
        ],
        "production_approved": bool(order.get("production_approved")),
    }
    events = _history_for_stage(order.get("status_history", []), "production_planning")
    if pg.get("error"):
        events.append({"at": ended_at, "type": "error", "message": pg["error"][:500]})

    return {
        "stage_key": "production_planning",
        "name_ar": _display_name("production_planning")["ar"],
        "name_en": _display_name("production_planning")["en"],
        "config_enabled": enabled,
        "status": status if enabled else "skipped",
        "started_at": started_at,
        "ended_at": ended_at,
        "latency_ms_estimate": _latency_ms(started_at, ended_at),
        "latency_is_estimate": True,
        "attempts": 1 if plan else 0,
        "provider": model[0],
        "model_name": model[1],
        "model_source": model[2],
        **prompt_info,
        "prompt_used": None,  # production prompt is built inline; not persisted
        "prompt_hash": None,
        "fallback_used": pg.get("source") == "fallback",
        "error_message": pg.get("error"),
        "mock_mode": False,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "events": events,
        "actions": {
            "regenerate_endpoint": f"POST /api/admin/orders/{order['id']}/production/regenerate",
            "supports_copy_prompt": False,
            "download_url": None,
        },
    }


async def _stage_child_character_i2i(order: dict, pipeline_cfg: dict) -> dict:
    enabled = (pipeline_cfg.get("stages", {}).get("child_character_i2i") or {}).get("enabled", False)
    asset = await db.child_character_assets.find_one({"order_id": order["id"]}, {"_id": 0})
    source_url = ((order.get("data") or {}).get("child") or {}).get("image_url")

    if not enabled:
        status = "skipped"
    elif asset:
        status = asset.get("status", "pending")
    else:
        status = "pending"

    # Resolve current config regardless of asset presence
    model = await _resolve_model_current("child_character_i2i")
    prompt_info = await _resolve_prompt_current("child_character_i2i")
    prompt_used = (asset or {}).get("prompt_used")

    input_summary = {
        "source_image_url": source_url,
        "child_name":       ((order.get("data") or {}).get("child") or {}).get("name"),
        "child_age":        ((order.get("data") or {}).get("child") or {}).get("age"),
    }
    output_summary = {
        "generated_image_url": (asset or {}).get("generated_image_url"),
        "provider":            (asset or {}).get("provider"),
        "model_name":          (asset or {}).get("model_name"),
        "mock":                (asset or {}).get("mock", False),
        "fallback_used":       (asset or {}).get("fallback_used", False),
    }
    events = []
    if asset:
        events.append({
            "at": asset.get("updated_at"),
            "type": "asset",
            "message": f"status={asset.get('status')} provider={asset.get('provider')} mock={asset.get('mock', False)}",
        })
        if asset.get("error_message"):
            events.append({"at": asset.get("updated_at"), "type": "error",
                           "message": asset["error_message"][:500]})

    return {
        "stage_key": "child_character_i2i",
        "name_ar": _display_name("child_character_i2i")["ar"],
        "name_en": _display_name("child_character_i2i")["en"],
        "config_enabled": enabled,
        "status": status,
        "started_at": (asset or {}).get("created_at"),
        "ended_at":   (asset or {}).get("updated_at"),
        "latency_ms_estimate": _latency_ms((asset or {}).get("created_at"),
                                            (asset or {}).get("updated_at")),
        "latency_is_estimate": True,
        "attempts": 1 if asset else 0,
        "provider": (asset or {}).get("provider") or model[0],
        "model_name": (asset or {}).get("model_name") or model[1],
        "model_source": (asset or {}).get("prompt_source") or model[2],
        "prompt_source": (asset or {}).get("prompt_source") or prompt_info["prompt_source"],
        "prompt_template_id": prompt_info["prompt_template_id"],
        "prompt_template_version": prompt_info["prompt_template_version"],
        "prompt_template_name": prompt_info["prompt_template_name"],
        "prompt_used": prompt_used,
        "prompt_hash": _prompt_hash(prompt_used),
        "fallback_used": (asset or {}).get("fallback_used", False),
        "error_message": (asset or {}).get("error_message"),
        "mock_mode": bool((asset or {}).get("mock", False)),
        "input_summary": input_summary,
        "output_summary": output_summary,
        "events": events,
        "actions": {
            "regenerate_endpoint": f"POST /api/admin/orders/{order['id']}/child-character/regenerate",
            "supports_copy_prompt": bool(prompt_used),
            "download_url": (asset or {}).get("generated_image_url"),
        },
    }


async def _stage_extra_character_i2i(order: dict, pipeline_cfg: dict) -> dict:
    """Aggregate status for all visible extra characters with uploaded images."""
    enabled = (pipeline_cfg.get("stages", {}).get("extra_character_i2i") or {}).get("enabled", False)
    chars = ((order.get("data") or {}).get("characters") or [])
    eligible = [
        {"character_index": i, "type": c.get("type"), "name": c.get("name"),
         "role": c.get("role"), "source_image_url": c.get("image_url"),
         "auto_visual_description": c.get("visual_description_auto")}
        for i, c in enumerate(chars)
        if c.get("role") == "visible" and c.get("image_url")
    ]
    assets = await db.extra_character_assets.find(
        {"order_id": order["id"]}, {"_id": 0}
    ).sort("character_index", 1).to_list(20)
    assets_by_idx = {a["character_index"]: a for a in assets}

    if not eligible:
        status = "skipped"
        reason = "no_visible_character_with_image"
    elif not enabled:
        status = "skipped"
        reason = "stage_disabled"
    else:
        if all(assets_by_idx.get(e["character_index"], {}).get("status") == "completed" for e in eligible):
            status = "completed"
        elif any(assets_by_idx.get(e["character_index"], {}).get("status") == "failed" for e in eligible):
            status = "failed"
        elif any(assets_by_idx.get(e["character_index"]) for e in eligible):
            status = "running"
        else:
            status = "pending"
        reason = ""

    # Timing: earliest created / latest updated across children assets.
    started_at = min((a.get("created_at") for a in assets if a.get("created_at")), default=None)
    ended_at   = max((a.get("updated_at") for a in assets if a.get("updated_at")), default=None)
    model = await _resolve_model_current("extra_character_i2i")
    prompt_info = await _resolve_prompt_current("child_character_i2i")  # reuses same template
    any_mock = any(a.get("mock") for a in assets)
    any_fb = any(a.get("fallback_used") for a in assets)

    characters_out = []
    for e in eligible:
        a = assets_by_idx.get(e["character_index"])
        characters_out.append({
            **e,
            "generated_image_url": (a or {}).get("generated_image_url"),
            "provider":            (a or {}).get("provider"),
            "model_name":          (a or {}).get("model_name"),
            "status":              (a or {}).get("status") or "pending",
            "mock":                (a or {}).get("mock", False),
            "fallback_used":       (a or {}).get("fallback_used", False),
            "prompt_hash":         _prompt_hash((a or {}).get("prompt_used")),
            "error_message":       (a or {}).get("error_message"),
        })

    events = []
    for a in assets:
        events.append({
            "at": a.get("updated_at"),
            "type": "asset",
            "message": f"char_idx={a.get('character_index')} name={a.get('character_name')} "
                       f"status={a.get('status')} mock={a.get('mock', False)}",
        })
        if a.get("error_message"):
            events.append({"at": a.get("updated_at"), "type": "error",
                           "message": a["error_message"][:300]})

    return {
        "stage_key": "extra_character_i2i",
        "name_ar": _display_name("extra_character_i2i")["ar"],
        "name_en": _display_name("extra_character_i2i")["en"],
        "config_enabled": enabled,
        "status": status,
        "started_at": started_at,
        "ended_at":   ended_at,
        "latency_ms_estimate": _latency_ms(started_at, ended_at),
        "latency_is_estimate": True,
        "attempts": len(assets),
        "provider": model[0],
        "model_name": model[1],
        "model_source": model[2],
        **prompt_info,
        "prompt_used": None,  # per-character prompts live on each asset
        "prompt_hash": None,
        "fallback_used": any_fb,
        "error_message": next((a.get("error_message") for a in assets if a.get("error_message")), None),
        "mock_mode": any_mock,
        "input_summary": {
            "eligible_count": len(eligible),
            "reason": reason or None,
        },
        "output_summary": {
            "characters": characters_out,
            "any_mock": any_mock,
            "any_fallback": any_fb,
        },
        "events": events,
        "actions": {
            "regenerate_endpoint": None,
            "supports_copy_prompt": False,
            "download_url": None,
        },
    }



async def _stage_scene_image_generation(order: dict, pipeline_cfg: dict,
                                         scene_plans: list[dict]) -> dict:
    enabled = (pipeline_cfg.get("stages", {}).get("scene_image_generation") or {}).get("enabled", True)
    jobs = await db.generation_jobs.find(
        {"order_id": order["id"], "job_type": {"$in": ["cover_image", "scene_image"]}},
        {"_id": 0},
    ).sort("created_at", 1).to_list(200)
    images = await db.scene_images.find({"order_id": order["id"]}, {"_id": 0}).sort("scene_index", 1).to_list(50)

    if not enabled:
        status = "skipped"
    elif jobs:
        if any(j.get("status") == "processing" for j in jobs):
            status = "running"
        elif all(j.get("status") == "completed" for j in jobs):
            status = "completed"
        elif any(j.get("status") == "failed" for j in jobs):
            status = "failed"
        else:
            status = "pending"
    else:
        status = "pending"
    started_at = min((j.get("created_at") for j in jobs if j.get("created_at")), default=None)
    ended_at   = max((j.get("updated_at") for j in jobs if j.get("updated_at")), default=None)
    model = await _resolve_model_current("scene_image_generation")
    prompt_info = await _resolve_prompt_current("scene_image_generation")
    fallback_used = any((img.get("provider") == "fallback") for img in images)

    # Per-scene debug array — real data only.
    scene_details = []
    plans_by_idx = {s.get("scene_index"): s for s in scene_plans}
    for img in images:
        if img.get("kind") != "scene":
            continue
        # Find matching job (latest attempt for that scene_plan_id)
        scene_jobs = [j for j in jobs if j.get("job_type") == "scene_image"
                                         and j.get("target_id") == img.get("scene_plan_id")]
        last_job = sorted(scene_jobs, key=lambda x: x.get("updated_at") or "", reverse=True)
        last_job = last_job[0] if last_job else None
        scene_details.append({
            "scene_index":   img.get("scene_index"),
            "scene_title":   (plans_by_idx.get(img.get("scene_index")) or {}).get("title"),
            "image_url":     img.get("image_url"),
            "prompt_preview": (img.get("prompt_used") or "")[:200],
            "prompt_hash":    _prompt_hash(img.get("prompt_used")),
            "provider":       img.get("provider"),
            "fallback_used":  img.get("provider") == "fallback",
            "latency_ms_estimate": _latency_ms(
                (last_job or {}).get("created_at"), (last_job or {}).get("updated_at")
            ),
            "attempts":      (last_job or {}).get("attempt_count"),
            "status":        (last_job or {}).get("status"),
            "error_message": (last_job or {}).get("error_message"),
        })
    cover_img = next((i for i in images if i.get("kind") == "cover"), None)
    cover_info = None
    if cover_img:
        cover_info = {
            "image_url": cover_img.get("image_url"),
            "prompt_preview": (cover_img.get("prompt_used") or "")[:200],
            "provider": cover_img.get("provider"),
        }

    input_summary = {
        "scene_count_planned": len(scene_plans),
        "audio_background": ((order.get("data") or {}).get("audio_background") or {}).get("mode"),
        "uses_child_reference_asset": (pipeline_cfg.get("stages", {})
                                       .get("scene_image_generation") or {})
                                       .get("uses_child_reference_asset", False),
    }
    output_summary = {
        "cover": cover_info,
        "scene_count_generated": len(scene_details),
        "fallback_count": sum(1 for s in scene_details if s["fallback_used"]),
        "scenes": scene_details,
    }
    events = _history_for_stage(order.get("status_history", []), "scene_image_generation") \
             + _job_events([j for j in jobs if j.get("status") in ("failed", "completed")])[-15:]

    return {
        "stage_key": "scene_image_generation",
        "name_ar": _display_name("scene_image_generation")["ar"],
        "name_en": _display_name("scene_image_generation")["en"],
        "config_enabled": enabled,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "latency_ms_estimate": _latency_ms(started_at, ended_at),
        "latency_is_estimate": True,
        "attempts": sum((j.get("attempt_count") or 0) for j in jobs),
        "provider": model[0],
        "model_name": model[1],
        "model_source": model[2],
        **prompt_info,
        "prompt_used": None,  # per-scene prompts inside scenes[].prompt_preview
        "prompt_hash": None,
        "fallback_used": fallback_used,
        "error_message": next((j.get("error_message") for j in jobs if j.get("status") == "failed"), None),
        "mock_mode": False,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "events": events,
        "actions": {
            "regenerate_endpoint": f"POST /api/admin/orders/{order['id']}/media/regenerate",
            "supports_copy_prompt": False,
            "download_url": None,
        },
    }


async def _stage_narration(order: dict, pipeline_cfg: dict) -> dict:
    enabled = (pipeline_cfg.get("stages", {}).get("narration_generation") or {}).get("enabled", True)
    jobs = await db.generation_jobs.find(
        {"order_id": order["id"], "job_type": "narration_audio"}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    assets = await db.narration_assets.find({"order_id": order["id"]}, {"_id": 0}).sort("scene_index", 1).to_list(50)

    if not enabled:
        status = "skipped"
    elif jobs and all(j.get("status") == "completed" for j in jobs):
        status = "completed"
    elif any(j.get("status") == "failed" for j in jobs):
        status = "failed"
    elif any(j.get("status") == "processing" for j in jobs):
        status = "running"
    else:
        status = "pending" if not assets else "completed"

    started_at = min((j.get("created_at") for j in jobs if j.get("created_at")), default=None)
    ended_at   = max((j.get("updated_at") for j in jobs if j.get("updated_at")), default=None)
    model = await _resolve_model_current("narration_generation")
    any_mock = any((a.get("provider") == "mock") for a in assets)

    output_summary = {
        "count": len(assets),
        "total_duration_seconds": sum((a.get("duration_seconds") or 0) for a in assets),
        "all_mocked": any_mock and all((a.get("provider") == "mock") for a in assets),
        "items": [
            {
                "scene_index":      a.get("scene_index"),
                "voice_type":       a.get("voice_type"),
                "language":         a.get("language"),
                "duration_seconds": a.get("duration_seconds"),
                "provider":         a.get("provider"),
                "audio_url":        a.get("audio_url"),
                "text_preview":     (a.get("text") or "")[:120],
            }
            for a in assets
        ],
    }
    events = _job_events([j for j in jobs if j.get("status") in ("failed", "completed")])[-15:]

    return {
        "stage_key": "narration_generation",
        "name_ar": _display_name("narration_generation")["ar"],
        "name_en": _display_name("narration_generation")["en"],
        "config_enabled": enabled,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "latency_ms_estimate": _latency_ms(started_at, ended_at),
        "latency_is_estimate": True,
        "attempts": sum((j.get("attempt_count") or 0) for j in jobs),
        "provider": model[0],
        "model_name": model[1],
        "model_source": model[2],
        "prompt_source": "n/a",
        "prompt_template_id": None,
        "prompt_template_version": None,
        "prompt_template_name": None,
        "prompt_used": None,
        "prompt_hash": None,
        "fallback_used": False,
        "error_message": next((j.get("error_message") for j in jobs if j.get("status") == "failed"), None),
        "mock_mode": any_mock,
        "input_summary": {
            "voice":   (order.get("enriched") or {}).get("voice_name"),
            "language":(order.get("enriched") or {}).get("language_name"),
        },
        "output_summary": output_summary,
        "events": events,
        "actions": {
            "regenerate_endpoint": f"POST /api/admin/orders/{order['id']}/media/regenerate",
            "supports_copy_prompt": False,
            "download_url": None,
        },
    }


async def _stage_book_assets(order: dict, pipeline_cfg: dict) -> dict:
    # book_assets is not tracked as a distinct stage in pipeline_config; treat as
    # enabled unless explicitly disabled in the future config.
    stage_flags = pipeline_cfg.get("stages", {}).get("book_assets_generation") or {}
    enabled = stage_flags.get("enabled", True)
    jobs = await db.generation_jobs.find(
        {"order_id": order["id"], "job_type": "book_page_asset"}, {"_id": 0}
    ).sort("created_at", 1).to_list(200)
    assets = await db.book_assets.find({"order_id": order["id"]}, {"_id": 0}).sort("page_number", 1).to_list(50)

    if jobs and all(j.get("status") == "completed" for j in jobs):
        status = "completed"
    elif any(j.get("status") == "failed" for j in jobs):
        status = "failed"
    elif any(j.get("status") == "processing" for j in jobs):
        status = "running"
    else:
        status = "pending" if not assets else "completed"

    started_at = min((j.get("created_at") for j in jobs if j.get("created_at")), default=None)
    ended_at   = max((j.get("updated_at") for j in jobs if j.get("updated_at")), default=None)

    output_summary = {
        "page_count": len(assets),
        "reused_from_scenes": sum(1 for a in assets if a.get("provider") == "reused"),
        "items": [
            {
                "page_number":      a.get("page_number"),
                "scene_index":      a.get("scene_index"),
                "illustration_url": a.get("illustration_url"),
                "provider":         a.get("provider"),
                "text_preview":    (a.get("page_text") or "")[:120],
            }
            for a in assets
        ],
    }
    events = _job_events([j for j in jobs if j.get("status") in ("failed", "completed")])[-15:]

    return {
        "stage_key": "book_assets_generation",
        "name_ar": _display_name("book_assets_generation")["ar"],
        "name_en": _display_name("book_assets_generation")["en"],
        "config_enabled": enabled,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "latency_ms_estimate": _latency_ms(started_at, ended_at),
        "latency_is_estimate": True,
        "attempts": sum((j.get("attempt_count") or 0) for j in jobs),
        "provider": "reused (from scene_images)",
        "model_name": "n/a",
        "model_source": "n/a",
        "prompt_source": "n/a",
        "prompt_template_id": None,
        "prompt_template_version": None,
        "prompt_template_name": None,
        "prompt_used": None,
        "prompt_hash": None,
        "fallback_used": False,
        "error_message": next((j.get("error_message") for j in jobs if j.get("status") == "failed"), None),
        "mock_mode": False,
        "input_summary": {"expected_page_count": len(assets)},
        "output_summary": output_summary,
        "events": events,
        "actions": {
            "regenerate_endpoint": f"POST /api/admin/orders/{order['id']}/media/regenerate",
            "supports_copy_prompt": False,
            "download_url": None,
        },
    }


async def _stage_assembly(order: dict, job_type: str, doc_collection: str,
                           url_field: str, stage_key: str) -> dict:
    jobs = await db.generation_jobs.find(
        {"order_id": order["id"], "job_type": job_type}, {"_id": 0}
    ).sort("created_at", 1).to_list(20)
    doc = await getattr(db, doc_collection).find_one({"order_id": order["id"]}, {"_id": 0})

    if doc and (doc.get(url_field)):
        status = "completed"
    elif any(j.get("status") == "failed" for j in jobs):
        status = "failed"
    elif any(j.get("status") == "processing" for j in jobs):
        status = "running"
    elif jobs:
        status = "pending"
    else:
        status = "pending"

    started_at = min((j.get("created_at") for j in jobs if j.get("created_at")), default=None)
    ended_at   = max((j.get("updated_at") for j in jobs if j.get("updated_at")), default=None)
    events = _job_events([j for j in jobs if j.get("status") in ("failed", "completed")])[-15:]
    output_summary = {
        url_field:          (doc or {}).get(url_field),
        "duration_seconds": (doc or {}).get("duration_seconds"),
        "page_count":       (doc or {}).get("page_count"),
        "thumbnail_url":    (doc or {}).get("thumbnail_url"),
        "audio_background_mode": (doc or {}).get("audio_background_mode"),
        "provider":         (doc or {}).get("provider"),
        "assembly_metadata":(doc or {}).get("assembly_metadata"),
    }

    return {
        "stage_key": stage_key,
        "name_ar": _display_name(stage_key)["ar"],
        "name_en": _display_name(stage_key)["en"],
        "config_enabled": True,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "latency_ms_estimate": _latency_ms(started_at, ended_at),
        "latency_is_estimate": True,
        "attempts": sum((j.get("attempt_count") or 0) for j in jobs),
        "provider": (doc or {}).get("provider") or ("ffmpeg" if job_type == "final_video_assembly" else "reportlab"),
        "model_name": "local-assembly" if job_type == "final_video_assembly" else "local-reportlab",
        "model_source": "local",
        "prompt_source": "n/a",
        "prompt_template_id": None,
        "prompt_template_version": None,
        "prompt_template_name": None,
        "prompt_used": None,
        "prompt_hash": None,
        "fallback_used": False,
        "error_message": next((j.get("error_message") for j in jobs if j.get("status") == "failed"), None),
        "mock_mode": False,
        "input_summary": {"jobs_count": len(jobs)},
        "output_summary": output_summary,
        "events": events,
        "actions": {
            "regenerate_endpoint": f"POST /api/admin/orders/{order['id']}/delivery/regenerate",
            "supports_copy_prompt": False,
            "download_url": (doc or {}).get(url_field),
        },
    }


# --- main endpoint ---------------------------------------------------------
def _status_color(status: str) -> str:
    return {
        "completed": "green",
        "running":   "yellow",
        "failed":    "red",
        "skipped":   "gray",
        "pending":   "neutral",
    }.get(status, "neutral")


@router.get("/orders/{order_id}/storyboard")
async def get_storyboard(order_id: str) -> dict[str, Any]:
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")

    pipeline_cfg = await get_pipeline_config()

    # Pre-fetch scene_plans once for reuse in scene_image_generation stage.
    scene_plans = await db.scene_plans.find(
        {"order_id": order_id, "is_archived": False}, {"_id": 0}
    ).sort("scene_index", 1).to_list(50)

    stages = [
        await _stage_scenario_generation(order, pipeline_cfg),
        await _stage_production_planning(order, pipeline_cfg),
        await _stage_child_character_i2i(order, pipeline_cfg),
        await _stage_extra_character_i2i(order, pipeline_cfg),
        await _stage_scene_image_generation(order, pipeline_cfg, scene_plans),
        await _stage_narration(order, pipeline_cfg),
        await _stage_book_assets(order, pipeline_cfg),
        await _stage_assembly(order, "final_video_assembly", "final_videos", "video_url", "video_assembly"),
        await _stage_assembly(order, "final_pdf_assembly",   "final_pdfs",   "pdf_url",   "pdf_assembly"),
    ]

    timeline = [
        {
            "stage_key": s["stage_key"],
            "name_ar": s["name_ar"],
            "status": s["status"],
            "badge_color": _status_color(s["status"]),
            "attempts": s.get("attempts", 0),
            "latency_ms_estimate": s.get("latency_ms_estimate"),
            "fallback_used": s.get("fallback_used", False),
            "mock_mode": s.get("mock_mode", False),
        }
        for s in stages
    ]

    child = (order.get("data") or {}).get("child") or {}
    pers = (order.get("data") or {}).get("personalization") or {}
    return {
        "order": {
            "id":       order["id"],
            "status":   order.get("status"),
            "status_ar": ORDER_STATUS_AR.get(order.get("status"), order.get("status")),
            "child_name": child.get("name"),
            "child_age":  child.get("age"),
            "child_image_url": child.get("image_url"),
            "child_appearance_notes": child.get("appearance_notes"),
            "child_hijab": child.get("hijab"),
            "toy_image_url":          pers.get("toy_image_url"),
            "toy_description_auto":   pers.get("toy_description_auto"),
            "custom_notes":           pers.get("custom_notes"),
            "duration": order.get("duration"),
            "production_approved": bool(order.get("production_approved")),
            "created_at": order.get("created_at"),
            "updated_at": order.get("updated_at"),
        },
        "timeline": timeline,
        "stages": stages,
        "pipeline_config": {
            "stages": pipeline_cfg.get("stages", {}),
            "order":  pipeline_cfg.get("order", []),
        },
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "latency_values_are_estimates": True,
            "data_source": "read-only aggregation (no new collections)",
        },
    }
