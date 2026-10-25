"""Admin endpoints — v2."""
import re
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from db import db
from auth import require_admin
from models import (
    CategoryIn, SubcategoryIn, StoryOptionIn, OrderStatusUpdate, OrderNoteUpdate,
    ContentBlockIn, SettingIn, UserUpdate, ORDER_STATUS_AR,
)
from services.scenario_service import generate_scenarios, build_scenario_docs
from routes.order_routes import append_status, run_scenario_generation
from services.ai.comfy import DEFAULT_USD_PER_GPU_SECOND

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _audit_catalog(admin: dict, entity: str, entity_id: str | None, action: str, summary: str,
                         after: dict | None = None) -> None:
    from services.audit_service import record_audit
    await record_audit(entity_type=entity, entity_id=entity_id, action=action, actor_id=admin.get("id"),
                       actor_email=admin.get("email"), summary=summary, after=after)


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
async def list_users(q: str = "", role: str = "all", page: int = 1, limit: int = 25):
    limit = max(1, min(limit, 100))
    page = max(1, page)
    query: dict = {}
    if q.strip():
        query["$or"] = [{"email": _rx(q)}, {"full_name": _rx(q)}]
    if role in ("admin", "user"):
        query["role"] = role
    total = await db.users.count_documents(query)
    items = await db.users.find(query, {"_id": 0, "hashed_password": 0}).sort("created_at", -1) \
        .skip((page - 1) * limit).limit(limit).to_list(limit)
    counts = {}
    async for row in db.orders.aggregate([{"$match": {"user_id": {"$in": [u["id"] for u in items]}}},
                                          {"$group": {"_id": "$user_id", "n": {"$sum": 1}}}]):
        counts[row["_id"]] = row["n"]
    for u in items:
        u["orders_count"] = counts.get(u["id"], 0)
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.patch("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, admin=Depends(require_admin)):
    from services.audit_service import record_audit

    updates = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا توجد تحديثات")
    if user_id == admin["id"] and (updates.get("is_active") is False or
                                   ("role" in updates and str(getattr(updates["role"], "value", updates["role"])) != "admin")):
        raise HTTPException(status_code=400, detail="ما ينفعش تشيل صلاحية الأدمن من نفسك أو توقف حسابك")
    before = await db.users.find_one({"id": user_id}, {"_id": 0, "role": 1, "is_active": 1, "full_name": 1, "email": 1})
    if not before:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    if "role" in updates:
        updates["role"] = str(getattr(updates["role"], "value", updates["role"]))
    revoke = ("role" in updates and updates["role"] != before.get("role")) or \
        ("is_active" in updates and updates["is_active"] != before.get("is_active", True))
    await db.users.update_one({"id": user_id}, {"$set": updates, **({"$inc": {"token_version": 1}} if revoke else {})})
    await record_audit(entity_type="user", entity_id=user_id, action="user.update",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"تعديل المستخدم {before.get('email')}: {', '.join(sorted(updates))}",
                       before={k: before.get(k) for k in updates}, after=updates)
    return {"ok": True}


class NotifyTestIn(BaseModel):
    to: str = Field(min_length=5, max_length=200)


@router.post("/notify/test")
async def admin_notify_test(payload: NotifyTestIn):
    """Send one email now to check SMTP_URL."""
    from services.notify_service import smtp_config, test_connection
    if not await smtp_config():
        raise HTTPException(status_code=400, detail="سجّل SMTP_URL الأول من صفحة المفاتيح")
    return await test_connection(payload.to.strip())


@router.get("/notify/log")
async def admin_notify_log(limit: int = 30):
    from services.notify_service import smtp_config
    rows = await db.notifications.find({}, {"_id": 0}).sort("at", -1).to_list(max(1, min(limit, 100)))
    return {"rows": rows, "configured": bool(await smtp_config())}


class SafetyReviewIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    reason: str = Field(min_length=3, max_length=500)


@router.post("/orders/{order_id}/safety-review")
async def admin_safety_review(order_id: str, payload: SafetyReviewIn, admin=Depends(require_admin)):
    """A plan the model marked as sensitive: let the parent approve it, or stop it."""
    from services.audit_service import record_audit
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "status": 1, "safety_flag": 1})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if not o.get("safety_flag"):
        raise HTTPException(status_code=400, detail="الطلب ده مش محتاج مراجعة")
    review = {"decision": payload.decision, "reason": payload.reason, "by": admin.get("email"), "at": _now()}
    await db.orders.update_one({"id": order_id}, {"$set": {"safety_review": review}})
    if payload.decision == "reject" and o.get("status") == "production_ready":
        await append_status(order_id, o["status"], "failed", "admin", actor_id=admin["id"],
                            reason=f"safety review rejected: {payload.reason}")
    await record_audit(entity_type="order", entity_id=order_id, action="safety.review",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"مراجعة السلامة: {'موافقة' if payload.decision == 'approve' else 'رفض'} — {payload.reason}")
    return {"ok": True, "safety_review": review}


class DataDeleteIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/users/{user_id}/delete-data")
async def admin_delete_user_data(user_id: str, payload: DataDeleteIn, admin=Depends(require_admin)):
    """A parent asked (email/phone) to delete their data."""
    from services.privacy_service import delete_account
    try:
        return {"ok": True, **(await delete_account(user_id, actor=admin, reason=payload.reason))}
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------- Orders ----------
# Order status phases (mirrors frontend lib/orderStatus.js).
ORDER_PHASES = {
    "intake": ["draft", "pending", "in_review"],
    "scenarios": ["scenarios_generating", "scenarios_ready", "scenario_selected", "awaiting_payment"],
    "planning": ["ready_for_ai", "production_planning", "production_ready", "production_approved"],
    "media": ["assets_generating", "assets_ready", "assembling", "generating"],
    "delivered": ["delivered", "completed"],
    "failed": ["media_failed", "failed"],
}
ORDER_LIST_FIELDS = {"_id": 0, "id": 1, "user_id": 1, "status": 1, "created_at": 1, "updated_at": 1,
                     "data.child.name": 1, "data.delivery": 1, "duration.seconds": 1, "price_quote": 1,
                     "production_plan_id": 1, "engine_paused": 1, "feedback.rating": 1, "feedback.problem": 1,
                     "feedback.problem_status": 1, "payment.status": 1, "payment.amount_sar": 1}


def _rx(text: str) -> dict:
    return {"$regex": re.escape(text.strip()), "$options": "i"}


async def _add_cost_and_flags(items: list[dict]) -> None:
    """Per row: the actual cost so far and the margin (same numbers as the order's
    cost tab), and how many shots the automatic review flagged."""
    import asyncio
    from services.order_costs import actual_cost

    async def cost(o):
        try:
            c = await actual_cost(o)
            return {"cost_sar": c["total_sar"], "margin_pct": c["margin_pct"]}
        except Exception:  # noqa: BLE001 — a row without a cost still lists
            return {"cost_sar": None, "margin_pct": None}

    for o, c in zip(items, await asyncio.gather(*(cost(o) for o in items))):
        o.update(c)
    flagged = {r["_id"]: r["n"] async for r in db.shot_assets.aggregate([
        {"$match": {"order_id": {"$in": [o["id"] for o in items]},
                    "$or": [{"keyframe_review.ok": False}, {"clip_review.ok": False}]}},
        {"$group": {"_id": "$order_id", "n": {"$sum": 1}}},
    ])}
    for o in items:
        o["flagged_shots"] = flagged.get(o["id"], 0)


