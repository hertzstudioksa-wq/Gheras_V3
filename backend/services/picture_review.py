"""The parent checks the story's pictures before any of them is animated.

Every picture is drawn and checked first anyway (shot_pipeline); here the order
then waits in `pictures_review` instead of going straight to the clips. The parent
sees each shot's start picture with its narration line, may send a few back to be
drawn again, and approves; the pipeline then resumes and animates them (drawn
sheets, pictures and the voice are reused). The owner held himself to the same
rule ("no video before I confirm the pictures"): a rejected video costs far more
than a redrawn picture, and a parent who chose the pictures isn't surprised by the
story. A parent who doesn't answer is approved for after a while, so a story never
waits forever. A waiting order holds no generation slot (services/limits.py) and
isn't "resumed" by the recovery after a restart (it isn't stuck).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from db import db
from models import OrderStatus

logger = logging.getLogger("picture_review")

ENABLED_KEY = "review.parent_pictures"
REDRAWS_KEY = "review.parent_redraws"
AUTO_HOURS_KEY = "review.auto_approve_hours"
DEFAULT_REDRAWS = 3
DEFAULT_AUTO_HOURS = 24
CHECK_EVERY_SECONDS = 600
# A redraw cut short by a restart frees the review after this; the approval draws any
# picture still missing.
REDRAW_STALE_MINUTES = 20
# Why the parent sent a picture back (kept for the admin; the redraw is a fresh take
# through the same checks either way).
REASONS = {"likeness": "الشخص مش شبهه", "people": "فيه شخص زيادة أو ناقص", "other": "حاجة تانية غلط"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _setting(key: str, default):
    s = await db.settings.find_one({"key": key}, {"_id": 0, "value": 1})
    value = (s or {}).get("value", default)
    return default if value is None else value


async def enabled() -> bool:
    return await _setting(ENABLED_KEY, True) is not False


async def waits(order: dict) -> bool:
    """The pictures are drawn and this order's parent hasn't approved them yet."""
    return await enabled() and not (order.get("picture_review") or {}).get("approved_at")


async def open_review(order_id: str) -> bool:
    """The pipeline stops here: the order waits for its parent (from assets_generating)."""
    from services.order_state import claim

    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "picture_review": 1}) or {}
    review = order.get("picture_review") or {}
    left = review.get("redraws_left")
    if left is None:
        left = int(await _setting(REDRAWS_KEY, DEFAULT_REDRAWS))
    return await claim(order_id, (OrderStatus.ASSETS_GENERATING.value,), OrderStatus.PICTURES_REVIEW.value, "system",
                       reason="الصور جاهزة لمراجعة ولي الأمر",
                       extra={"picture_review": {**review, "state": "waiting", "waiting_since": _now(),
                                                 "redraws_left": int(left), "redrawing": []}})


async def pictures(order: dict) -> dict:
    """What the parent sees: each shot's start picture and line, nothing internal."""
    from services.shot_pipeline import shot_rows

    review = order.get("picture_review") or {}
    redrawing = {tuple(k) for k in review.get("redrawing") or []}
    rows = await shot_rows(order["id"], order["production_plan_id"]) if order.get("production_plan_id") else []
    shots = [{"scene_index": r["scene_index"], "shot_index": r["shot_index"],
              "picture_url": r.get("keyframe_url"), "narration_line": r.get("narration_line") or "",
              "redrawing": (r["scene_index"], r["shot_index"]) in redrawing,
              "redrawn": bool(r.get("parent_redraw"))} for r in rows]
    return {"state": review.get("state"), "redraws_left": int(review.get("redraws_left") or 0),
            "reasons": REASONS, "shots": shots}


class ReviewError(Exception):
    """A request the review can't take now (message for the parent)."""


