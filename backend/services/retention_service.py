"""Storage retention for delivered stories (off until an admin sets the days).

A 45 s story stores 210–330 MB, but what the parent keeps is 25–35 MB: the
final video, the picture book, the cover and the character sheets. The rest
(Kling clips, shot keyframes, per-shot voice lines, scene narration, music,
and the older versions left by re-assembly) is only needed to redo a shot.

`retention.intermediate_days` days after delivery (0 = never) those files are
deleted, except for orders with an open problem report. The window should stay
longer than the 14 days the terms give to report a defect (suggested: 30).
After pruning, a shot can no longer be redone and the book can't be rebuilt.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from db import db
from services.audit_service import record_audit

logger = logging.getLogger("retention")

SETTING = "retention.intermediate_days"
# Generated folders (orders/<id>/generated/<kind>/) that are working files.
INTERMEDIATE_KINDS = ("clip", "clips", "keyframe", "scene", "narration", "narration-line", "audio", "music")
# Folders whose newest file is the deliverable and older ones are leftovers.
VERSIONED_KINDS = ("final-video", "final-pdf", "cover")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file_id(url: str | None) -> str | None:
    return str(url).rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0] if url else None


async def retention_days() -> int:
    doc = await db.settings.find_one({"key": SETTING}, {"_id": 0, "value": 1})
    try:
        return max(0, int((doc or {}).get("value") or 0))
    except (TypeError, ValueError):
        return 0


async def _kept_file_ids(order_id: str) -> set[str]:
    """The deliverables of an order: newest final video (+thumbnail), PDF, cover."""
    keep: set[str] = set()
    v = await db.final_videos.find_one({"order_id": order_id}, {"_id": 0, "video_url": 1, "thumbnail_url": 1},
                                       sort=[("created_at", -1)])
    p = await db.final_pdfs.find_one({"order_id": order_id}, {"_id": 0, "pdf_url": 1}, sort=[("created_at", -1)])
    c = await db.scene_images.find_one({"order_id": order_id, "kind": "cover"}, {"_id": 0, "image_url": 1},
                                       sort=[("created_at", -1)])
    for url in ((v or {}).get("video_url"), (v or {}).get("thumbnail_url"), (p or {}).get("pdf_url"),
                (c or {}).get("image_url")):
        if _file_id(url):
            keep.add(_file_id(url))
    return keep


async def prune_order(order: dict, *, reason: str, actor: dict | None = None) -> dict:
    """Delete one delivered order's working files; returns counts."""
    from services.privacy_service import _delete_files

    oid = order["id"]
    keep = await _kept_file_ids(oid)
    kinds = "|".join(INTERMEDIATE_KINDS + VERSIONED_KINDS)
    candidates = [f async for f in db.files.find(
        {"storage_path": {"$regex": f"orders/{oid}/generated/({kinds})/"}, "is_deleted": False},
        {"_id": 0, "id": 1, "size": 1})]
    ids = [f["id"] for f in candidates if f["id"] not in keep]
    freed = sum(int(f.get("size") or 0) for f in candidates if f["id"] not in keep)
    n = await _delete_files({"id": {"$in": ids}}) if ids else 0
    await db.orders.update_one({"id": oid}, {"$set": {"intermediates_pruned_at": _now().isoformat(),
                                                       "intermediates_pruned": {"files": n, "bytes": freed}}})
    await record_audit(entity_type="order", entity_id=oid, action="retention.pruned",
                       actor_id=(actor or {}).get("id"), actor_email=(actor or {}).get("email"),
                       summary=f"مسح {n} ملف وسيط ({freed / 1e6:.0f} ميجا) — {reason}")
    return {"files": n, "bytes": freed}


async def prune_delivered(days: int | None = None) -> int:
    """Prune every story delivered more than `days` ago (setting when None)."""
    days = await retention_days() if days is None else days
    if days <= 0:
        return 0
    cutoff = (_now() - timedelta(days=days)).isoformat()
    done = 0
    async for o in db.orders.find(
        {"status": {"$in": ["delivered", "completed"]}, "intermediates_pruned_at": {"$exists": False},
         "updated_at": {"$lt": cutoff}, "feedback.problem_status": {"$ne": "open"}},
        {"_id": 0, "id": 1, "status_history": 1},
    ):
        delivered_at = next((h.get("at") for h in reversed(o.get("status_history") or [])
                             if h.get("to") in ("delivered", "completed")), None)
        if delivered_at and delivered_at > cutoff:
            continue
        await prune_order(o, reason=f"{days} يوم بعد التسليم")
        done += 1
    if done:
        logger.info(f"[retention] pruned working files of {done} delivered stories")
    return done
