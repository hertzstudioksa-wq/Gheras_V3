"""Admin endpoints — v2."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from db import db
from auth import require_admin
from models import (
    CategoryIn, SubcategoryIn, StoryOptionIn, OrderStatusUpdate, PromptUpdate,
    ContentBlockIn, PromptIn, PlanIn, SettingIn, UserUpdate, ORDER_STATUS_AR,
)
from prompt_engine import build_prompt
from services.scenario_service import generate_scenarios, build_scenario_docs
from routes.order_routes import append_status, run_scenario_generation

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------- Stats ----------
@router.get("/stats")
async def stats():
    users_count = await db.users.count_documents({})
    orders_count = await db.orders.count_documents({})
    pending = await db.orders.count_documents({"status": "pending"})
    in_review = await db.orders.count_documents({"status": "in_review"})
    completed = await db.orders.count_documents({"status": "completed"})
    categories = await db.categories.count_documents({})
    recent = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(5)
    for r in recent:
        d = (r.get("data") or {}).get("child", {})
        r["child_name"] = d.get("name")
    return {
        "users_count": users_count,
        "orders_count": orders_count,
        "pending_count": pending,
        "in_review_count": in_review,
        "completed_count": completed,
        "categories_count": categories,
        "recent_orders": recent,
    }


# ---------- Users ----------
@router.get("/users")
async def list_users():
    return await db.users.find({}, {"_id": 0, "hashed_password": 0}).sort("created_at", -1).to_list(500)


@router.patch("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate):
    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا توجد تحديثات")
    res = await db.users.update_one({"id": user_id}, {"$set": updates})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    return {"ok": True}


# ---------- Orders ----------
@router.get("/orders")
async def list_orders():
    items = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)
    for o in items:
        user = await db.users.find_one({"id": o.get("user_id")}, {"_id": 0, "email": 1, "full_name": 1})
        d = (o.get("data") or {}).get("child", {})
        o["user_email"] = user.get("email") if user else None
        o["user_name"] = user.get("full_name") if user else None
        o["child_name"] = d.get("name")
        o["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    return items


@router.get("/orders/{order_id}")
async def admin_order_detail(order_id: str):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    user = await db.users.find_one({"id": o.get("user_id")}, {"_id": 0, "email": 1, "full_name": 1})
    o["user_email"] = user.get("email") if user else None
    o["user_name"] = user.get("full_name") if user else None
    o["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    return o


@router.patch("/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: OrderStatusUpdate, admin=Depends(require_admin)):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "status": 1})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if payload.admin_note is not None:
        await db.orders.update_one({"id": order_id}, {"$set": {"admin_note": payload.admin_note}})
    await append_status(order_id, o.get("status"), payload.status.value, "admin", actor_id=admin["id"], reason=payload.admin_note)
    return {"ok": True}


@router.patch("/orders/{order_id}/prompt")
async def update_order_prompt(order_id: str, payload: PromptUpdate):
    res = await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "ai_prompt_snapshot": payload.ai_prompt_snapshot,
            "prompt_edited": True,
            "updated_at": _now(),
        }},
    )
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    return {"ok": True}


@router.post("/orders/{order_id}/regenerate-prompt")
async def regenerate_prompt(order_id: str):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    prompt = build_prompt(o.get("data", {}), o.get("enriched", {}))
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"ai_prompt_snapshot": prompt, "prompt_edited": False, "updated_at": _now()}},
    )
    return {"ok": True, "ai_prompt_snapshot": prompt}


# ---------- Admin Scenarios ----------
@router.get("/orders/{order_id}/scenarios")
async def admin_list_scenarios(order_id: str):
    o = await db.orders.find_one(
        {"id": order_id},
        {"_id": 0, "scenarios_generation": 1, "selected_scenario_id": 1,
         "status": 1, "current_scenario_batch_id": 1, "selected_scenario_batch_id": 1,
         "regeneration_count": 1, "max_regenerations": 1, "duration": 1},
    ) or {}
    items = await db.scenarios.find({"order_id": order_id}, {"_id": 0}).sort([("created_at", -1), ("scenario_index", 1)]).to_list(200)
    # Group by batch
    batches_map: dict[str, dict] = {}
    for s in items:
        bid = s.get("scenario_batch_id") or "legacy"
        if bid not in batches_map:
            batches_map[bid] = {
                "batch_id": bid,
                "is_current": bid == o.get("current_scenario_batch_id"),
                "created_at": s.get("created_at"),
                "source": s.get("source"),
                "scenarios": [],
            }
        # keep earliest created_at in batch (should be same)
        if s.get("created_at") and s["created_at"] < batches_map[bid]["created_at"]:
            batches_map[bid]["created_at"] = s["created_at"]
        batches_map[bid]["scenarios"].append(s)
    batches = sorted(batches_map.values(), key=lambda b: b.get("created_at") or "", reverse=True)
    for b in batches:
        b["scenarios"].sort(key=lambda x: x.get("scenario_index", 0))
    max_regen = o.get("max_regenerations", 3)
    used = o.get("regeneration_count", 0)
    return {
        "scenarios": items,  # kept for backwards compatibility (all scenarios)
        "batches": batches,
        "current_scenario_batch_id": o.get("current_scenario_batch_id"),
        "selected_scenario_batch_id": o.get("selected_scenario_batch_id"),
        "generation": o.get("scenarios_generation"),
        "selected_scenario_id": o.get("selected_scenario_id"),
        "status": o.get("status"),
        "regeneration_count": used,
        "max_regenerations": max_regen,
        "regenerations_remaining": max(0, max_regen - used),
        "duration": o.get("duration"),
    }


@router.post("/orders/{order_id}/scenarios/regenerate")
async def admin_regenerate_scenarios(order_id: str, background: BackgroundTasks, admin=Depends(require_admin)):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    # Admin bypass: always allowed, but still bumps counter
    new_batch_id = str(uuid.uuid4())
    used = int(o.get("regeneration_count", 0))
    max_regen = int(o.get("max_regenerations", 3))
    await db.orders.update_one(
        {"id": order_id},
        {
            "$set": {
                "current_scenario_batch_id": new_batch_id,
                "selected_scenario_id": None,
                "selected_scenario_snapshot": None,
            },
            "$inc": {"regeneration_count": 1},
        },
    )
    await append_status(
        order_id, o.get("status"), "scenarios_generating", "admin",
        actor_id=admin["id"],
        reason=f"admin regenerate ({used + 1}/{max_regen})" + (" — over limit" if used >= max_regen else ""),
    )
    background.add_task(run_scenario_generation, order_id, new_batch_id)
    return {"ok": True, "batch_id": new_batch_id, "regeneration_count": used + 1}


@router.delete("/orders/{order_id}/scenarios")
async def admin_delete_scenarios(order_id: str, admin=Depends(require_admin)):
    await db.scenarios.delete_many({"order_id": order_id})
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "selected_scenario_id": None,
            "selected_scenario_snapshot": None,
            "selected_scenario_batch_id": None,
        }},
    )
    return {"ok": True}


@router.post("/orders/{order_id}/scenarios/{scenario_id}/select")
async def admin_select_scenario(order_id: str, scenario_id: str, background: BackgroundTasks, admin=Depends(require_admin)):
    o = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    scenario = await db.scenarios.find_one({"id": scenario_id, "order_id": order_id}, {"_id": 0})
    if not scenario:
        raise HTTPException(status_code=404, detail="السيناريو غير موجود")
    # Admin is allowed to select any batch. If from an old batch, promote it to current.
    target_batch = scenario.get("scenario_batch_id")
    current_batch = o.get("current_scenario_batch_id")
    await db.scenarios.update_many({"order_id": order_id}, {"$set": {"is_selected": False}})
    await db.scenarios.update_one({"id": scenario_id}, {"$set": {"is_selected": True}})
    updates = {
        "selected_scenario_id": scenario_id,
        "selected_scenario_snapshot": scenario,
        "selected_scenario_batch_id": target_batch,
    }
    reason = f"admin selected {scenario.get('scenario_index')}"
    if target_batch and target_batch != current_batch:
        updates["current_scenario_batch_id"] = target_batch
        reason += f" (promoted batch {str(target_batch)[:8]})"
    await db.orders.update_one({"id": order_id}, {"$set": updates})
    await append_status(order_id, o.get("status"), "scenario_selected", "admin", actor_id=admin["id"], reason=reason)
    await append_status(order_id, "scenario_selected", "ready_for_ai", "system", reason="auto after admin selection")
    # Trigger production planning in background (phase 5)
    from routes.production_routes import trigger_production_planning
    await trigger_production_planning(order_id, background)
    return {"ok": True}


# ---------- Categories ----------
@router.post("/categories")
async def create_category(payload: CategoryIn):
    if await db.categories.find_one({"slug": payload.slug}):
        raise HTTPException(status_code=400, detail="هذا المعرّف مستخدم")
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now()}
    await db.categories.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/categories/{cat_id}")
async def update_category(cat_id: str, payload: CategoryIn):
    res = await db.categories.update_one({"id": cat_id}, {"$set": payload.model_dump()})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str):
    await db.subcategories.delete_many({"category_id": cat_id})
    res = await db.categories.delete_one({"id": cat_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


# ---------- Subcategories ----------
@router.get("/subcategories")
async def list_subcategories():
    return await db.subcategories.find({}, {"_id": 0}).sort("sort_order", 1).to_list(500)


@router.post("/subcategories")
async def create_subcategory(payload: SubcategoryIn):
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now()}
    await db.subcategories.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/subcategories/{sub_id}")
async def update_subcategory(sub_id: str, payload: SubcategoryIn):
    res = await db.subcategories.update_one({"id": sub_id}, {"$set": payload.model_dump()})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


@router.delete("/subcategories/{sub_id}")
async def delete_subcategory(sub_id: str):
    res = await db.subcategories.delete_one({"id": sub_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


# ---------- Story options (dynamic Step 5) ----------
@router.get("/story-options")
async def list_story_options():
    return await db.story_options.find({}, {"_id": 0}).sort([("kind", 1), ("sort_order", 1)]).to_list(500)


@router.post("/story-options")
async def create_story_option(payload: StoryOptionIn):
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now()}
    await db.story_options.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/story-options/{oid}")
async def update_story_option(oid: str, payload: StoryOptionIn):
    res = await db.story_options.update_one({"id": oid}, {"$set": payload.model_dump()})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


@router.delete("/story-options/{oid}")
async def delete_story_option(oid: str):
    res = await db.story_options.delete_one({"id": oid})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


# ---------- Content blocks ----------
@router.get("/content")
async def list_content():
    return await db.content.find({}, {"_id": 0}).sort("key", 1).to_list(500)


@router.put("/content")
async def upsert_content(payload: ContentBlockIn):
    data = {**payload.model_dump(), "updated_at": _now()}
    await db.content.update_one({"key": payload.key}, {"$set": data}, upsert=True)
    return {"ok": True}


@router.delete("/content/{key}")
async def delete_content(key: str):
    res = await db.content.delete_one({"key": key})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


# ---------- Prompts (global templates) ----------
@router.get("/prompts")
async def list_prompts():
    return await db.prompts.find({}, {"_id": 0}).sort("key", 1).to_list(100)


@router.post("/prompts")
async def create_prompt(payload: PromptIn):
    if await db.prompts.find_one({"key": payload.key}):
        raise HTTPException(status_code=400, detail="المفتاح مستخدم")
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now(), "updated_at": _now()}
    await db.prompts.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/prompts/{pid}")
async def update_prompt(pid: str, payload: PromptIn):
    data = {**payload.model_dump(), "updated_at": _now()}
    res = await db.prompts.update_one({"id": pid}, {"$set": data})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


@router.delete("/prompts/{pid}")
async def delete_prompt(pid: str):
    res = await db.prompts.delete_one({"id": pid})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


# ---------- Plans ----------
@router.get("/plans")
async def list_plans():
    return await db.plans.find({}, {"_id": 0}).sort("sort_order", 1).to_list(50)


@router.post("/plans")
async def create_plan(payload: PlanIn):
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now()}
    await db.plans.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.patch("/plans/{pid}")
async def update_plan(pid: str, payload: PlanIn):
    res = await db.plans.update_one({"id": pid}, {"$set": payload.model_dump()})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


@router.delete("/plans/{pid}")
async def delete_plan(pid: str):
    res = await db.plans.delete_one({"id": pid})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    return {"ok": True}


# ---------- Settings ----------
@router.get("/settings")
async def list_settings():
    return await db.settings.find({}, {"_id": 0}).to_list(500)


@router.put("/settings")
async def upsert_setting(payload: SettingIn):
    await db.settings.update_one(
        {"key": payload.key},
        {"$set": {"key": payload.key, "value": payload.value, "updated_at": _now()}},
        upsert=True,
    )
    return {"ok": True}