async def redraw(order: dict, keys: list[tuple[int, int]], reason: str, actor_id: str | None) -> dict:
    """Send some pictures back: their rows are cleared and the scenes drawn again in
    the background (only the cleared shots; each new picture gets its end picture)."""
    from services.engine_health import ensure_available

    review = order.get("picture_review") or {}
    if order.get("status") != OrderStatus.PICTURES_REVIEW.value or review.get("state") != "waiting":
        raise ReviewError("الصور مش جاهزة للمراجعة دلوقتي")
    keys = sorted({(int(s), int(h)) for s, h in keys})
    if not keys:
        raise ReviewError("اختار صورة واحدة على الأقل")
    left = int(review.get("redraws_left") or 0)
    if len(keys) > left:
        raise ReviewError(f"متبقي لك {left} إعادة رسم بس")
    if reason not in REASONS:
        reason = "other"
    rows = {(r["scene_index"], r["shot_index"]): r async for r in db.shot_assets.find(
        {"order_id": order["id"], "production_plan_id": order["production_plan_id"]},
        {"_id": 0, "scene_index": 1, "shot_index": 1, "scene_plan_id": 1})}
    missing = [k for k in keys if k not in rows]
    if missing:
        raise ReviewError("صورة من دول مش موجودة")
    await ensure_available()
    at = _now()
    claimed = await db.orders.update_one(
        {"id": order["id"], "status": OrderStatus.PICTURES_REVIEW.value, "picture_review.state": "waiting"},
        {"$set": {"picture_review.state": "redrawing", "picture_review.redrawing": [list(k) for k in keys],
                  "picture_review.redraw_started_at": at, "updated_at": at},
         "$inc": {"picture_review.redraws_left": -len(keys)},
         "$push": {"picture_review.requests": {"at": at, "shots": [list(k) for k in keys], "reason": reason,
                                               "by": actor_id}}})
    if not claimed.modified_count:
        raise ReviewError("الصور بتتعاد دلوقتي")
    for k in keys:
        # A stale Comfy job id would hand back the old picture instead of a new one.
        await db.shot_assets.update_one(
            {"order_id": order["id"], "production_plan_id": order["production_plan_id"],
             "scene_index": k[0], "shot_index": k[1]},
            {"$set": {"keyframe_url": None, "keyframe_review": None, "keyframe_prompt_id": None,
                      "keyframe_prompt_attempt": None, "end_keyframe_url": None, "end_frame_review": None,
                      "clip_url": None, "clip_request_id": None, "clip_prompt_id": None, "clip_state": None,
                      "clip_review": None, "parent_redraw": {"reason": reason, "at": at}}})
    scenes = sorted({rows[k]["scene_plan_id"] for k in keys})
    asyncio.get_running_loop().create_task(_redraw_now(order["id"], scenes))
    return {"redrawing": [list(k) for k in keys], "redraws_left": left - len(keys)}


async def _redraw_now(order_id: str, scene_plan_ids: list[str]) -> None:
    from services import shot_pipeline
    from services.ai.fake_providers import CURRENT_ORDER

    CURRENT_ORDER.set(order_id)  # Comfy serves this order's pictures in its usual place in line
    try:
        order = await db.orders.find_one({"id": order_id}, {"_id": 0})
        plan = await db.production_plans.find_one({"id": order["production_plan_id"]}, {"_id": 0})
        for scene_id in scene_plan_ids:
            # Draws only the shots without a start picture: the ones sent back.
            await shot_pipeline.execute_scene_keyframes({"id": f"parent-redraw-{uuid.uuid4()}", "target_id": scene_id},
                                                        order, plan)
    except Exception as e:  # noqa: BLE001 — the approval draws whatever is still missing
        logger.warning(f"[picture_review] redraw for {order_id[:8]} failed: {type(e).__name__}: {str(e)[:200]}")
    finally:
        await db.orders.update_one({"id": order_id, "picture_review.state": "redrawing"}, {"$set": {
            "picture_review.state": "waiting", "picture_review.redrawing": [], "picture_review.waiting_since": _now(),
            "updated_at": _now()}})


async def approve(order_id: str, by: str, actor_id: str | None = None, background=None) -> bool:
    """The parent (or the clock) approves: back to the pipeline, which animates the pictures."""
    from routes.media_routes import trigger_asset_generation
    from services.order_state import claim
    from services.recovery_service import _Background

    if not await claim(order_id, (OrderStatus.PICTURES_REVIEW.value,), OrderStatus.PRODUCTION_APPROVED.value, by,
                       actor_id=actor_id, where={"picture_review.state": "waiting"},
                       reason="ولي الأمر اعتمد الصور" if by == "user" else "اعتماد الصور تلقائياً بعد المهلة"
                       if by == "system" else "الإدارة اعتمدت الصور",
                       extra={"picture_review.state": "approved", "picture_review.approved_at": _now(),
                              "picture_review.approved_by": by}):
        return False
    await trigger_asset_generation(order_id, background or _Background())
    return True


async def sweep() -> dict:
    """Approves pictures nobody answered for, and frees a redraw a restart cut short."""
    approved, freed = [], []
    stale = (datetime.now(timezone.utc) - timedelta(minutes=REDRAW_STALE_MINUTES)).isoformat()
    async for o in db.orders.find({"status": OrderStatus.PICTURES_REVIEW.value, "picture_review.state": "redrawing",
                                   "picture_review.redraw_started_at": {"$lt": stale}}, {"_id": 0, "id": 1}):
        await db.orders.update_one({"id": o["id"], "picture_review.state": "redrawing"}, {"$set": {
            "picture_review.state": "waiting", "picture_review.redrawing": [], "picture_review.waiting_since": _now()}})
        freed.append(o["id"])
    hours = float(await _setting(AUTO_HOURS_KEY, DEFAULT_AUTO_HOURS) or 0)
    if hours > 0:
        due = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        async for o in db.orders.find({"status": OrderStatus.PICTURES_REVIEW.value, "picture_review.state": "waiting",
                                       "picture_review.waiting_since": {"$lt": due}}, {"_id": 0, "id": 1}):
            if await approve(o["id"], "system"):
                approved.append(o["id"])
    if approved or freed:
        logger.info(f"[picture_review] auto-approved {len(approved)}, freed {len(freed)} redraws")
    return {"approved": approved, "freed": freed}


async def sweep_forever() -> None:
    while True:
        try:
            await sweep()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[picture_review] sweep failed: {type(e).__name__}: {e}")
        await asyncio.sleep(CHECK_EVERY_SECONDS)
