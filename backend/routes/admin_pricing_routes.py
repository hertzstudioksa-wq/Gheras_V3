"""Admin pricing routes — Wave 2.

Read & update the pricing config; view per-order breakdowns; trigger snapshots.
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from db import db
from auth import require_admin
from services.pricing_service import (
    get_pricing_config,
    update_pricing_config,
    estimate_cost,
    actual_cost,
    snapshot_estimate,
    snapshot_actual,
    get_order_pricing,
)

router = APIRouter(
    prefix="/admin/pricing",
    tags=["admin-pricing"],
    dependencies=[Depends(require_admin)],
)


@router.get("/config")
async def get_config():
    cfg = await get_pricing_config()
    # Strip mongo bookkeeping if present.
    cfg.pop("_id", None)
    return cfg


@router.put("/config")
async def put_config(payload: dict[str, Any], admin=Depends(require_admin)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    cfg = await update_pricing_config(payload, admin_id=admin.get("id"))
    cfg.pop("_id", None)
    return cfg


# Order-level pricing helpers — separate router so it sits under /admin/orders/{id}.
order_router = APIRouter(
    prefix="/admin",
    tags=["admin-pricing-orders"],
    dependencies=[Depends(require_admin)],
)


@order_router.get("/orders/{order_id}/pricing")
async def get_order_pricing_view(order_id: str):
    """Return persisted snapshots + fresh estimate/actual for comparison."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    snaps = await get_order_pricing(order_id)
    fresh_estimate = await estimate_cost(order)
    fresh_actual = await actual_cost(order)
    return {
        "order_id": order_id,
        "snapshots": snaps,
        "fresh": {
            "estimate": fresh_estimate,
            "actual":   fresh_actual,
        },
    }


@order_router.post("/orders/{order_id}/pricing/snapshot")
async def trigger_pricing_snapshot(order_id: str, kind: str = "actual"):
    """Manually persist an estimate or actual snapshot for an order.

    Useful for backfilling pricing on legacy orders or after admin changes
    the pricing config and wants the new numbers stored.
    """
    if kind not in ("estimate", "actual"):
        raise HTTPException(status_code=400, detail="kind must be 'estimate' or 'actual'")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if kind == "estimate":
        doc = await snapshot_estimate(order)
    else:
        doc = await snapshot_actual(order)
    if not doc:
        raise HTTPException(status_code=500, detail="snapshot failed (see backend logs)")
    return {"ok": True, "snapshot": doc}
