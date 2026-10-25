"""Resume orders a restart interrupted (audit PL-4).

Generation runs as in-process background tasks, so a restart (a deploy, a
crash) drops whatever was running and the order would sit at "generating"
forever. At boot, each order caught mid-run is resumed once, from the step it
was on: the shot engine skips keyframes and clips that already exist and polls
Kling requests it already paid for, so resuming doesn't pay twice. An order
interrupted more than `RESUME_WITHIN_HOURS` ago, or already resumed once, is
marked failed instead and shows up in the admin's attention list.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from db import db

logger = logging.getLogger("recovery")

STEP_OF_STATUS = {
    "scenarios_generating": "scenarios",
    "ready_for_ai": "planning",
    "production_planning": "planning",
    "production_approved": "assets",
    "assets_generating": "assets",
    "assets_ready": "assembly",
    "assembling": "assembly",
}
FAILED_STATUS = {"scenarios": "failed", "planning": "failed", "assets": "media_failed", "assembly": "media_failed"}
RESUME_WITHIN_HOURS = 6
MAX_RESUMES = 1
BOOT_DELAY_SECONDS = 15


class _Background:
    """Stand-in for FastAPI BackgroundTasks outside a request."""
    def add_task(self, fn, *args, **kwargs):
        asyncio.create_task(fn(*args, **kwargs))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _note(order: dict, to_status: str, reason: str, inc: dict | None = None) -> None:
    entry = {"from": order["status"], "to": to_status, "at": _now(), "by": "system", "actor_id": None, "reason": reason}
    update = {"$set": {"status": to_status, "updated_at": _now()}, "$push": {"status_history": entry}}
    if inc:
        update["$inc"] = inc
    res = await db.orders.update_one({"id": order["id"], "status": order["status"]}, update)
    if res.modified_count:
        from services.notify_service import on_status
        on_status(order["id"], to_status)


async def _resume(order: dict, step: str) -> None:
    oid = order["id"]
    if step == "scenarios":
        from routes.order_routes import run_scenario_generation
        asyncio.create_task(run_scenario_generation(oid, order.get("current_scenario_batch_id") or str(uuid.uuid4())))
    elif step == "planning":
        from routes.production_routes import run_production_generation
        run_id = str(uuid.uuid4())
        await db.orders.update_one({"id": oid}, {"$set": {"production_generation": {
            "run_id": run_id, "source": "pending", "error": None, "started_at": _now()}}})
        asyncio.create_task(run_production_generation(oid, run_id))
    elif step == "assets":
        from routes.media_routes import trigger_asset_generation
        await trigger_asset_generation(oid, _Background())
    elif step == "assembly":
        from services.final_delivery_service import run_final_assembly
        asyncio.create_task(run_final_assembly(oid, str(uuid.uuid4())))


async def recover_interrupted(booted_at: str | None = None) -> dict:
    """Resume orders caught mid-run by the restart. Only orders last touched
    before this boot count: one a parent started in the seconds after boot is
    running fine, and "resuming" it started a second paid run (found in the
    free rehearsal)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=RESUME_WITHIN_HOURS)).isoformat()
    resumed, failed = [], []
    from services.order_heartbeat import stale_before

    query: dict = {"status": {"$in": list(STEP_OF_STATUS)},
                   # Another live process is still working on an order with a recent heartbeat.
                   "$or": [{"heartbeat_at": None}, {"heartbeat_at": {"$lt": stale_before()}}]}
    if booted_at:
        query["updated_at"] = {"$lt": booted_at}
    async for o in db.orders.find(query,
                                  {"_id": 0, "id": 1, "status": 1, "updated_at": 1, "recovery_count": 1,
                                   "current_scenario_batch_id": 1}):
        step = STEP_OF_STATUS[o["status"]]
        if int(o.get("recovery_count") or 0) >= MAX_RESUMES or (o.get("updated_at") or "") < cutoff:
            await _note(o, FAILED_STATUS[step], "توقّف بسبب إعادة تشغيل السيرفر — أعد المحاولة من صفحة الطلب")
            failed.append(o["id"])
            continue
        entry = {"from": o["status"], "to": o["status"], "at": _now(), "by": "system", "actor_id": None,
                 "reason": "resumed after a server restart"}
        await db.orders.update_one({"id": o["id"]}, {"$inc": {"recovery_count": 1}, "$push": {"status_history": entry}})
        try:
            await _resume(o, step)
            resumed.append(o["id"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[recovery] resume {o['id'][:8]} failed: {type(e).__name__}: {e}")
            await _note(o, FAILED_STATUS[step], f"تعذّر الاستكمال بعد إعادة التشغيل: {type(e).__name__}")
            failed.append(o["id"])
    if resumed or failed:
        logger.info(f"[recovery] resumed {len(resumed)} orders, marked {len(failed)} as interrupted")
    return {"resumed": resumed, "failed": failed}


async def recover_after_boot() -> None:
    booted_at = _now()
    await asyncio.sleep(BOOT_DELAY_SECONDS)  # let startup (seeding, migrations) finish first
    try:
        await recover_interrupted(booted_at)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[recovery] skipped: {type(e).__name__}: {e}")
