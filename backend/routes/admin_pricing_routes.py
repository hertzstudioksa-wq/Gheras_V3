"""Admin pricing routes (M6).

The price table (length × deliverable × video tier → cost, price, margin) with
editable margin/buffer/fees/minimum/FX/VAT and manual prices per cell, what each
order actually cost against its quote, and the margins report.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db import db
from auth import require_admin
from services import story_pricing
from services.order_costs import actual_cost

router = APIRouter(
    prefix="/admin/pricing",
    tags=["admin-pricing"],
    dependencies=[Depends(require_admin)],
)


class OverrideIn(BaseModel):
    seconds: int
    output_type: str
    video_tier: str | None = None
    price_sar: int | None = None  # None → back to the computed price


@router.get("/story")
async def get_story_pricing():
    prices = await story_pricing.current_prices()
    settings = await story_pricing.get_settings()
    return {
        "settings": settings,
        "defaults": story_pricing.DEFAULT_SETTINGS,
        "limits": story_pricing.SETTING_LIMITS,
        "labels": story_pricing.SETTING_LABELS,
        "table": story_pricing.price_table(prices, settings),
        "unit_prices": prices,
        "assumptions": {
            "cast_sheets": story_pricing.CAST_SHEETS,
            "clip_seconds_factor": story_pricing.CLIP_SECONDS_FACTOR,
            "text_tokens": story_pricing.TEXT_TOKENS,
        },
    }


@router.put("/story/settings")
async def put_story_settings(payload: dict, admin=Depends(require_admin)):
    try:
        await story_pricing.update_settings(payload, admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await get_story_pricing()


@router.put("/story/override")
async def put_story_override(payload: OverrideIn, admin=Depends(require_admin)):
    try:
        await story_pricing.set_override(payload.seconds, payload.output_type, payload.video_tier,
                                         payload.price_sar, admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await get_story_pricing()


@router.get("/margins")
async def margins_report(limit: int = 30):
    """Delivered orders: what the parent paid (or was quoted) against what the
    order actually cost. Uses the cost stored at delivery when present."""
    limit = max(1, min(int(limit), 200))
    rows = []
    cursor = db.orders.find(
        {"status": {"$in": ["delivered", "completed"]}},
        {"_id": 0},
    ).sort("created_at", -1).limit(limit)
    async for o in cursor:
        stored = o.get("cost_actual")
        cost = stored if stored else await actual_cost(o)
        quote = o.get("price_quote") or {}
        payment = o.get("payment") or {}
        price = payment["amount_sar"] if payment.get("status") == "paid" else quote.get("price_sar")
        cost_sar = cost.get("total_sar")
        rows.append({
            "order_id": o["id"],
            "child_name": ((o.get("data") or {}).get("child") or {}).get("name"),
            "created_at": o.get("created_at"),
            "seconds": (o.get("duration") or {}).get("seconds"),
            "output_type": quote.get("output_type") or ((o.get("data") or {}).get("delivery") or {}).get("output_type"),
            "video_tier": quote.get("video_tier"),
            "price_sar": price,
            "paid": payment.get("status") == "paid",
            "method": payment.get("method"),
            "estimate_sar": (round(quote["cost_usd"] * (await story_pricing.get_settings())["usd_to_sar"], 2)
                             if quote.get("cost_usd") else None),
            "cost_sar": cost_sar,
            "margin_pct": cost.get("margin_pct"),
        })
    priced = [r for r in rows if r["price_sar"] and r["cost_sar"] is not None]
    revenue = sum(r["price_sar"] for r in priced)
    cost_total = sum(r["cost_sar"] for r in priced)
    return {
        "rows": rows,
        "summary": {
            "orders": len(rows),
            "priced_orders": len(priced),
            "revenue_sar": round(revenue, 2),
            "cost_sar": round(cost_total, 2),
            "margin_pct": round((1 - cost_total / revenue) * 100, 1) if revenue else None,
        },
    }


# Order-level pricing — separate router so it sits under /admin/orders/{id}.
order_router = APIRouter(
    prefix="/admin",
    tags=["admin-pricing-orders"],
    dependencies=[Depends(require_admin)],
)


@order_router.get("/orders/{order_id}/pricing")
async def get_order_pricing_view(order_id: str):
    """The quote the parent saw, the payment, and the actual cost so far."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    return {
        "order_id": order_id,
        "quote": order.get("price_quote"),
        "payment": order.get("payment"),
        "actual": await actual_cost(order),
    }
