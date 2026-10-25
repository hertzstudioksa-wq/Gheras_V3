"""Can the AI engine take work right now?

fal answers HTTP 403 "User is locked. Exhausted balance" once the prepaid
balance runs out, and every later call fails the same way (it happened in the
first full test order). The first such answer marks the engine locked:

  * new orders and payments are turned away before the parent pays,
  * an order that fails while locked is tagged `engine_paused`: the parent is
    told we'll finish it, and the admin resumes every paused order in one click
    after topping up (from the step it stopped at, reusing what was drawn),
  * the admin gets one email and a banner.

The first fal call that succeeds clears it.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from db import db

logger = logging.getLogger("engine_health")

DOC_ID = "fal"
LOCK_MARKERS = ("exhausted balance", "user is locked", "insufficient balance", "insufficient credit",
                "out of credit")
CACHE_SECONDS = 15
PAUSABLE = ("failed", "media_failed")
BUSY_AR = ("التوليد متوقف دقايق عندنا لصيانة سريعة. جرّب تاني بعد شوية — "
           "مفيش أي مبلغ اتخصم منك.")
PROBE_MODEL = "anthropic/claude-haiku-5.5"
# The status an order is put back in for the step it resumes at.
RESUME_STATUS = {"scenarios": "scenarios_generating", "planning": "production_planning",
                 "assets": "assets_generating", "assembly": "assembling"}

_cache: dict = {"at": 0.0, "doc": None}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_balance_message(message) -> bool:
    text = str(message or "").lower()
    return any(m in text for m in LOCK_MARKERS)


async def _doc(fresh: bool = False) -> dict:
    if not fresh and _cache["doc"] is not None and time.monotonic() - _cache["at"] < CACHE_SECONDS:
        return _cache["doc"]
    doc = await db.engine_health.find_one({"id": DOC_ID}, {"_id": 0}) or {"id": DOC_ID, "locked": False}
    _cache.update(at=time.monotonic(), doc=doc)
    return doc


async def status(fresh: bool = False) -> dict:
    d = await _doc(fresh)
    return {"locked": bool(d.get("locked")), "locked_at": d.get("locked_at"), "stage": d.get("stage"),
            "message": d.get("message"), "cleared_at": d.get("cleared_at"),
            "paused_orders": await db.orders.count_documents({"engine_paused": {"$ne": None},
                                                               "status": {"$in": list(PAUSABLE)}})}


async def is_locked(fresh: bool = False) -> bool:
    return bool((await _doc(fresh)).get("locked"))


async def ensure_available() -> None:
    """Routes call this before anything that would spend money or start paid
    work: a locked engine turns the parent away before they pay."""
    if await is_locked(fresh=True):
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=BUSY_AR)


async def note_error(stage: str, message) -> None:
    """Called by the fal adapter on every HTTP error; acts only on a balance lock."""
    if not is_balance_message(message):
        return
    await db.engine_health.update_one({"id": DOC_ID}, {"$setOnInsert": {"id": DOC_ID, "locked": False}}, upsert=True)
    res = await db.engine_health.update_one(
        {"id": DOC_ID, "locked": {"$ne": True}},
        {"$set": {"locked": True, "locked_at": _now(), "stage": stage, "message": str(message)[:300]}},
    )
    _cache["at"] = 0.0
    if res.modified_count:
        logger.error(f"[engine] fal balance exhausted (first seen in {stage}): new orders are paused")
        try:
            asyncio.get_running_loop().create_task(_alert(stage))
        except RuntimeError:
            pass


async def note_success() -> None:
    """Called by the fal adapter after a call succeeds."""
    if not (await _doc()).get("locked"):
        return
    res = await db.engine_health.update_one({"id": DOC_ID, "locked": True},
                                            {"$set": {"locked": False, "cleared_at": _now()}})
    _cache["at"] = 0.0
    if res.modified_count:
        logger.info("[engine] fal answered again: engine unlocked")


async def _alert(stage: str) -> None:
    from services.notify_service import _setting, send_email, smtp_config

    ops = await _setting("notify.ops_email")
    if not ops or not await smtp_config():
        return
    try:
        await send_email(ops, "رصيد fal خلص — التوليد واقف", [
            f"fal رفض طلب في مرحلة {stage} لأن الرصيد خلص.",
            "الطلبات الجديدة والدفع متوقفين لحد ما يتشحن. أي طلب وقف في النص متعلّم «موقوف».",
            "بعد الشحن: لوحة الإدارة ← البانر اللي فوق ← «استكمال الطلبات الموقوفة».",
        ])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[engine] alert email not sent: {type(e).__name__}: {e}")


async def tag_if_paused(order_id: str, to_status: str) -> bool:
    """On a failed status: if the engine is locked, the failure is ours, not the
    story's — tag the order so it's resumed after the top-up."""
    if to_status not in PAUSABLE:
        return False
    if not await is_locked(fresh=True):
        # A later failure with a working engine is a real failure again.
        await db.orders.update_one({"id": order_id, "engine_paused": {"$ne": None}}, {"$set": {"engine_paused": None}})
        return False
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "status_history": {"$slice": -1}})
    last = ((order or {}).get("status_history") or [{}])[-1]
    await db.orders.update_one({"id": order_id, "status": to_status},
                               {"$set": {"engine_paused": {"at": _now(), "from_status": last.get("from")}}})
    return True


async def probe() -> dict:
    """A free one-byte upload and a few tokens of Haiku through fal (a fraction of
    a cent): the only way to know the balance works — fal's status endpoint
    answers fine on a locked account."""
    from services.ai import AIError, fal
    from services.ai.text_client import generate_text

    started = time.monotonic()
    try:
        # A free one-byte upload first: on an exhausted account fal still served
        # small text requests while uploads (and every image, clip and voice)
        # were refused.
        await fal.upload(env_key="FAL_KEY_SCENE", data=b"ok", content_type="text/plain", file_name="probe.txt")
        await generate_text(stage="engine_probe", provider="fal_llm", model=PROBE_MODEL,
                            system="Reply with the single word OK.", user="ping", effort="low",
                            max_tokens=16, timeout=45.0)
    except AIError as e:
        locked = is_balance_message(e)
        return {"ok": False, "locked": locked, "latency_ms": int((time.monotonic() - started) * 1000),
                "error": "رصيد fal خلص" if locked else str(e)[:200]}
    return {"ok": True, "locked": False, "latency_ms": int((time.monotonic() - started) * 1000), "error": None}


async def resume_paused(actor_id: str | None = None) -> dict:
    """After a top-up: probe once, then restart every paused order from the step
    it stopped at (drawn sheets, keyframes and paid clips are reused)."""
    from services.order_state import claim
    from services.recovery_service import STEP_OF_STATUS, _resume

    check = await probe()
    if not check["ok"]:
        return {"ok": False, "error": check["error"], "resumed": [], "skipped": []}
    resumed, skipped = [], []
    async for o in db.orders.find({"engine_paused": {"$ne": None}, "status": {"$in": list(PAUSABLE)}},
                                  {"_id": 0, "id": 1, "status": 1, "engine_paused": 1, "current_scenario_batch_id": 1}):
        step = STEP_OF_STATUS.get((o.get("engine_paused") or {}).get("from_status") or "")
        if not step:
            skipped.append(o["id"])
            continue
        if step == "assembly":
            from routes.media_routes import assets_complete
            if not await assets_complete(o["id"]):
                step = "assets"
        back_to = RESUME_STATUS[step]
        if not await claim(o["id"], (o["status"],), back_to, "admin", actor_id=actor_id,
                           reason="استكمال بعد شحن رصيد المحرك", extra={"engine_paused": None}):
            skipped.append(o["id"])
            continue
        try:
            await _resume({**o, "status": back_to}, step)
            resumed.append(o["id"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[engine] resume {o['id'][:8]} failed: {type(e).__name__}: {e}")
            skipped.append(o["id"])
    return {"ok": True, "error": None, "resumed": resumed, "skipped": skipped}
