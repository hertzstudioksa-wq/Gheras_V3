"""Order status transitions the parent can trigger (audit PJ-7 / CS-10).

Every step that starts paid work moves the order with one conditional update:
the status changes only if it is still one of the allowed "from" statuses, so a
double tap, a Back navigation or two tabs can never start the same run twice,
and nothing restarts an order once production is under way.
"""
from __future__ import annotations

from datetime import datetime, timezone

from db import db

# Picking a scenario starts planning (or payment); only before that.
SCENARIO_SELECTABLE = ("scenarios_ready", "scenario_selected", "awaiting_payment")
# New scenario ideas: same window, plus a failed scenario run.
SCENARIO_REGENERABLE = SCENARIO_SELECTABLE + ("failed",)
# Payment done (or not required): planning starts from here.
PLANNING_STARTABLE = ("scenario_selected", "awaiting_payment")
# A new plan: when the plan is ready (not yet approved) or planning failed.
PLAN_REGENERABLE = ("production_ready", "failed")
MAX_USER_DELIVERY_RETRIES = 2


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def claim(order_id: str, allowed_from, to_status: str, by: str, *, actor_id: str | None = None,
                reason: str | None = None, extra: dict | None = None, inc: dict | None = None,
                where: dict | None = None) -> bool:
    """Move the order to `to_status` if its status is in `allowed_from`.
    Returns False (and changes nothing) when another request got there first."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "status": 1})
    if not order or order.get("status") not in allowed_from:
        return False
    entry = {"from": order["status"], "to": to_status, "at": _now(), "by": by, "actor_id": actor_id, "reason": reason}
    update: dict = {"$set": {"status": to_status, "updated_at": _now(), **(extra or {})},
                    "$push": {"status_history": entry}}
    if inc:
        update["$inc"] = inc
    res = await db.orders.update_one({"id": order_id, "status": order["status"], **(where or {})}, update)
    if res.modified_count == 1:
        from services.notify_service import on_status
        on_status(order_id, to_status)
    return res.modified_count == 1
