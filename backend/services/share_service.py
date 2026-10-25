"""Private watch links for the family (owner decision, 2026-10-25).

The WhatsApp button only shared the website. A parent can now make a link to
their delivered story: unguessable, expires after 30 days, and they can switch
it off any time; deleting the account switches it off too. The page behind it
shows the story's video, cover and title — not the parent's name or photos.
"""
from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from db import db

SHARE_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file_id(url: str | None) -> str | None:
    return url.rsplit("/", 1)[-1] if url and "/api/uploads/file/" in url else None


async def active_link(order_id: str) -> dict | None:
    return await db.share_links.find_one(
        {"order_id": order_id, "revoked_at": None, "expires_at": {"$gt": _now().isoformat()}},
        {"_id": 0}, sort=[("created_at", -1)])


async def create(order: dict) -> dict:
    """A fresh link (any older one stops working)."""
    await revoke(order["id"])
    link = {"id": str(uuid.uuid4()), "token": secrets.token_urlsafe(24), "order_id": order["id"],
            "user_id": order["user_id"], "created_at": _now().isoformat(),
            "expires_at": (_now() + timedelta(days=SHARE_DAYS)).isoformat(), "revoked_at": None, "views": 0}
    await db.share_links.insert_one(link)
    link.pop("_id", None)
    return link


async def revoke(order_id: str) -> int:
    res = await db.share_links.update_many({"order_id": order_id, "revoked_at": None},
                                           {"$set": {"revoked_at": _now().isoformat()}})
    return res.modified_count


async def revoke_for_user(user_id: str) -> int:
    res = await db.share_links.update_many({"user_id": user_id, "revoked_at": None},
                                           {"$set": {"revoked_at": _now().isoformat()}})
    return res.modified_count


async def resolve(token: str) -> dict | None:
    """What a valid link shows: {link, title, child_name, video_file_id, cover_file_id}."""
    if not token or len(token) > 64:
        return None
    link = await db.share_links.find_one({"token": token, "revoked_at": None}, {"_id": 0})
    if not link or link["expires_at"] <= _now().isoformat():
        return None
    order = await db.orders.find_one({"id": link["order_id"], "status": "delivered"},
                                     {"_id": 0, "production_plan_id": 1, "data.child.name": 1, "data_deleted_at": 1})
    if not order or order.get("data_deleted_at"):
        return None
    video = await db.final_videos.find_one({"order_id": link["order_id"]}, {"_id": 0, "video_url": 1},
                                           sort=[("created_at", -1)])
    if not _file_id((video or {}).get("video_url")):
        return None
    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0, "title": 1})
    cover = await db.scene_images.find_one({"order_id": link["order_id"], "kind": "cover",
                                            "production_plan_id": order.get("production_plan_id")},
                                           {"_id": 0, "image_url": 1}, sort=[("created_at", -1)])
    return {"link": link, "title": (plan or {}).get("title") or "",
            "child_name": ((order.get("data") or {}).get("child") or {}).get("name") or "",
            "video_file_id": _file_id(video["video_url"]), "cover_file_id": _file_id((cover or {}).get("image_url"))}


async def count_view(link_id: str) -> None:
    await db.share_links.update_one({"id": link_id}, {"$inc": {"views": 1},
                                                      "$set": {"last_viewed_at": _now().isoformat()}})
