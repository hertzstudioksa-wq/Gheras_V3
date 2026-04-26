"""Admin Stage Testing Lab routes — Wave 2."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from auth import require_admin
from services.stage_lab_service import (
    SUPPORTED_STAGES, REAL_CALL_STAGES,
    run_stage_test, list_stage_test_runs, get_stage_test_run,
)
from services.pricing_service import get_pricing_config

router = APIRouter(
    prefix="/admin/lab",
    tags=["admin-stage-lab"],
    dependencies=[Depends(require_admin)],
)


@router.get("/stages")
async def list_stages():
    """Return the catalogue of stages the lab can drive + their nature.

    The frontend uses this to render the stage picker and show whether
    running a stage will burn budget (real-call) or just preview prompts.
    """
    cfg = await get_pricing_config()
    stages = []
    for s in SUPPORTED_STAGES:
        stages.append({
            "stage_key": s,
            "real_call": s in REAL_CALL_STAGES,
            "estimated_cost": float(cfg.get("per_stage_costs", {}).get(s, 0.0)),
            "currency": cfg.get("currency", "SAR"),
        })
    return {"stages": stages}


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
    # Cost-confirmation gate — admin must explicitly acknowledge real-call cost.
    if stage_key in REAL_CALL_STAGES and not bool(payload.get("acknowledged_cost")):
        raise HTTPException(
            status_code=400,
            detail="هذه المرحلة تستهلك رصيد API. أرسل acknowledged_cost=true للتأكيد.",
        )
    record = await run_stage_test(stage_key, inputs, admin_id=admin.get("id"))
    return record


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