@router.get("/orders")
async def list_orders(q: str = "", phase: str = "all", page: int = 1, limit: int = 25):
    """Paged order list: search by child name, customer name/email or order id; filter by phase."""
    limit = max(1, min(limit, 100))
    page = max(1, page)
    base: dict = {}
    if q.strip():
        user_ids = [u["id"] async for u in db.users.find({"$or": [{"email": _rx(q)}, {"full_name": _rx(q)}]},
                                                           {"_id": 0, "id": 1})]
        base["$or"] = [{"data.child.name": _rx(q)}, {"id": {"$regex": "^" + re.escape(q.strip())}},
                       {"user_id": {"$in": user_ids}}]
    query = dict(base)
    if phase in ORDER_PHASES:
        query["status"] = {"$in": ORDER_PHASES[phase]}
    total = await db.orders.count_documents(query)
    items = await db.orders.find(query, ORDER_LIST_FIELDS).sort("created_at", -1) \
        .skip((page - 1) * limit).limit(limit).to_list(limit)
    users = {u["id"]: u async for u in db.users.find({"id": {"$in": list({o.get("user_id") for o in items})}},
                                                     {"_id": 0, "id": 1, "email": 1, "full_name": 1})}
    titles = {p["id"]: p.get("title") async for p in db.production_plans.find(
        {"id": {"$in": [o["production_plan_id"] for o in items if o.get("production_plan_id")]}},
        {"_id": 0, "id": 1, "title": 1})}
    for o in items:
        u = users.get(o.get("user_id")) or {}
        o["user_email"], o["user_name"] = u.get("email"), u.get("full_name")
        data = o.pop("data", {}) or {}
        o["child_name"] = (data.get("child") or {}).get("name")
        delivery = data.get("delivery") or {}
        o["output_type"] = delivery.get("output_type") or "both"
        o["video_tier"] = None if o["output_type"] == "pdf" else (delivery.get("video_tier") or "balanced")
        o["title"] = titles.get(o.get("production_plan_id"))
        o["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    await _add_cost_and_flags(items)
    # Phase counts for the filter chips (within the current search).
    counts = {k: 0 for k in ORDER_PHASES}
    async for row in db.orders.aggregate([{"$match": base}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]):
        for k, statuses in ORDER_PHASES.items():
            if row["_id"] in statuses:
                counts[k] += row["n"]
    return {"items": items, "total": total, "page": page, "limit": limit,
            "phase_counts": counts, "all_count": sum(counts.values())}


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


@router.post("/orders/{order_id}/feedback/resolve")
async def resolve_feedback_problem(order_id: str, admin=Depends(require_admin)):
    """The parent's problem report was handled (scene redone or refunded)."""
    res = await db.orders.update_one({"id": order_id, "feedback.problem": True},
                                     {"$set": {"feedback.problem_status": "resolved",
                                               "feedback.resolved_at": datetime.now(timezone.utc).isoformat(),
                                               "feedback.resolved_by": admin.get("email")}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="مفيش بلاغ مفتوح على الطلب ده")
    return {"ok": True}


@router.patch("/orders/{order_id}/status")
async def update_order_status(order_id: str, payload: OrderStatusUpdate, admin=Depends(require_admin)):
    """Manual status override: changes the label only (no production runs or
    stops). The reason goes into the status history and the audit log."""
    from services.audit_service import record_audit

    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "status": 1})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    reason = (payload.reason or "").strip() or None
    if payload.admin_note is not None and payload.reason is None:  # old clients sent the note as the reason
        await db.orders.update_one({"id": order_id}, {"$set": {"admin_note": payload.admin_note}})
        reason = payload.admin_note
    await append_status(order_id, o.get("status"), payload.status.value, "admin", actor_id=admin["id"], reason=reason)
    await record_audit(entity_type="order", entity_id=order_id, action="order.status_override",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"تغيير حالة الطلب يدوياً: {o.get('status')} → {payload.status.value}"
                               + (f" — {reason}" if reason else ""),
                       before={"status": o.get("status")}, after={"status": payload.status.value})
    return {"ok": True}


