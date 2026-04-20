"""Order endpoints — v2 structured JSON."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

from db import db
from auth import get_current_user
from models import OrderCreate, OrderStatus, ORDER_STATUS_AR
from prompt_engine import build_prompt

router = APIRouter(prefix="/orders", tags=["orders"])


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _enrich(data: dict) -> dict:
    """Resolve names for category/subcategory/style ids to embed alongside JSON."""
    goal = data.get("goal", {}) or {}
    style = data.get("style", {}) or {}
    out = {}

    if goal.get("category_id"):
        cat = await db.categories.find_one({"id": goal["category_id"]}, {"_id": 0, "name_ar": 1})
        if cat:
            out["category_name"] = cat["name_ar"]
    if goal.get("subcategory_id"):
        sub = await db.subcategories.find_one({"id": goal["subcategory_id"]}, {"_id": 0, "name_ar": 1})
        if sub:
            out["subcategory_name"] = sub["name_ar"]

    for k, field in [
        ("type_id", "type_name"), ("tone_id", "tone_name"), ("setting_id", "setting_name"),
        ("language_id", "language_name"), ("voice_id", "voice_name"),
    ]:
        if style.get(k):
            opt = await db.story_options.find_one({"id": style[k]}, {"_id": 0, "name_ar": 1})
            if opt:
                out[field] = opt["name_ar"]
    return out


@router.post("")
async def create_order(payload: OrderCreate, current=Depends(get_current_user)):
    data = payload.data.model_dump()

    # basic ref validation
    if not await db.categories.find_one({"id": data["goal"]["category_id"], "is_active": True}):
        raise HTTPException(status_code=400, detail="التصنيف غير موجود")

    # characters limit from settings
    max_chars = 3
    s = await db.settings.find_one({"key": "characters.max_count"}, {"_id": 0})
    if s and isinstance(s.get("value"), (int, float)):
        max_chars = int(s["value"])
    if len(data.get("characters", [])) > max_chars:
        raise HTTPException(status_code=400, detail=f"الحد الأقصى للشخصيات هو {max_chars}")

    order_id = str(uuid.uuid4())
    enriched = await _enrich(data)
    prompt = build_prompt(data, enriched)

    doc = {
        "id": order_id,
        "user_id": current["id"],
        "data": data,
        "enriched": enriched,
        "status": OrderStatus.PENDING.value,
        "admin_note": None,
        "ai_prompt_snapshot": prompt,
        "prompt_edited": False,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.orders.insert_one(doc)
    # clear server draft
    await db.drafts.delete_one({"user_id": current["id"]})
    doc.pop("_id", None)
    return doc


def _summary(o: dict) -> dict:
    e = o.get("enriched", {}) or {}
    child = (o.get("data") or {}).get("child", {})
    return {
        "id": o["id"],
        "user_id": o.get("user_id"),
        "status": o.get("status"),
        "status_ar": ORDER_STATUS_AR.get(o.get("status"), o.get("status")),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
        "child_name": child.get("name"),
        "child_age": child.get("age"),
        "child_gender": child.get("gender"),
        "category_name": e.get("category_name"),
        "subcategory_name": e.get("subcategory_name"),
        "type_name": e.get("type_name"),
    }


@router.get("")
async def my_orders(current=Depends(get_current_user)):
    items = await db.orders.find(
        {"user_id": current["id"]}, {"_id": 0}
    ).sort("created_at", -1).to_list(200)
    return [_summary(o) for o in items]


@router.get("/{order_id}")
async def order_detail(order_id: str, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    o["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    return o
