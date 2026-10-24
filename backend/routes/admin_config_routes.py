"""Admin-only CRUD for Phase A config:
  * /api/admin/models/*           — model_registry CRUD
  * /api/admin/pipeline-config    — pipeline_config GET/PATCH
  * /api/admin/api-status         — read-only env/secret configuration check

CRITICAL: raw API keys are NEVER returned in any response. Only masked status.
"""
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from db import db
from auth import require_admin
from services.config_service import (
    DEFAULT_MODELS,
    DEFAULT_PIPELINE,
    STAGE_DISPLAY_NAMES,
    PROVIDER_ENV_MAP,
    env_status,
)


router = APIRouter(prefix="/admin", tags=["admin-config"], dependencies=[Depends(require_admin)])


def _now():
    return datetime.now(timezone.utc).isoformat()


# ============================================================================
# MODEL REGISTRY
# ============================================================================
class ModelUpdate(BaseModel):
    provider: str | None = None
    model_name: str | None = None
    fallback_provider: str | None = None
    fallback_model: str | None = None
    env_key: str | None = None
    active: bool | None = None
    notes: str | None = None


@router.get("/models")
async def list_models():
    docs = await db.model_registry.find({}, {"_id": 0}).sort("stage_key", 1).to_list(100)
    # Include any stages that don't yet have a DB row so admin sees them all.
    existing_keys = {d["stage_key"] for d in docs}
    for stage_key, defaults in DEFAULT_MODELS.items():
        if stage_key not in existing_keys:
            docs.append({
                "id": None,
                "stage_key": stage_key,
                "stage_name_ar": STAGE_DISPLAY_NAMES[stage_key]["ar"],
                "stage_name_en": STAGE_DISPLAY_NAMES[stage_key]["en"],
                "provider": defaults["provider"],
                "model_name": defaults["model_name"],
                "fallback_provider": defaults.get("fallback_provider"),
                "fallback_model": defaults.get("fallback_model"),
                "env_key": defaults.get("env_key"),
                "active": True,
                "notes": "",
                "source": "default-unsaved",
                "created_at": None,
                "updated_at": None,
            })
    docs.sort(key=lambda d: d.get("stage_key", ""))
    return docs


@router.patch("/models/{stage_key}")
async def update_model(stage_key: str, payload: ModelUpdate, admin: dict = Depends(require_admin)):
    if stage_key not in DEFAULT_MODELS:
        raise HTTPException(status_code=400, detail="stage_key غير معروفة")
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(status_code=400, detail="لا يوجد تعديل")
    # M4: a stage may only use a model from the catalog (same check as the engine page).
    if patch.get("provider") or patch.get("model_name"):
        from services import model_catalog
        from services.config_service import resolve_model
        cur_provider, cur_model, _src = await resolve_model(stage_key, "", "")
        try:
            await model_catalog.set_stage_model(stage_key, patch.get("provider") or cur_provider,
                                                patch.get("model_name") or cur_model, admin)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    patch["updated_at"] = _now()
    existing = await db.model_registry.find_one({"stage_key": stage_key})
    if not existing:
        # Upsert with defaults + patch.
        base = DEFAULT_MODELS[stage_key]
        doc = {
            "id": str(uuid.uuid4()),
            "stage_key": stage_key,
            "stage_name_ar": STAGE_DISPLAY_NAMES[stage_key]["ar"],
            "stage_name_en": STAGE_DISPLAY_NAMES[stage_key]["en"],
            "provider": base["provider"],
            "model_name": base["model_name"],
            "fallback_provider": base.get("fallback_provider"),
            "fallback_model": base.get("fallback_model"),
            "env_key": base.get("env_key"),
            "active": True,
            "notes": "",
            "created_at": _now(),
            **patch,
        }
        await db.model_registry.insert_one(doc)
    else:
        await db.model_registry.update_one({"stage_key": stage_key}, {"$set": patch})
    return await db.model_registry.find_one({"stage_key": stage_key}, {"_id": 0})


# ============================================================================
# PIPELINE CONFIG
# ============================================================================
class PipelineUpdate(BaseModel):
    order: list[str] | None = None
    stages: dict[str, dict[str, Any]] | None = None


@router.get("/pipeline-config")
async def get_pipeline_config():
    doc = await db.pipeline_config.find_one({"id": "default"}, {"_id": 0})
    if not doc:
        return {**DEFAULT_PIPELINE, "id": "default", "source": "default"}
    return doc


@router.get("/pipeline-readiness")
async def get_pipeline_readiness():
    """Phase I — single source of truth for /admin/pipeline.

    Joins SUPPORTED_STAGES + EXECUTOR_STATUS + pipeline_config + model_registry
    + prompt_templates + pricing + secret_overrides + active preset stack.
    """
    from services.pipeline_readiness_service import build_readiness
    return await build_readiness()


@router.patch("/pipeline-config")
async def patch_pipeline_config(payload: PipelineUpdate):
    patch = {k: v for k, v in payload.model_dump().items() if v is not None}
    if not patch:
        raise HTTPException(status_code=400, detail="لا يوجد تعديل")
    patch["updated_at"] = _now()
    existing = await db.pipeline_config.find_one({"id": "default"})
    if not existing:
        doc = {"id": "default", **DEFAULT_PIPELINE, "created_at": _now(), **patch}
        await db.pipeline_config.insert_one(doc)
    else:
        await db.pipeline_config.update_one({"id": "default"}, {"$set": patch})
    return await db.pipeline_config.find_one({"id": "default"}, {"_id": 0})


# ============================================================================
# API / SECRETS STATUS (read-only; never exposes raw keys)
# ============================================================================
@router.get("/api-status")
async def api_status():
    """Return env-var mapping + configured/not-configured per provider.

    NEVER returns raw values — only masked previews (first4••••last4).
    Keys are sourced directly from `os.environ`, not from the DB.
    """
    out = []
    for provider, meta in PROVIDER_ENV_MAP.items():
        env = env_status(meta["env_key"])
        out.append({
            "provider": provider,
            "label": meta["label"],
            **env,
        })
    return {
        "providers": out,
        "doc": "API keys must be stored in .env files, never in the database. Admin can only view masked status.",
    }
