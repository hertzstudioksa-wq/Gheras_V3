"""Admin Stage Testing Lab routes — Wave 2."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from auth import require_admin
from services.stage_lab_service import (
    SUPPORTED_STAGES, REAL_CALL_STAGES, EXECUTOR_STATUS, STAGE_NOTES_AR,
    run_stage_test, list_stage_test_runs, get_stage_test_run,
    build_effective_prompt_preview,
)
from services.pricing_service import get_pricing_config
from services.config_service import STAGE_DISPLAY_NAMES
from db import db

router = APIRouter(
    prefix="/admin/lab",
    tags=["admin-stage-lab"],
    dependencies=[Depends(require_admin)],
)


@router.get("/stages")
async def list_stages():
    """Return the catalogue of stages the lab can drive + their nature.

    The frontend uses this to render the stage picker, the executor-status
    badge, the cost preview, and the "why is this preview-only" tooltip.
    """
    cfg = await get_pricing_config()
    # Snapshot which stages have an active prompt template (prompt_driven).
    rows = await db.prompt_templates.find(
        {"active": True}, {"_id": 0, "stage_key": 1}
    ).to_list(50)
    has_template = {r.get("stage_key") for r in rows}

    # Phase H — surface the active preset stack so the UI can show
    # "config came from preset X" alongside each stage.
    active_preset = await db.preset_stacks.find_one(
        {"is_active": True, "is_archived": {"$ne": True}}, {"_id": 0},
    )
    # Per-stage applied_by_preset map.
    mr_rows = await db.model_registry.find(
        {}, {"_id": 0, "stage_key": 1, "applied_by_preset_id": 1, "applied_by_preset_name": 1},
    ).to_list(50)
    applied_by = {r["stage_key"]: r for r in mr_rows}

    stages = []
    for s in SUPPORTED_STAGES:
        executor_status = EXECUTOR_STATUS.get(s, "preview-only")
        # `real_call` kept for back-compat with the existing UI checkbox.
        real_call = (executor_status == "real-call")
        applied = applied_by.get(s) or {}
        stages.append({
            "stage_key": s,
            "name_ar": (STAGE_DISPLAY_NAMES.get(s) or {}).get("ar") or s,
            "name_en": (STAGE_DISPLAY_NAMES.get(s) or {}).get("en") or s,
            "real_call": real_call,
            "executor_status": executor_status,
            "prompt_driven": s in has_template,
            "estimated_cost": float(cfg.get("per_stage_costs", {}).get(s, 0.0)),
            "currency": cfg.get("currency", "SAR"),
            "notes_ar": STAGE_NOTES_AR.get(s, ""),
            # Phase H — provenance
            "applied_by_preset_id":   applied.get("applied_by_preset_id"),
            "applied_by_preset_name": applied.get("applied_by_preset_name"),
            "config_source": (
                "preset" if applied.get("applied_by_preset_id") else
                ("manual_or_default")
            ),
        })
    return {
        "stages": stages,
        "active_preset": (
            {"id": active_preset.get("id"), "name": active_preset.get("name"),
             "slug": active_preset.get("slug"), "applied_at": active_preset.get("applied_at")}
            if active_preset else None
        ),
    }


@router.post("/run")
async def run(payload: dict[str, Any], admin=Depends(require_admin)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    stage_key = payload.get("stage_key")
    if stage_key not in SUPPORTED_STAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported stage_key: {stage_key}")
    inputs = payload.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise HTTPException(status_code=400, detail="inputs must be a dict")
    preview_only = bool(payload.get("preview_only"))
    # Cost-confirmation gate — admin must explicitly acknowledge real-call cost,
    # but ONLY when this is NOT a preview-only run.
    if not preview_only and stage_key in REAL_CALL_STAGES and not bool(payload.get("acknowledged_cost")):
        raise HTTPException(
            status_code=400,
            detail="هذه المرحلة تستهلك رصيد API. أرسل acknowledged_cost=true للتأكيد، أو preview_only=true للمعاينة فقط.",
        )
    record = await run_stage_test(stage_key, inputs, admin_id=admin.get("id"),
                                   preview_only=preview_only)
    return record


@router.post("/preview")
async def preview(payload: dict[str, Any], admin=Depends(require_admin)):
    """Phase F — dedicated Effective Prompt Preview endpoint.

    Equivalent to POST /run with preview_only=true, but never persists a
    stage_test_runs record (this is for fast iteration). Returns the preview
    payload directly.
    """
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    stage_key = payload.get("stage_key")
    if stage_key not in SUPPORTED_STAGES:
        raise HTTPException(status_code=400, detail=f"Unsupported stage_key: {stage_key}")
    inputs = payload.get("inputs") or {}
    if not isinstance(inputs, dict):
        raise HTTPException(status_code=400, detail="inputs must be a dict")
    return await build_effective_prompt_preview(stage_key, inputs)


@router.get("/runs")
async def list_runs(stage_key: str | None = None, limit: int = 30):
    rows = await list_stage_test_runs(stage_key=stage_key, limit=limit)
    return {"runs": rows, "count": len(rows)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    doc = await get_stage_test_run(run_id)
    if not doc:
        raise HTTPException(status_code=404, detail="run not found")
    return doc
