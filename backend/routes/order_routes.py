"""User order endpoints."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException

from db import db
from auth import get_current_user
from models import OrderCreate, Order, OrderStatus, ORDER_STATUS_AR

router = APIRouter(prefix="/orders", tags=["orders"])


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _build_ai_prompt_snapshot(order: dict) -> str:
    """Pre-compute the AI prompt so it's ready when AI generation is hooked in later."""
    prompt = await db.prompts.find_one({"key": "story.generate.master", "is_active": True}, {"_id": 0})
    if not prompt:
        return ""
    child = order.get("child_snapshot", {})
    category = await db.categories.find_one({"id": order.get("category_id")}, {"_id": 0})
    sub = None
    if order.get("subcategory_id"):
        sub = await db.subcategories.find_one({"id": order["subcategory_id"]}, {"_id": 0})
    style = await db.story_styles.find_one({"id": order.get("style_id")}, {"_id": 0})
    goal = (sub or {}).get("name_ar") or order.get("custom_goal") or (category or {}).get("name_ar") or ""
    values = {
        "style": (style or {}).get("name_ar", ""),
        "goal": goal,
        "child_name": child.get("name", ""),
        "child_age": child.get("age", ""),
        "child_gender": "ولد" if child.get("gender") == "male" else "بنت",
        "personality": child.get("personality") or "",
        "interests": child.get("interests") or "",
        "notes": order.get("notes") or "",
    }
    try:
        return prompt["template"].format(**values)
    except Exception:
        return prompt["template"]


@router.post("", response_model=Order)
async def create_order(payload: OrderCreate, current=Depends(get_current_user)):
    # validate refs
    if not await db.categories.find_one({"id": payload.category_id, "is_active": True}):
        raise HTTPException(status_code=400, detail="التصنيف غير موجود")
    if payload.subcategory_id:
        if not await db.subcategories.find_one({"id": payload.subcategory_id, "is_active": True}):
            raise HTTPException(status_code=400, detail="الموضوع الفرعي غير موجود")
    if not await db.story_styles.find_one({"id": payload.style_id, "is_active": True}):
        raise HTTPException(status_code=400, detail="أسلوب القصة غير موجود")

    order_id = str(uuid.uuid4())
    doc = {
        "id": order_id,
        "user_id": current["id"],
        "category_id": payload.category_id,
        "subcategory_id": payload.subcategory_id,
        "custom_goal": payload.custom_goal,
        "child_snapshot": payload.child.model_dump(),
        "personalization": payload.personalization,
        "style_id": payload.style_id,
        "notes": payload.notes,
        "status": OrderStatus.PENDING.value,
        "admin_note": None,
        "ai_prompt_snapshot": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    doc["ai_prompt_snapshot"] = await _build_ai_prompt_snapshot(doc)
    await db.orders.insert_one(doc)

    # also create child record
    await db.children.insert_one({
        "id": str(uuid.uuid4()),
        "user_id": current["id"],
        **payload.child.model_dump(),
        "created_at": _now(),
    })
    doc.pop("_id", None)
    return Order(**doc)


@router.get("")
async def my_orders(current=Depends(get_current_user)):
    orders = await db.orders.find({"user_id": current["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    # enrich with category/style names
    for o in orders:
        cat = await db.categories.find_one({"id": o.get("category_id")}, {"_id": 0, "name_ar": 1})
        style = await db.story_styles.find_one({"id": o.get("style_id")}, {"_id": 0, "name_ar": 1})
        sub = None
        if o.get("subcategory_id"):
            sub = await db.subcategories.find_one({"id": o["subcategory_id"]}, {"_id": 0, "name_ar": 1})
        o["category_name"] = cat.get("name_ar") if cat else None
        o["subcategory_name"] = sub.get("name_ar") if sub else None
        o["style_name"] = style.get("name_ar") if style else None
        o["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    return orders


@router.get("/{order_id}")
async def order_detail(order_id: str, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    cat = await db.categories.find_one({"id": o.get("category_id")}, {"_id": 0, "name_ar": 1})
    style = await db.story_styles.find_one({"id": o.get("style_id")}, {"_id": 0, "name_ar": 1})
    sub = None
    if o.get("subcategory_id"):
        sub = await db.subcategories.find_one({"id": o["subcategory_id"]}, {"_id": 0, "name_ar": 1})
    o["category_name"] = cat.get("name_ar") if cat else None
    o["subcategory_name"] = sub.get("name_ar") if sub else None
    o["style_name"] = style.get("name_ar") if style else None
    o["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    return o
