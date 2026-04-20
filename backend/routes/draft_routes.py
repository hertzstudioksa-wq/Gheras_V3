"""Server-side drafts (one per user)."""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends

from db import db
from auth import get_current_user
from models import DraftUpsert

router = APIRouter(prefix="/drafts", tags=["drafts"])


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.get("/current")
async def get_current_draft(current=Depends(get_current_user)):
    doc = await db.drafts.find_one({"user_id": current["id"]}, {"_id": 0})
    return doc or {"current_step": 1, "data": {}, "user_id": current["id"]}


@router.put("/current")
async def upsert_draft(payload: DraftUpsert, current=Depends(get_current_user)):
    await db.drafts.update_one(
        {"user_id": current["id"]},
        {"$set": {
            "user_id": current["id"],
            "current_step": payload.current_step,
            "data": payload.data,
            "updated_at": _now(),
        }},
        upsert=True,
    )
    return {"ok": True}


@router.delete("/current")
async def clear_draft(current=Depends(get_current_user)):
    await db.drafts.delete_one({"user_id": current["id"]})
    return {"ok": True}