@router.patch("/orders/{order_id}/note")
async def update_order_note(order_id: str, payload: OrderNoteUpdate):
    res = await db.orders.update_one({"id": order_id}, {"$set": {"admin_note": payload.admin_note.strip() or None,
                                                                 "updated_at": _now()}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    return {"ok": True}


# ---------- Admin Scenarios ----------
@router.get("/orders/{order_id}/scenarios")
async def admin_list_scenarios(order_id: str):
    o = await db.orders.find_one(
        {"id": order_id},
        {"_id": 0, "scenarios_generation": 1, "selected_scenario_id": 1,
         "status": 1, "current_scenario_batch_id": 1, "selected_scenario_batch_id": 1,
         "regeneration_count": 1, "max_regenerations": 1, "duration": 1, "data": 1},
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
        "output_type": ((o.get("data") or {}).get("delivery") or {}).get("output_type") or "both",
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
    # M6 — same payment gate as the parent's own selection (waive it from the order page).
    from services.payment_service import gate_production
    return {"ok": True, **(await gate_production(order_id, background))}


# ---------- Categories ----------
@router.get("/categories")
async def list_categories_admin():
    """Every category with every subcategory, including inactive ones and the
    admin prompt direction the public endpoint hides."""
    cats = await db.categories.find({}, {"_id": 0}).sort("sort_order", 1).to_list(200)
    subs = await db.subcategories.find({}, {"_id": 0}).sort("sort_order", 1).to_list(1000)
    for c in cats:
        c["subcategories"] = [s for s in subs if s.get("category_id") == c["id"]]
    return cats


@router.post("/categories")
async def create_category(payload: CategoryIn, admin=Depends(require_admin)):
    if await db.categories.find_one({"slug": payload.slug}):
        raise HTTPException(status_code=400, detail="هذا المعرّف مستخدم")
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now()}
    await db.categories.insert_one(doc)
    doc.pop("_id", None)
    await _audit_catalog(admin, "category", doc["id"], "catalog.create", f"تصنيف جديد: {payload.name_ar}")
    return doc


@router.patch("/categories/{cat_id}")
async def update_category(cat_id: str, payload: CategoryIn, admin=Depends(require_admin)):
    patch = payload.model_dump(exclude_unset=True)
    res = await db.categories.update_one({"id": cat_id}, {"$set": patch})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await _audit_catalog(admin, "category", cat_id, "catalog.update", f"تعديل تصنيف {payload.name_ar}: {', '.join(sorted(patch))}", patch)
    return {"ok": True}


async def _refuse_if_used(field: str, value: str, what: str) -> None:
    """Orders keep pointing at catalog items; deleting one that is in use breaks
    those orders' labels and prompts, so offer deactivation instead."""
    n = await db.orders.count_documents({field: value})
    if n:
        raise HTTPException(status_code=400, detail=f"{what} مستخدم في {n} طلب — أوقفه بدل ما تمسحه")


@router.delete("/categories/{cat_id}")
async def delete_category(cat_id: str, admin=Depends(require_admin)):
    from services.audit_service import record_audit

    await _refuse_if_used("data.goal.category_id", cat_id, "التصنيف")
    sub_ids = [s["id"] async for s in db.subcategories.find({"category_id": cat_id}, {"_id": 0, "id": 1})]
    if sub_ids and await db.orders.count_documents({"data.goal.subcategory_id": {"$in": sub_ids}}):
        raise HTTPException(status_code=400, detail="فيه موضوع من مواضيع التصنيف ده مستخدم في طلبات — أوقف التصنيف بدل ما تمسحه")
    cat = await db.categories.find_one({"id": cat_id}, {"_id": 0, "name_ar": 1})
    await db.subcategories.delete_many({"category_id": cat_id})
    res = await db.categories.delete_one({"id": cat_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await record_audit(entity_type="category", entity_id=cat_id, action="category.delete",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"مسح تصنيف {(cat or {}).get('name_ar')} و{len(sub_ids)} موضوع")
    return {"ok": True}


# ---------- Subcategories ----------
@router.get("/subcategories")
async def list_subcategories():
    return await db.subcategories.find({}, {"_id": 0}).sort("sort_order", 1).to_list(500)


@router.post("/subcategories")
async def create_subcategory(payload: SubcategoryIn, admin=Depends(require_admin)):
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now()}
    await db.subcategories.insert_one(doc)
    doc.pop("_id", None)
    await _audit_catalog(admin, "subcategory", doc["id"], "catalog.create", f"موضوع جديد: {payload.name_ar}")
    return doc


@router.patch("/subcategories/{sub_id}")
async def update_subcategory(sub_id: str, payload: SubcategoryIn, admin=Depends(require_admin)):
    patch = payload.model_dump(exclude_unset=True)
    res = await db.subcategories.update_one({"id": sub_id}, {"$set": patch})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await _audit_catalog(admin, "subcategory", sub_id, "catalog.update", f"تعديل موضوع {payload.name_ar}: {', '.join(sorted(patch))}", patch)
    return {"ok": True}


@router.delete("/subcategories/{sub_id}")
async def delete_subcategory(sub_id: str, admin=Depends(require_admin)):
    await _refuse_if_used("data.goal.subcategory_id", sub_id, "الموضوع")
    res = await db.subcategories.delete_one({"id": sub_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await _audit_catalog(admin, "subcategory", sub_id, "catalog.delete", "مسح موضوع")
    return {"ok": True}


# ---------- Story options (dynamic Step 5) ----------
@router.get("/story-options")
async def list_story_options():
    return await db.story_options.find({}, {"_id": 0}).sort([("kind", 1), ("sort_order", 1)]).to_list(500)


@router.post("/story-options")
async def create_story_option(payload: StoryOptionIn, admin=Depends(require_admin)):
    doc = {"id": str(uuid.uuid4()), **payload.model_dump(), "created_at": _now()}
    await db.story_options.insert_one(doc)
    doc.pop("_id", None)
    await _audit_catalog(admin, "story_option", doc["id"], "catalog.create", f"خيار قصة جديد ({payload.kind}): {payload.name_ar}")
    return doc


@router.patch("/story-options/{oid}")
async def update_story_option(oid: str, payload: StoryOptionIn, admin=Depends(require_admin)):
    patch = payload.model_dump(exclude_unset=True)
    res = await db.story_options.update_one({"id": oid}, {"$set": patch})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await _audit_catalog(admin, "story_option", oid, "catalog.update", f"تعديل خيار {payload.name_ar}: {', '.join(sorted(patch))}", patch)
    return {"ok": True}


@router.delete("/story-options/{oid}")
async def delete_story_option(oid: str, admin=Depends(require_admin)):
    for field in ("type_id", "tone_id", "setting_id", "language_id", "voice_id"):
        await _refuse_if_used(f"data.style.{field}", oid, "الخيار")
    res = await db.story_options.delete_one({"id": oid})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await _audit_catalog(admin, "story_option", oid, "catalog.delete", "مسح خيار قصة")
    return {"ok": True}


# ---------- Content blocks ----------
@router.get("/content")
async def list_content():
    return await db.content.find({}, {"_id": 0}).sort("key", 1).to_list(500)


@router.put("/content")
async def upsert_content(payload: ContentBlockIn, admin=Depends(require_admin)):
    before = await db.content.find_one({"key": payload.key}, {"_id": 0, "value": 1})
    data = {**payload.model_dump(), "updated_at": _now()}
    await db.content.update_one({"key": payload.key}, {"$set": data}, upsert=True)
    from services.audit_service import record_audit
    await record_audit(entity_type="content", entity_id=payload.key, action="content.update",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"تعديل نص الموقع: {payload.key}", before=before, after={"value": payload.value})
    return {"ok": True}


@router.delete("/content/{key}")
async def delete_content(key: str, admin=Depends(require_admin)):
    res = await db.content.delete_one({"key": key})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await _audit_catalog(admin, "content", key, "content.delete", f"مسح نص الموقع: {key}")
    return {"ok": True}


# ---------- Settings ----------
# The settings the code actually reads (audit AF-15). Anything else in the
# collection is an old key nothing uses; the page lists those for cleanup.
KNOWN_SETTINGS = {
    "characters.max_count": {
        "label_ar": "أقصى عدد للشخصيات الإضافية في القصة",
        "description_ar": "عدد الأقارب أو الأصدقاء اللي ولي الأمر يقدر يضيفهم في خطوة الشخصيات.",
        "type": "int", "min": 0, "max": 6, "default": 3, "public": True,
    },
    "notify.enabled": {
        "label_ar": "إيميلات لأولياء الأمور",
        "description_ar": "خطة جاهزة للاعتماد، القصة جاهزة، أو حصلت مشكلة. بتشتغل لما SMTP_URL يتسجّل في صفحة المفاتيح.",
        "type": "bool", "default": True,
    },
    "notify.from_email": {
        "label_ar": "الإيميل اللي بنبعت منه",
        "description_ar": "فاضي = إيميل حساب SMTP نفسه.",
        "type": "email", "default": "",
    },
    "notify.ops_email": {
        "label_ar": "إيميل فريق التشغيل",
        "description_ar": "بيوصله تنبيه لما طلب يقع أو خطة تحتاج مراجعة سلامة. فاضي = من غير تنبيهات.",
        "type": "email", "default": "",
    },
    "generation.max_parallel_orders": {
        "label_ar": "أقصى عدد قصص بتتولّد في نفس الوقت",
        "description_ar": "الزيادة بتستنى في طابور حسب ترتيب الاعتماد، وولي الأمر بيشوف دوره. "
                          "لما صور اللقطات أو المقاطع على ComfyUI، الحد الفعلي = خانات Comfy + 1 لو أقل من الرقم ده "
                          "(أكتر من كده بيداخل القصص في بعض وكلها تخلص متأخر). ارفعه حسب حد fal وحجم السيرفر.",
        "type": "int", "min": 1, "max": 200, "default": 6,
    },
    "render.max_parallel": {
        "label_ar": "أقصى عدد تجميع فيديو/كتاب في نفس الوقت",
        "description_ar": "كل خانة بتاكل حوالي 1.3 جيجا رام (ffmpeg للفيديو أو Chromium للكتاب). 1 آمن مع حد الذاكرة 1.5 جيجا؛ "
                          "2 لسيرفر منفصل 8 vCPU / 16 جيجا.",
        "type": "int", "min": 1, "max": 16, "default": 1,
    },
    "retention.intermediate_days": {
        "label_ar": "مسح الملفات الوسيطة بعد التسليم بكام يوم",
        "description_ar": "المقاطع وصور اللقطات وتسجيلات اللقطات والنسخ القديمة (حوالي 85% من مساحة القصة). "
                          "الفيديو النهائي والكتاب والغلاف والشيتات بيفضلوا. 0 = مقفول. المقترح 30 (أكتر من مهلة الـ 14 يوم لإعادة لقطة).",
        "type": "int", "min": 0, "max": 365, "default": 0,
    },
    "clip_review.enabled": {
        "label_ar": "مراجعة آلية لكل لقطة",
        "description_ar": "موديل رؤية رخيص بيبص على صورة البداية والمقطع: شخصية متكررة، جسم بيخترق حاجة، كتابة. "
                          "اللقطة اللي فيها غلط بتتعاد مرة واحدة تلقائي (~$0.03 للقصة + تكلفة اللقطة اللي بتتعاد).",
        "type": "bool", "default": True,
    },
    "comfy.max_concurrent": {
        "label_ar": "عدد طلبات Comfy في نفس الوقت",
        "description_ar": "كام صورة أو مقطع يتبعتوا لـ Comfy Cloud مع بعض لكل الطلبات. باقة Standard بتشغّل طلب "
                          "واحد بس؛ زوّده لو الباقة بتسمح بأكتر. التغيير بيسري في ثواني من غير restart.",
        "type": "int", "min": 1, "max": 8, "default": 1,
    },
    "comfy.kling_rescue": {
        "label_ar": "Kling كشبكة أمان لمقاطع Comfy",
        "description_ar": "مقفول افتراضياً عشان التكلفة تفضل زي التسعير. وهو مقفول: المقطع اللي المراجعة بتعلّم عليه "
                          "بيتعاد بحركة أهدى، وبعدين مرة كمان بـ seed جديد (≈ $0.15)، ويتسلّم أحسن نسخة. لو اتفتح: بعد "
                          "الحركة الأهدى اللقطة دي بس بتترندر بـ Kling الفاخر (≈ $0.11 للثانية، 4–5 أضعاف Wan).",
        "type": "bool", "default": False,
    },
    "comfy.usd_per_gpu_second": {
        "label_ar": "سعر ثانية GPU على Comfy (دولار)",
        "description_ar": "التكلفة الفعلية لصور اللقطات ومقاطع Wan على Comfy = ثواني GPU × السعر ده. الافتراضي 0.0019 = "
                          "credits الباقة (0.39 credit للثانية، ~211 credit للدولار). على API deployment ≈ 0.00097. "
                          "مش بيغيّر سعر البيع (ده من الكتالوج).",
        "type": "float", "min": 0.0001, "max": 0.05, "step": 0.0001, "default": DEFAULT_USD_PER_GPU_SECOND,
    },
}


@router.get("/settings")
async def list_settings():
    stored = {s["key"]: s for s in await db.settings.find({}, {"_id": 0}).to_list(500)}
    items = [{"key": k, **meta, "value": (stored.get(k) or {}).get("value", meta["default"]),
              "updated_at": (stored.get(k) or {}).get("updated_at")} for k, meta in KNOWN_SETTINGS.items()]
    unused = [{"key": k, "value": v.get("value")} for k, v in stored.items() if k not in KNOWN_SETTINGS]
    return {"items": items, "unused": unused}


@router.put("/settings")
async def upsert_setting(payload: SettingIn, admin=Depends(require_admin)):
    from services.audit_service import record_audit

    meta = KNOWN_SETTINGS.get(payload.key)
    if not meta:
        raise HTTPException(status_code=400, detail="إعداد غير معروف")
    value = payload.value
    if meta["type"] == "bool":
        if not isinstance(value, bool):
            raise HTTPException(status_code=400, detail="القيمة لازم تكون تشغيل أو إيقاف")
    elif meta["type"] == "email":
        value = str(value or "").strip()
        if value and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise HTTPException(status_code=400, detail="الإيميل مش مظبوط")
    if meta["type"] in ("int", "float"):
        try:
            value = int(value) if meta["type"] == "int" else float(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="القيمة لازم تكون رقم صحيح" if meta["type"] == "int"
                                else "القيمة لازم تكون رقم")
        if not meta["min"] <= value <= meta["max"]:
            raise HTTPException(status_code=400, detail=f"القيمة لازم تكون بين {meta['min']} و{meta['max']}")
    before = await db.settings.find_one({"key": payload.key}, {"_id": 0, "value": 1})
    await db.settings.update_one(
        {"key": payload.key},
        {"$set": {"key": payload.key, "value": value, "updated_at": _now()}},
        upsert=True,
    )
    await record_audit(entity_type="setting", entity_id=payload.key, action="setting.update",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"{meta['label_ar']}: {(before or {}).get('value')} → {value}",
                       before=before, after={"value": value})
    return {"ok": True}


@router.delete("/settings/{key}")
async def delete_unused_setting(key: str, admin=Depends(require_admin)):
    """Remove an old key nothing reads (known settings can't be deleted)."""
    from services.audit_service import record_audit

    if key in KNOWN_SETTINGS:
        raise HTTPException(status_code=400, detail="الإعداد ده مستخدم وما ينفعش يتمسح")
    res = await db.settings.delete_one({"key": key})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="غير موجود")
    await record_audit(entity_type="setting", entity_id=key, action="setting.delete",
                       actor_id=admin.get("id"), actor_email=admin.get("email"), summary=f"مسح إعداد قديم: {key}")
    return {"ok": True}
