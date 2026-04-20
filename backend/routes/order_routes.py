"""Order endpoints — v3 with scenarios orchestration."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from db import db
from auth import get_current_user
from models import OrderCreate, OrderStatus, ORDER_STATUS_AR
from prompt_engine import build_prompt
from services.scenario_service import generate_scenarios, build_scenario_docs

router = APIRouter(prefix="/orders", tags=["orders"])


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _enrich(data: dict) -> dict:
    goal = data.get("goal", {}) or {}
    style = data.get("style", {}) or {}
    out: dict = {}
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


async def append_status(order_id: str, from_status: str | None, to_status: str, by: str, actor_id: str | None = None, reason: str | None = None):
    entry = {
        "from": from_status,
        "to": to_status,
        "at": _now(),
        "by": by,
        "actor_id": actor_id,
        "reason": reason,
    }
    await db.orders.update_one(
        {"id": order_id},
        {
            "$set": {"status": to_status, "updated_at": _now()},
            "$push": {"status_history": entry},
        },
    )


async def run_scenario_generation(order_id: str):
    """Background task: generate scenarios, persist, and advance status."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    try:
        items, source, err = await generate_scenarios(order)
        docs = build_scenario_docs(order_id, items)
        # replace any existing
        await db.scenarios.delete_many({"order_id": order_id})
        await db.scenarios.insert_many(docs)
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "scenarios_generation": {
                    "source": source,
                    "error": err,
                    "completed_at": _now(),
                },
            }},
        )
        await append_status(order_id, order.get("status"), OrderStatus.SCENARIOS_READY.value, "system", reason=f"via {source}")
    except Exception as e:
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "scenarios_generation": {"source": "error", "error": str(e), "completed_at": _now()},
            }},
        )
        await append_status(order_id, order.get("status"), OrderStatus.FAILED.value, "system", reason=f"scenarios error: {e}")


@router.post("")
async def create_order(payload: OrderCreate, background: BackgroundTasks, current=Depends(get_current_user)):
    data = payload.data.model_dump()
    if not await db.categories.find_one({"id": data["goal"]["category_id"], "is_active": True}):
        raise HTTPException(status_code=400, detail="التصنيف غير موجود")

    max_chars = 3
    s = await db.settings.find_one({"key": "characters.max_count"}, {"_id": 0})
    if s and isinstance(s.get("value"), (int, float)):
        max_chars = int(s["value"])
    if len(data.get("characters", [])) > max_chars:
        raise HTTPException(status_code=400, detail=f"الحد الأقصى للشخصيات هو {max_chars}")

    order_id = str(uuid.uuid4())
    enriched = await _enrich(data)
    prompt = build_prompt(data, enriched)

    initial_history = [
        {"from": None, "to": OrderStatus.PENDING.value, "at": _now(), "by": "user", "actor_id": current["id"], "reason": "submit"},
    ]
    doc = {
        "id": order_id,
        "user_id": current["id"],
        "data": data,
        "enriched": enriched,
        "status": OrderStatus.PENDING.value,
        "admin_note": None,
        "ai_prompt_snapshot": prompt,
        "prompt_edited": False,
        "selected_scenario_id": None,
        "selected_scenario_snapshot": None,
        "scenarios_generation": None,
        "status_history": initial_history,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.orders.insert_one(doc)
    await db.drafts.delete_one({"user_id": current["id"]})

    # transition to scenarios_generating and kick background
    await append_status(order_id, OrderStatus.PENDING.value, OrderStatus.SCENARIOS_GENERATING.value, "system", reason="auto")
    background.add_task(run_scenario_generation, order_id)

    fresh = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return fresh


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
        "selected_scenario_id": o.get("selected_scenario_id"),
    }


@router.get("")
async def my_orders(current=Depends(get_current_user)):
    items = await db.orders.find({"user_id": current["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [_summary(o) for o in items]


@router.get("/{order_id}")
async def order_detail(order_id: str, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    o["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    return o


# ---------- Scenarios (user-facing) ----------
@router.get("/{order_id}/scenarios")
async def list_scenarios(order_id: str, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0, "status": 1, "scenarios_generation": 1, "selected_scenario_id": 1})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    items = await db.scenarios.find({"order_id": order_id}, {"_id": 0}).sort("scenario_index", 1).to_list(10)
    return {
        "status": o.get("status"),
        "status_ar": ORDER_STATUS_AR.get(o.get("status"), o.get("status")),
        "generation": o.get("scenarios_generation"),
        "selected_scenario_id": o.get("selected_scenario_id"),
        "scenarios": items,
    }


@router.post("/{order_id}/scenarios/regenerate")
async def regenerate_scenarios(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if o.get("status") in (OrderStatus.GENERATING.value, OrderStatus.COMPLETED.value):
        raise HTTPException(status_code=400, detail="لا يمكن إعادة التوليد بعد بدء الإنتاج")
    await db.scenarios.delete_many({"order_id": order_id})
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"selected_scenario_id": None, "selected_scenario_snapshot": None}},
    )
    await append_status(order_id, o.get("status"), OrderStatus.SCENARIOS_GENERATING.value, "user", actor_id=current["id"], reason="regenerate")
    background.add_task(run_scenario_generation, order_id)
    return {"ok": True}


@router.post("/{order_id}/scenarios/{scenario_id}/select")
async def select_scenario(order_id: str, scenario_id: str, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if o.get("status") in (OrderStatus.GENERATING.value, OrderStatus.COMPLETED.value):
        raise HTTPException(status_code=400, detail="لا يمكن التعديل بعد بدء الإنتاج")
    scenario = await db.scenarios.find_one({"id": scenario_id, "order_id": order_id}, {"_id": 0})
    if not scenario:
        raise HTTPException(status_code=404, detail="السيناريو غير موجود")
    # unselect others, select this
    await db.scenarios.update_many({"order_id": order_id}, {"$set": {"is_selected": False}})
    await db.scenarios.update_one({"id": scenario_id}, {"$set": {"is_selected": True}})
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "selected_scenario_id": scenario_id,
            "selected_scenario_snapshot": scenario,
        }},
    )
    await append_status(order_id, o.get("status"), OrderStatus.SCENARIO_SELECTED.value, "user", actor_id=current["id"], reason=f"selected scenario {scenario.get('scenario_index')}")
    # auto-advance to ready_for_ai
    await append_status(order_id, OrderStatus.SCENARIO_SELECTED.value, OrderStatus.READY_FOR_AI.value, "system", reason="auto after selection")
    return {"ok": True}
