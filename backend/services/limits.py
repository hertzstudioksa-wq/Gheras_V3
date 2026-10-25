"""Capacity limits that keep a busy day from taking the server down.

* Generation queue (`generation.max_parallel_orders`): how many orders may be in
  the asset stage (drawing, voicing, animating) at once. The rest wait in order
  of approval; the parent sees their place. Counted from the database, so it
  holds across restarts and processes. When keyframes or clips run on Comfy,
  the limit is also capped at Comfy's slots + 1 (`comfy.max_concurrent`).
* Render slots (`render.max_parallel`): how many video assemblies (ffmpeg, ~0.6
  GB) and picture books (Chromium, ~1.1 GB) run at once in this process.

Both limits are admin settings, re-read every few seconds (no restart needed).
Measured numbers and the sizing behind the defaults: .claude/production-plan.md.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timedelta, timezone

from db import db

logger = logging.getLogger("limits")

GENERATION_SETTING = "generation.max_parallel_orders"
RENDER_SETTING = "render.max_parallel"
DEFAULTS = {GENERATION_SETTING: 6, RENDER_SETTING: 1}
RECHECK_SECONDS = 15
LIMIT_CACHE_SECONDS = 10
GRANT_TTL_SECONDS = 600
# Orders in these statuses hold a generation slot.
GENERATING = ("assets_generating",)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def setting_int(key: str) -> int:
    try:
        doc = await db.settings.find_one({"key": key}, {"_id": 0, "value": 1})
        return max(1, int((doc or {}).get("value") or DEFAULTS[key]))
    except Exception:  # noqa: BLE001 — a settings hiccup must not stop the engine
        return DEFAULTS[key]


# ---------------------------------------------------------------- generation queue
# With shot keyframes/clips on Comfy, every story waits for the same GPU slots:
# more stories at once than slots only interleaves them (all finish late). One
# extra story fills the gap while its sheets and voice are made on fal.
COMFY_EXTRA_ORDERS = 1
_comfy_cache: dict = {"at": -1e9, "in_use": False}


async def generation_limit() -> tuple[int, str]:
    """How many stories may generate at once, and what set it ("setting"/"comfy")."""
    limit = await setting_int(GENERATION_SETTING)
    try:
        if time.monotonic() - _comfy_cache["at"] > LIMIT_CACHE_SECONDS * 3:
            from services import engine_health
            _comfy_cache.update(at=time.monotonic(), in_use=await engine_health.comfy_in_use())
        if _comfy_cache["in_use"]:
            from services.ai.comfy import _max_concurrent
            tied = await _max_concurrent() + COMFY_EXTRA_ORDERS
            if tied < limit:
                return tied, "comfy"
    except Exception as e:  # noqa: BLE001 — fall back to the plain setting
        logger.warning(f"[queue] comfy-tied limit unavailable: {type(e).__name__}: {e}")
    return limit, "setting"


async def queue_position(order_id: str, since: str) -> int:
    """1 = next to start."""
    ahead = await db.orders.count_documents({
        "id": {"$ne": order_id}, "status": "production_approved",
        "generation_queue.since": {"$lt": since},
    })
    return ahead + 1


async def wait_for_generation_slot(order_id: str) -> None:
    """Hold an approved order until a generation slot is free (first approved,
    first served). Its heartbeat keeps running meanwhile, so a restart resumes
    it into the queue again instead of starting it twice."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "generation_queue": 1})
    since = ((order or {}).get("generation_queue") or {}).get("since") or _now()
    announced = False
    while True:
        limit, _why = await generation_limit()
        # A slot just granted counts at once: the order's status only becomes
        # assets_generating a moment later, and the next in line must not slip
        # into that gap. A grant that never turned into work expires.
        fresh = (datetime.now(timezone.utc) - timedelta(seconds=GRANT_TTL_SECONDS)).isoformat()
        busy = await db.orders.count_documents({"id": {"$ne": order_id}, "$or": [
            {"status": {"$in": list(GENERATING)}},
            {"status": "production_approved", "generation_queue.granted_at": {"$gt": fresh}},
        ]})
        position = await queue_position(order_id, since)
        if busy + position - 1 < limit:
            if announced:
                logger.info(f"[queue] order {order_id[:8]} starts (busy {busy}/{limit})")
            await db.orders.update_one({"id": order_id}, {"$set": {"generation_queue": {"granted_at": _now()}}})
            return
        await db.orders.update_one({"id": order_id}, {"$set": {
            "generation_queue": {"since": since, "position": position, "limit": limit, "checked_at": _now()}}})
        if not announced:
            logger.info(f"[queue] order {order_id[:8]} waits: position {position}, busy {busy}/{limit}")
            announced = True
        await asyncio.sleep(RECHECK_SECONDS)


# ---------------------------------------------------------------- render slots
class DynamicGate:
    """At most N holders at once in this process, N read from a setting."""

    def __init__(self, setting: str):
        self.setting = setting
        self._cond: asyncio.Condition | None = None
        self._busy = 0
        self._limit, self._at = DEFAULTS[setting], -1e9

    async def _current_limit(self) -> int:
        if time.monotonic() - self._at > LIMIT_CACHE_SECONDS:
            self._limit, self._at = await setting_int(self.setting), time.monotonic()
        return self._limit

    @contextlib.asynccontextmanager
    async def slot(self):
        if self._cond is None:
            self._cond = asyncio.Condition()
        async with self._cond:
            while self._busy >= await self._current_limit():
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self._cond.wait(), LIMIT_CACHE_SECONDS)
            self._busy += 1
        try:
            yield
        finally:
            async with self._cond:
                self._busy -= 1
                self._cond.notify_all()


render_gate = DynamicGate(RENDER_SETTING)
