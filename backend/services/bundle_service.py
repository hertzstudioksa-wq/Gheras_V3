"""Bundle service — Wave 3.

Bundles are admin-defined SKUs (e.g. "5 video stories — 199 SAR").

Lifecycle (per `bundle_purchase`):
  reserved   — credit reserved at start_production for an order
  consumed   — order delivered → reservation finalized
  refunded   — order failed → reservation rolled back
  expired    — purchase passed expires_at
  active     — has remaining credits & not expired

Credit accounting (per purchase):
  quantity_total       (admin / payment-provided)
  quantity_consumed    (delivered orders that drew from this purchase)
  quantity_reserved    (in-flight orders that may either consume or refund)
  quantity_remaining   = quantity_total - consumed - reserved

Account rule: a credit is usable for ANY child under the same user account.

Idempotency:
  * reserve(order_id)   — no-op if order already has bundle_reservation pointing at this purchase
  * consume(order_id)   — no-op if reservation is already consumed
  * refund(order_id)    — no-op if reservation is already refunded/missing

These calls NEVER raise. Caller branches on the returned dict:
  {"ok": True/False, "reason": "...", "bundle_purchase_id": "...", ...}
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timedelta, timezone

from db import db
from services.audit_service import record_audit

logger = logging.getLogger("bundle_service")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Bundle CRUD
# ---------------------------------------------------------------------------
ALLOWED_OUTPUT_TYPES = ("video", "pdf", "both")


async def create_bundle(payload: dict, admin_id: str | None, admin_email: str | None) -> dict:
    out = (payload.get("output_type") or "both").lower()
    if out not in ALLOWED_OUTPUT_TYPES:
        out = "both"
    bundle = {
        "id": str(uuid.uuid4()),
        "name":           (payload.get("name") or "Bundle").strip()[:120],
        "description":    (payload.get("description") or "").strip()[:500],
        "output_type":    out,
        "quantity":       max(1, int(payload.get("quantity") or 1)),
        "validity_days":  max(1, int(payload.get("validity_days") or 90)),
        "price":          float(payload.get("price") or 0),
        "currency":       (payload.get("currency") or "SAR")[:8],
        "is_active":      bool(payload.get("is_active", True)),
        "notes":          (payload.get("notes") or "").strip()[:500],
        "is_seeded":      bool(payload.get("is_seeded", False)),
        "created_at":     _now_iso(),
        "updated_at":     _now_iso(),
    }
    await db.bundles.insert_one(bundle)
    bundle.pop("_id", None)
    await record_audit(
        entity_type="bundle", entity_id=bundle["id"], action="create",
        actor_id=admin_id, actor_email=admin_email,
        summary=f"create bundle {bundle['name']} ({bundle['quantity']}x {bundle['output_type']})",
        after=bundle,
    )
    return bundle


async def update_bundle(bundle_id: str, patch: dict, admin_id: str | None, admin_email: str | None) -> dict | None:
    before = await db.bundles.find_one({"id": bundle_id}, {"_id": 0})
    if not before:
        return None
    allowed = {"name", "description", "output_type", "quantity", "validity_days",
               "price", "currency", "is_active", "notes"}
    upd: dict = {k: v for k, v in patch.items() if k in allowed}
    if "output_type" in upd and upd["output_type"] not in ALLOWED_OUTPUT_TYPES:
        upd.pop("output_type")
    upd["updated_at"] = _now_iso()
    await db.bundles.update_one({"id": bundle_id}, {"$set": upd})
    after = await db.bundles.find_one({"id": bundle_id}, {"_id": 0})
    await record_audit(
        entity_type="bundle", entity_id=bundle_id, action="update",
        actor_id=admin_id, actor_email=admin_email,
        summary=f"update bundle {before.get('name')}",
        before=before, after=after,
    )
    return after


async def delete_bundle(bundle_id: str, admin_id: str | None, admin_email: str | None) -> bool:
    before = await db.bundles.find_one({"id": bundle_id}, {"_id": 0})
    if not before:
        return False
    # Soft-disable instead of true delete so existing purchases stay valid.
    await db.bundles.update_one({"id": bundle_id}, {"$set": {"is_active": False, "updated_at": _now_iso()}})
    await record_audit(
        entity_type="bundle", entity_id=bundle_id, action="delete",
        actor_id=admin_id, actor_email=admin_email,
        summary=f"deactivate bundle {before.get('name')}",
        before=before,
    )
    return True


async def list_bundles(active_only: bool = False) -> list[dict]:
    q = {"is_active": True} if active_only else {}
    rows = await db.bundles.find(q, {"_id": 0}).sort("created_at", -1).to_list(200)
    return rows


# ---------------------------------------------------------------------------
# Bundle Purchase / Grant
# ---------------------------------------------------------------------------
async def grant_purchase_to_user(
    *,
    user_id: str,
    bundle_id: str,
    granted_by: str | None,
    granted_by_email: str | None,
    payment_id: str | None = None,
    price_paid: float | None = None,
    reason: str = "manual grant",
) -> dict | None:
    bundle = await db.bundles.find_one({"id": bundle_id, "is_active": True}, {"_id": 0})
    if not bundle:
        return None
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "email": 1, "name": 1})
    if not user:
        return None
    expires = _now() + timedelta(days=int(bundle.get("validity_days") or 90))
    purchase = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "bundle_id": bundle_id,
        "bundle_snapshot": bundle,
        "quantity_total":     int(bundle["quantity"]),
        "quantity_consumed":  0,
        "quantity_reserved":  0,
        "purchased_at":  _now_iso(),
        "expires_at":    expires.isoformat(),
        "price_paid":    float(price_paid) if price_paid is not None else float(bundle.get("price", 0)),
        "currency":      bundle.get("currency", "SAR"),
        "payment_id":    payment_id,
        "granted_by":    granted_by,
        "grant_reason":  reason[:200],
        "reservations":  [],   # [{"order_id": ..., "status": "reserved|consumed|refunded", "at": "..."}]
        "is_active":     True,
    }
    await db.bundle_purchases.insert_one(purchase)
    purchase.pop("_id", None)
    await record_audit(
        entity_type="bundle_purchase", entity_id=purchase["id"], action="grant",
        actor_id=granted_by, actor_email=granted_by_email,
        summary=f"grant '{bundle['name']}' to {user.get('email')}",
        after={"user_email": user.get("email"), "bundle_name": bundle.get("name"),
               "quantity": bundle["quantity"], "expires_at": purchase["expires_at"]},
        metadata={"bundle_id": bundle_id, "user_id": user_id},
    )
    return purchase


async def list_user_purchases(user_id: str, only_active: bool = False) -> list[dict]:
    q: dict = {"user_id": user_id}
    if only_active:
        q["is_active"] = True
    rows = await db.bundle_purchases.find(q, {"_id": 0}).sort("purchased_at", -1).to_list(200)
    # Recompute remaining + status for display.
    out = []
    for p in rows:
        remaining = int(p["quantity_total"]) - int(p.get("quantity_consumed", 0)) - int(p.get("quantity_reserved", 0))
        expired = (p.get("expires_at") or "") < _now_iso()
        if expired:
            status = "expired"
        elif remaining <= 0:
            status = "exhausted"
        elif int(p.get("quantity_reserved", 0)) > 0:
            status = "active"
        else:
            status = "active"
        out.append({**p, "quantity_remaining": max(0, remaining), "status": status})
    return out


async def find_usable_purchase(user_id: str, output_type: str) -> dict | None:
    """Pick the OLDEST active purchase that matches the requested output_type
    (or `both`-typed bundles, which cover anything). Returns None if none.
    """
    rows = await list_user_purchases(user_id, only_active=True)
    candidates = [
        p for p in rows
        if p["status"] == "active"
        and p["quantity_remaining"] > 0
        and p["bundle_snapshot"].get("output_type") in (output_type, "both")
    ]
    candidates.sort(key=lambda p: p.get("expires_at") or "")
    return candidates[0] if candidates else None


# ---------------------------------------------------------------------------
# Reserve / Consume / Refund (idempotent)
# ---------------------------------------------------------------------------
async def reserve_for_order(*, user_id: str, order_id: str, output_type: str,
                            actor_id: str | None = None) -> dict:
    """Reserve 1 credit when an order starts production.

    Returns {"ok": True, "bundle_purchase_id": ...} or {"ok": False, "reason": ...}.
    """
    # Idempotency: did this order already reserve a credit?
    existing = await db.bundle_purchases.find_one(
        {"user_id": user_id, "reservations.order_id": order_id, "reservations.status": "reserved"},
        {"_id": 0, "id": 1},
    )
    if existing:
        return {"ok": True, "bundle_purchase_id": existing["id"], "reason": "already-reserved"}

    purchase_view = await find_usable_purchase(user_id, output_type)
    if not purchase_view:
        return {"ok": False, "reason": "no-usable-bundle"}

    pid = purchase_view["id"]
    res = await db.bundle_purchases.update_one(
        {"id": pid, "$expr": {
            "$lt": [
                {"$add": ["$quantity_consumed", "$quantity_reserved"]},
                "$quantity_total",
            ]
        }},
        {
            "$inc": {"quantity_reserved": 1},
            "$push": {"reservations": {"order_id": order_id, "status": "reserved", "at": _now_iso()}},
        },
    )
    if res.modified_count == 0:
        return {"ok": False, "reason": "race-no-credit-left"}

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"bundle_reservation": {
            "bundle_purchase_id": pid,
            "bundle_id": purchase_view.get("bundle_id"),
            "status": "reserved",
            "at": _now_iso(),
        }}},
    )
    await record_audit(
        entity_type="bundle_purchase", entity_id=pid, action="reserve",
        actor_id=actor_id, actor_email=None,
        summary=f"reserve 1 credit for order {order_id[:8]}",
        metadata={"order_id": order_id, "user_id": user_id},
    )
    return {"ok": True, "bundle_purchase_id": pid}


async def _change_reservation(*, order_id: str, from_status: str, to_status: str,
                              inc_consumed: int = 0, dec_reserved: int = 0,
                              audit_action: str, audit_summary: str) -> dict:
    """Internal: idempotent state transition for a reservation belonging to order_id."""
    # Find the purchase that owns this reservation.
    purchase = await db.bundle_purchases.find_one(
        {"reservations": {"$elemMatch": {"order_id": order_id, "status": from_status}}},
        {"_id": 0, "id": 1},
    )
    if not purchase:
        # Already-transitioned or never-reserved → idempotent no-op.
        return {"ok": True, "reason": "already-or-never"}
    pid = purchase["id"]
    res = await db.bundle_purchases.update_one(
        {"id": pid, "reservations.order_id": order_id, "reservations.status": from_status},
        {
            "$inc": {"quantity_reserved": -dec_reserved, "quantity_consumed": inc_consumed},
            "$set": {
                "reservations.$.status": to_status,
                "reservations.$.transition_at": _now_iso(),
            },
        },
    )
    if res.modified_count == 0:
        return {"ok": True, "reason": "race-already-transitioned"}
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"bundle_reservation.status": to_status, "bundle_reservation.transition_at": _now_iso()}},
    )
    await record_audit(
        entity_type="bundle_purchase", entity_id=pid, action=audit_action,
        actor_id=None, actor_email=None, summary=audit_summary,
        metadata={"order_id": order_id},
    )
    return {"ok": True, "bundle_purchase_id": pid}


async def consume_for_order(order_id: str) -> dict:
    """Reservation → consumed. Called from final_delivery_service when DELIVERED."""
    return await _change_reservation(
        order_id=order_id, from_status="reserved", to_status="consumed",
        inc_consumed=1, dec_reserved=1,
        audit_action="consume",
        audit_summary=f"consume 1 credit for delivered order {order_id[:8]}",
    )


async def refund_for_order(order_id: str) -> dict:
    """Reservation → refunded. Called when an order moves to FAILED/MEDIA_FAILED."""
    return await _change_reservation(
        order_id=order_id, from_status="reserved", to_status="refunded",
        inc_consumed=0, dec_reserved=1,
        audit_action="refund",
        audit_summary=f"refund 1 credit for failed order {order_id[:8]}",
    )


# ---------------------------------------------------------------------------
# Seed defaults (Wave 3 — 3 starter bundles)
# ---------------------------------------------------------------------------
SEEDED_BUNDLES = [
    {
        "name": "5 فيديوهات",
        "description": "5 قصص فيديو مخصّصة للأطفال خلال 90 يوماً.",
        "output_type": "video", "quantity": 5, "validity_days": 90,
        "price": 199.0, "currency": "SAR", "is_active": True, "is_seeded": True,
    },
    {
        "name": "10 كتب PDF",
        "description": "10 كتب قصصية PDF عربية مصوّرة خلال 120 يوماً.",
        "output_type": "pdf", "quantity": 10, "validity_days": 120,
        "price": 249.0, "currency": "SAR", "is_active": True, "is_seeded": True,
    },
    {
        "name": "حزمة كاملة 5 + 5",
        "description": "5 قصص فيديو + 5 كتب PDF خلال 180 يوماً (يمكن مزجها).",
        "output_type": "both", "quantity": 10, "validity_days": 180,
        "price": 449.0, "currency": "SAR", "is_active": True, "is_seeded": True,
    },
]


async def seed_default_bundles() -> int:
    """Insert default bundles only if none exist yet. Returns number created."""
    if await db.bundles.count_documents({}) > 0:
        return 0
    created = 0
    for b in SEEDED_BUNDLES:
        bundle = {**b,
                  "id": str(uuid.uuid4()),
                  "notes": "",
                  "created_at": _now_iso(),
                  "updated_at": _now_iso()}
        await db.bundles.insert_one(bundle)
        created += 1
    logger.info(f"[bundles] seeded {created} default bundles")
    return created
