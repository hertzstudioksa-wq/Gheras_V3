"""A heartbeat on orders while a process is working on them.

Restart recovery resumes orders "caught mid-run". An order's updated_at can sit
still for minutes (five character sheets are drawn without a status change), so
another process sharing the database — a second worker, or a rehearsal server
on another port — would have taken a running order for an interrupted one and
started a second paid run. While a run is alive it stamps `heartbeat_at` every
HEARTBEAT_SECONDS; recovery leaves alone any order with a recent heartbeat.
"""
from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timedelta, timezone

from db import db

HEARTBEAT_SECONDS = 30
STALE_AFTER = timedelta(seconds=HEARTBEAT_SECONDS * 3)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stale_before() -> str:
    """Orders whose heartbeat is older than this are no longer being worked on."""
    return (_now() - STALE_AFTER).isoformat()


@contextlib.asynccontextmanager
async def beating(order_id: str):
    async def beat():
        while True:
            await db.orders.update_one({"id": order_id}, {"$set": {"heartbeat_at": _now().isoformat()}})
            await asyncio.sleep(HEARTBEAT_SECONDS)

    task = asyncio.create_task(beat())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
