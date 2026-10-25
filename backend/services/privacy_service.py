"""Children's data (audit CS-7): consent, deleting original photos, deleting an account.

What the privacy page promises, this module does:
  * The parent's original photos (child, relatives, toy) are deleted
    `ORIGINAL_PHOTO_DAYS` after the story is delivered, or right away when the
    parent asks. The drawn characters and the finished story stay theirs.
  * Deleting an account removes the parent's personal data: every file they
    uploaded or we made for them, the child's details on their orders, and their
    name and email. Payment records stay for accounting, without the email.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from db import db
from services.audit_service import record_audit

logger = logging.getLogger("privacy")

CONSENT_VERSION = "2026-10-24"
ORIGINAL_PHOTO_DAYS = 30
PHOTO_SCOPES = ("child", "character", "toy")
BUSY_STATUSES = ("scenarios_generating", "ready_for_ai", "production_planning", "production_approved",
                 "assets_generating", "assets_ready", "assembling", "generating")
SWEEP_EVERY_SECONDS = 6 * 3600


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file_id(url: str | None) -> str | None:
    if not url:
        return None
    return str(url).rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0] or None


def order_photo_ids(order: dict) -> list[str]:
    data = order.get("data") or {}
    urls = [(data.get("child") or {}).get("image_url")]
    urls += [c.get("image_url") for c in data.get("characters") or []]
    urls.append((data.get("personalization") or {}).get("toy_image_url"))
    return [fid for fid in map(_file_id, urls) if fid]


async def _delete_files(query: dict) -> int:
    """Delete the stored objects and mark the rows deleted. Returns the count."""
    from storage import delete_object

    n = 0
    async for f in db.files.find({**query, "is_deleted": False}, {"_id": 0, "id": 1, "storage_path": 1}):
        try:
            await asyncio.to_thread(delete_object, f["storage_path"])
        except Exception as e:  # noqa: BLE001 — a missing object is already deleted
            logger.warning(f"[privacy] delete {f['id']}: {type(e).__name__}: {e}")
        await db.files.update_one({"id": f["id"]}, {"$set": {"is_deleted": True, "deleted_at": _now().isoformat()}})
        n += 1
    return n


async def delete_order_photos(order: dict, *, actor: dict | None, reason: str) -> int:
    """Delete the parent's original photos for one order (not the drawings)."""
    ids = order_photo_ids(order)
    n = await _delete_files({"id": {"$in": ids}, "user_id": order["user_id"], "scope": {"$in": list(PHOTO_SCOPES)}}) if ids else 0
    await db.orders.update_one({"id": order["id"]}, {"$set": {"photos_deleted_at": _now().isoformat()}})
    await record_audit(entity_type="order", entity_id=order["id"], action="privacy.photos_deleted",
                       actor_id=(actor or {}).get("id"), actor_email=(actor or {}).get("email"),
                       summary=f"مسح {n} صورة أصلية — {reason}")
    return n


async def purge_old_photos(days: int = ORIGINAL_PHOTO_DAYS) -> int:
    """Delete original photos of orders delivered more than `days` ago."""
    cutoff = (_now() - timedelta(days=days)).isoformat()
    done = 0
    async for o in db.orders.find(
        # Orders placed under this promise (with consent); older orders were never told.
        {"status": {"$in": ["delivered", "completed"]}, "photos_deleted_at": {"$exists": False},
         "consent.version": {"$exists": True}, "updated_at": {"$lt": cutoff}},
        {"_id": 0, "id": 1, "user_id": 1, "data": 1, "status_history": 1},
    ):
        delivered_at = next((h.get("at") for h in reversed(o.get("status_history") or [])
                             if h.get("to") in ("delivered", "completed")), None)
        if delivered_at and delivered_at > cutoff:
            continue
        await delete_order_photos(o, actor=None, reason=f"{days} يوم بعد التسليم")
        done += 1
    if done:
        logger.info(f"[privacy] deleted original photos of {done} delivered orders")
    return done


async def sweep_forever() -> None:
    """Started at boot: the photo-retention promise runs on its own."""
    from services.retention_service import prune_delivered

    while True:
        try:
            await purge_old_photos()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[privacy] sweep failed: {type(e).__name__}: {e}")
        try:
            await prune_delivered()  # off until retention.intermediate_days is set
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[retention] sweep failed: {type(e).__name__}: {e}")
        await asyncio.sleep(SWEEP_EVERY_SECONDS)


async def delete_account(user_id: str, *, actor: dict | None, reason: str) -> dict:
    """Remove a parent's personal data. Refuses while a story is being made or
    while wallet credit is left (that money is refunded first)."""
    from services.wallet_service import balance

    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise LookupError("المستخدم غير موجود")
    if user.get("role") == "admin":
        raise ValueError("حساب الأدمن ما يتمسحش من هنا")
    if await db.orders.count_documents({"user_id": user_id, "status": {"$in": list(BUSY_STATUSES)}}):
        raise ValueError("لديك قصة قيد التجهيز — انتظر حتى تكتمل ثم احذف الحساب")
    credit = await balance(user_id)
    if credit > 0:
        raise ValueError(f"لديك رصيد {credit / 100:.2f} ر.س — تواصل معنا لاسترداده قبل حذف الحساب")

    from services.share_service import revoke_for_user
    await revoke_for_user(user_id)  # family watch links stop working first
    files = await _delete_files({"user_id": user_id})
    orders = await db.orders.update_many({"user_id": user_id}, {
        "$set": {"data.child": {"name": "محذوف", "age": None, "gender": None, "image_url": None},
                 "data.characters": [], "data.personalization": {}, "data.goal.context": "",
                 "enriched": {}, "ai_prompt_snapshot": None, "data_deleted_at": _now().isoformat()},
    })
    gone = f"deleted-{uuid.uuid4().hex[:12]}@deleted.invalid"
    await db.users.update_one({"id": user_id}, {
        "$set": {"email": gone, "full_name": "حساب محذوف", "hashed_password": "!", "is_active": False,
                 "deleted_at": _now().isoformat()},
        "$inc": {"token_version": 1},
    })
    await db.payments.update_many({"user_id": user_id}, {"$set": {"user_email": gone}})
    await db.drafts.delete_many({"user_id": user_id})
    await record_audit(entity_type="user", entity_id=user_id, action="privacy.account_deleted",
                       actor_id=(actor or {}).get("id"), actor_email=(actor or {}).get("email"),
                       summary=f"مسح بيانات حساب: {files} ملف، {orders.modified_count} طلب — {reason}")
    return {"files": files, "orders": orders.modified_count}
