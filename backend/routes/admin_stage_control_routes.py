"""Admin Stage Control — Phase K.

Single control surface for all 11 canonical pipeline stages. Replaces the
need to bounce between /admin/models, /admin/pipeline, /admin/prompts,
/admin/secrets, and /admin/lab.

Endpoints:
  GET  /api/admin/stage-control/state    — full read-only snapshot
  PATCH /api/admin/stage-control/{stage_key} — upsert provider/model/active
                                              (delegates to model_registry)

Read shape: extends pipeline_readiness with:
  * provider_choices             — admin-friendly dropdown values per stage
  * env_key_choices              — env keys this provider needs (or null)
  * defaults                     — DEFAULT_MODELS row for the stage (for reset)
  * stage_pricing                — per-stage cost from pricing_service
  * narration_real_call_available — bool for the narration banner
  * stages_remaining_to_wire     — list of stage_keys still `not-yet-wired`
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from db import db
from services.config_service import (
    DEFAULT_MODELS, STAGE_DISPLAY_NAMES, PROVIDER_ENV_MAP,
)
from services.pipeline_readiness_service import build_readiness
from services.tts_service import (
    narration_real_call_available, DEFAULT_ELEVENLABS_MODEL,
    DEFAULT_ELEVENLABS_VOICE,
)
from services.audit_service import record_audit


router = APIRouter(
    prefix="/admin/stage-control",
    tags=["admin-stage-control"],
    dependencies=[Depends(require_admin)],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Provider menu shown per stage type. Keep flat — the UI applies the
# right subset based on the stage's executor_status.
_TEXT_PROVIDERS  = ["anthropic", "openai", "internal"]
_IMAGE_PROVIDERS = ["openai", "gemini"]
_TTS_PROVIDERS   = ["elevenlabs", "openai", "mock"]
_VIDEO_PROVIDERS = ["kling", "sora", "ffmpeg"]
_MUSIC_PROVIDERS = ["elevenlabs", "suno", "mock"]
_LOCAL_PROVIDERS = ["ffmpeg", "reportlab"]

PROVIDER_CHOICES_BY_STAGE: dict[str, list[str]] = {
    "scenario_generation":         _TEXT_PROVIDERS,
    "production_planning":         _TEXT_PROVIDERS,
    "child_character_i2i":         _IMAGE_PROVIDERS,
    "extra_character_i2i":         _IMAGE_PROVIDERS,
    "scene_image_generation":      _IMAGE_PROVIDERS,
    "book_page_image_generation":  _IMAGE_PROVIDERS,
    "narration_generation":        _TTS_PROVIDERS,
    "music_generation":            _MUSIC_PROVIDERS,
    "video_generation":            _VIDEO_PROVIDERS,
    "video_assembly":              ["ffmpeg"],
    "pdf_assembly":                ["reportlab"],
}


class StagePatch(BaseModel):
    provider:          str | None = None
    model_name:        str | None = None
    fallback_provider: str | None = None
    fallback_model:    str | None = None
    env_key:           str | None = None
    active:            bool | None = None
    notes:             str | None = None


@router.get("/state")
async def get_state():
    """Full snapshot the unified Stage Control page renders from."""
    readiness = await build_readiness()

    # Augment each stage with provider menu + defaults + remaining-to-wire flag.
    augmented_stages: list[dict[str, Any]] = []
    remaining_to_wire: list[str] = []
    for stage in readiness["stages"]:
        sk = stage["stage_key"]
        defaults = DEFAULT_MODELS.get(sk) or {}
        provider_choices = PROVIDER_CHOICES_BY_STAGE.get(sk, [])
        env_meta = PROVIDER_ENV_MAP.get(stage.get("provider") or "") or {}
        if stage["executor_status"] == "not-yet-wired":
            remaining_to_wire.append(sk)
        augmented_stages.append({
            **stage,
            "provider_choices":   provider_choices,
            "default_provider":   defaults.get("provider"),
            "default_model":      defaults.get("model_name"),
            "default_env_key":    defaults.get("env_key"),
            "env_label":          env_meta.get("label"),
        })

    return {
        **readiness,
        "stages":                            augmented_stages,
        "narration_real_call_available":     await narration_real_call_available(),
        "narration_defaults": {
            "model":  DEFAULT_ELEVENLABS_MODEL,
            "voice":  DEFAULT_ELEVENLABS_VOICE,
            "env_key": "ELEVENLABS_API_KEY",
        },
        "stages_remaining_to_wire":          remaining_to_wire,
        "available_env_keys":                list({m.get("env_key") for m in PROVIDER_ENV_MAP.values() if m.get("env_key")}),
    }


@router.patch("/{stage_key}")
async def patch_stage(stage_key: str, payload: StagePatch, admin=Depends(require_admin)):
    """Upsert a model_registry row for a stage. Mirrors PATCH /admin/models/{stage_key}
    but lives under stage-control for unified UX. Audited."""
    if stage_key not in DEFAULT_MODELS:
        raise HTTPException(status_code=400, detail="stage_key غير معروفة")
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(status_code=400, detail="لا يوجد تعديل")
    # Provider sanity — must belong to the curated menu (or be the default).
    if patch.get("provider"):
        allowed = set(PROVIDER_CHOICES_BY_STAGE.get(stage_key, []))
        allowed.add((DEFAULT_MODELS.get(stage_key) or {}).get("provider"))
        allowed.discard(None)
        if patch["provider"] not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"المزوّد غير مسموح لهذه المرحلة. المسموح: {sorted(a for a in allowed if a)}",
            )
    patch["updated_at"] = _now()
    existing = await db.model_registry.find_one({"stage_key": stage_key})
    base = DEFAULT_MODELS[stage_key]
    if not existing:
        doc = {
            "id":                str(uuid.uuid4()),
            "stage_key":         stage_key,
            "stage_name_ar":     STAGE_DISPLAY_NAMES[stage_key]["ar"],
            "stage_name_en":     STAGE_DISPLAY_NAMES[stage_key]["en"],
            "provider":          base["provider"],
            "model_name":        base["model_name"],
            "fallback_provider": base.get("fallback_provider"),
            "fallback_model":    base.get("fallback_model"),
            "env_key":           base.get("env_key"),
            "active":            True,
            "notes":             "",
            "created_at":        _now(),
            **patch,
        }
        await db.model_registry.insert_one(doc)
    else:
        await db.model_registry.update_one(
            {"stage_key": stage_key}, {"$set": patch},
        )
    after = await db.model_registry.find_one({"stage_key": stage_key}, {"_id": 0})
    try:
        await record_audit(
            entity_type="stage_control",
            entity_id=stage_key,
            action="stage.patch",
            actor_id=admin.get("id"),
            actor_email=admin.get("email"),
            summary=f"stage_control patched {stage_key}: {sorted(patch.keys())}",
            before=existing,
            after=after,
        )
    except Exception:  # noqa: BLE001
        pass
    return after


@router.post("/{stage_key}/reset")
async def reset_stage(stage_key: str, admin=Depends(require_admin)):
    """Reset a stage's model_registry row to DEFAULT_MODELS values."""
    if stage_key not in DEFAULT_MODELS:
        raise HTTPException(status_code=400, detail="stage_key غير معروفة")
    base = DEFAULT_MODELS[stage_key]
    before = await db.model_registry.find_one({"stage_key": stage_key}, {"_id": 0})
    doc = {
        "stage_key":         stage_key,
        "stage_name_ar":     STAGE_DISPLAY_NAMES[stage_key]["ar"],
        "stage_name_en":     STAGE_DISPLAY_NAMES[stage_key]["en"],
        "provider":          base["provider"],
        "model_name":        base["model_name"],
        "fallback_provider": base.get("fallback_provider"),
        "fallback_model":    base.get("fallback_model"),
        "env_key":           base.get("env_key"),
        "active":            True,
        "notes":             "reset to defaults",
        "applied_by_preset_id":   None,
        "applied_by_preset_name": None,
        "updated_at":        _now(),
    }
    await db.model_registry.update_one(
        {"stage_key": stage_key},
        {"$set": doc, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _now()}},
        upsert=True,
    )
    after = await db.model_registry.find_one({"stage_key": stage_key}, {"_id": 0})
    try:
        await record_audit(
            entity_type="stage_control",
            entity_id=stage_key,
            action="stage.reset",
            actor_id=admin.get("id"),
            actor_email=admin.get("email"),
            summary=f"stage_control reset {stage_key} to defaults",
            before=before, after=after,
        )
    except Exception:  # noqa: BLE001
        pass
    return after
