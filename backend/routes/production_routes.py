"""Production planning routes — user + admin endpoints for Phase 5.

Flow:
  scenario_selected -> ready_for_ai -> (auto) production_planning -> production_ready
  User views summary -> approves -> production_approved -> (Phase 6: generating)
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from db import db
from auth import get_current_user, require_admin
from models import OrderStatus, ORDER_STATUS_AR, SceneEdit, BookPageEdit, CharacterProfileEdit
from services.production_service import generate_production_plan, build_docs
from services.progress_service import compute_pipeline_progress

MAX_USER_PRODUCTION_REGENERATIONS = 1

user_router = APIRouter(prefix="/orders", tags=["production-user"])
admin_router = APIRouter(prefix="/admin", tags=["production-admin"], dependencies=[Depends(require_admin)])


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------- Background task ----------------
async def run_production_generation(order_id: str, run_id: str):
    """Generate a new production plan in background, archiving any previous plans."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    scenario = order.get("selected_scenario_snapshot")
    duration = order.get("duration") or {}
    # Phase D.5 — pick a concrete target within the bucket range. For new
    # orders `scene_target` is already bucket-aligned. If the selected
    # scenario suggested an estimated_scene_count and it lies inside the
    # bucket range, honour it; otherwise fall back to scene_target.
    base_target = int(duration.get("scene_target") or 6)
    target_scenes = base_target
    est = (scenario or {}).get("estimated_scene_count")
    mn = duration.get("scene_target_min")
    mx = duration.get("scene_target_max")
    if isinstance(est, int) and isinstance(mn, int) and isinstance(mx, int) and mn <= est <= mx:
        target_scenes = est
    if not scenario:
        await _append_status(order_id, order.get("status"), OrderStatus.FAILED.value, "system",
                             reason="production: no selected_scenario_snapshot")
        return

    try:
        payload, source, err = await generate_production_plan(order, scenario, target_scenes)
        docs = build_docs(order, payload, run_id, source)

        # Archive prior docs (keep history)
        await db.production_plans.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})
        await db.scene_plans.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})
        await db.book_pages.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})
        await db.character_profiles.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})

        # Insert new docs
        await db.production_plans.insert_one(docs["plan"])
        if docs["scenes"]:
            await db.scene_plans.insert_many(docs["scenes"])
        if docs["book_pages"]:
            await db.book_pages.insert_many(docs["book_pages"])
        if docs["character_profiles"]:
            await db.character_profiles.insert_many(docs["character_profiles"])

        # Update order
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "production_plan_id": docs["plan"]["id"],
                "production_plan_snapshot": {
                    "plan_id": docs["plan"]["id"],
                    "run_id": run_id,
                    "source": source,
                    "target_scene_count": docs["plan"]["target_scene_count"],
                    "generated_at": _now(),
                },
                "production_generation": {
                    "run_id": run_id,
                    "source": source,
                    "error": err,
                    "completed_at": _now(),
                },
                "production_approved": False,
                "production_approved_at": None,
                "updated_at": _now(),
            }},
        )
        await _append_status(order_id, order.get("status"), OrderStatus.PRODUCTION_READY.value, "system",
                             reason=f"production plan via {source} (run {run_id[:8]})")
    except Exception as e:
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"production_generation": {"run_id": run_id, "source": "error", "error": str(e), "completed_at": _now()}}},
        )
        await _append_status(order_id, order.get("status"), OrderStatus.FAILED.value, "system",
                             reason=f"production error: {e}")


async def _append_status(order_id, from_status, to_status, by, actor_id=None, reason=None):
    entry = {"from": from_status, "to": to_status, "at": _now(),
             "by": by, "actor_id": actor_id, "reason": reason}
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": to_status, "updated_at": _now()},
         "$push": {"status_history": entry}},
    )


async def trigger_production_planning(order_id: str, background: BackgroundTasks):
    """Called from order_routes after ready_for_ai transitions."""
    run_id = str(uuid.uuid4())
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"production_generation": {"run_id": run_id, "source": "pending", "error": None, "started_at": _now()}}},
    )
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "status": 1})
    await _append_status(order_id, (o or {}).get("status"), OrderStatus.PRODUCTION_PLANNING.value, "system",
                         reason="auto after ready_for_ai")
    background.add_task(run_production_generation, order_id, run_id)


# ---------------- User endpoints ----------------
def _user_summary(plan: dict | None, order: dict) -> dict | None:
    if not plan:
        return None
    return {
        "plan_id": plan["id"],
        "title": plan.get("title"),
        "story_summary": plan.get("story_summary"),
        "main_message": plan.get("main_message"),
        "target_scene_count": plan.get("target_scene_count"),
        "estimated_image_count": plan.get("estimated_image_count"),
        "duration_label": plan.get("duration_label"),
        "duration_seconds": plan.get("duration_seconds"),
        "audio_background": plan.get("audio_background") or {"mode": "music"},
        "safety_check": plan.get("safety_check"),
        "generated_at": (order.get("production_plan_snapshot") or {}).get("generated_at"),
    }


@user_router.get("/{order_id}/production-summary")
async def get_production_summary(order_id: str, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    plan = None
    if order.get("production_plan_id"):
        plan = await db.production_plans.find_one(
            {"id": order["production_plan_id"]}, {"_id": 0, "ai_plan_snapshot_json": 0}
        )
    used = int(order.get("production_regeneration_count", 0))
    progress = await compute_pipeline_progress(order)
    # Only surface the plan summary when the plan actually exists; this avoids
    # the race where the status flips to production_ready before the documents
    # are written.
    plan_is_live = bool(plan) and not plan.get("is_archived", False)
    status = order.get("status")
    effective_status = status
    if status == OrderStatus.PRODUCTION_READY.value and not plan_is_live:
        # Plan not yet visible — show planning UI until next poll.
        effective_status = OrderStatus.PRODUCTION_PLANNING.value
    return {
        "status": effective_status,
        "raw_status": status,
        "status_ar": ORDER_STATUS_AR.get(effective_status, effective_status),
        "summary": _user_summary(plan, order) if plan_is_live else None,
        "production_approved": bool(order.get("production_approved", False)),
        "production_approved_at": order.get("production_approved_at"),
        "production_regeneration_count": used,
        "max_user_production_regenerations": MAX_USER_PRODUCTION_REGENERATIONS,
        "production_regenerations_remaining": max(0, MAX_USER_PRODUCTION_REGENERATIONS - used),
        "progress": progress,
    }


@user_router.post("/{order_id}/production/approve")
async def user_approve_production(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if order.get("status") != OrderStatus.PRODUCTION_READY.value:
        raise HTTPException(status_code=400, detail="خطة الإنتاج ليست جاهزة بعد")
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"production_approved": True, "production_approved_at": _now(), "updated_at": _now()}},
    )
    await _append_status(order_id, order.get("status"), OrderStatus.PRODUCTION_APPROVED.value, "user",
                         actor_id=current["id"], reason="user approved production plan")
    # Trigger asset generation pipeline (phase 6A)
    from routes.media_routes import trigger_asset_generation
    run_id = await trigger_asset_generation(order_id, background)
    return {"ok": True, "asset_run_id": run_id}


@user_router.post("/{order_id}/production/regenerate")
async def user_regenerate_production(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if order.get("status") == OrderStatus.PRODUCTION_APPROVED.value or \
       order.get("status") in (OrderStatus.GENERATING.value, OrderStatus.COMPLETED.value):
        raise HTTPException(status_code=400, detail="لا يمكن إعادة التوليد بعد بدء الإنتاج")
    used = int(order.get("production_regeneration_count", 0))
    if used >= MAX_USER_PRODUCTION_REGENERATIONS:
        raise HTTPException(
            status_code=429,
            detail="لقد استخدمت محاولة إعادة توليد خطة الإنتاج المتاحة.",
        )
    run_id = str(uuid.uuid4())
    await db.orders.update_one(
        {"id": order_id},
        {"$inc": {"production_regeneration_count": 1},
         "$set": {"production_generation": {"run_id": run_id, "source": "pending", "error": None, "started_at": _now()}}},
    )
    await _append_status(order_id, order.get("status"), OrderStatus.PRODUCTION_PLANNING.value, "user",
                         actor_id=current["id"], reason=f"user regenerate production ({used + 1}/{MAX_USER_PRODUCTION_REGENERATIONS})")
    background.add_task(run_production_generation, order_id, run_id)
    return {"ok": True, "run_id": run_id, "remaining": MAX_USER_PRODUCTION_REGENERATIONS - used - 1}


# ---------------- Admin endpoints ----------------
@admin_router.get("/orders/{order_id}/production")
async def admin_get_production(order_id: str):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    plan = None
    if order.get("production_plan_id"):
        plan = await db.production_plans.find_one({"id": order["production_plan_id"]}, {"_id": 0})
    scenes = await db.scene_plans.find(
        {"order_id": order_id, "is_archived": False}, {"_id": 0}
    ).sort("scene_index", 1).to_list(50)
    pages = await db.book_pages.find(
        {"order_id": order_id, "is_archived": False}, {"_id": 0}
    ).sort("page_number", 1).to_list(50)
    characters = await db.character_profiles.find(
        {"order_id": order_id, "is_archived": False}, {"_id": 0}
    ).to_list(50)
    used = int(order.get("production_regeneration_count", 0))
    return {
        "order_id": order_id,
        "status": order.get("status"),
        "status_ar": ORDER_STATUS_AR.get(order.get("status"), order.get("status")),
        "production_approved": bool(order.get("production_approved", False)),
        "production_approved_at": order.get("production_approved_at"),
        "production_regeneration_count": used,
        "max_user_production_regenerations": MAX_USER_PRODUCTION_REGENERATIONS,
        "production_generation": order.get("production_generation"),
        "plan": plan,
        "scenes": scenes,
        "book_pages": pages,
        "character_profiles": characters,
    }


@admin_router.post("/orders/{order_id}/production/regenerate")
async def admin_regenerate_production(order_id: str, background: BackgroundTasks, admin=Depends(require_admin)):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    # Need a selected scenario
    if not order.get("selected_scenario_snapshot"):
        raise HTTPException(status_code=400, detail="لم يتم اختيار سيناريو بعد")
    run_id = str(uuid.uuid4())
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"production_generation": {"run_id": run_id, "source": "pending", "error": None, "started_at": _now()},
                  "production_approved": False, "production_approved_at": None}},
    )
    await _append_status(order_id, order.get("status"), OrderStatus.PRODUCTION_PLANNING.value, "admin",
                         actor_id=admin["id"], reason=f"admin regenerate production (run {run_id[:8]})")
    background.add_task(run_production_generation, order_id, run_id)
    return {"ok": True, "run_id": run_id}


@admin_router.patch("/scene-plans/{scene_id}")
async def admin_edit_scene(scene_id: str, payload: SceneEdit):
    updates: dict = {}
    body = payload.model_dump(exclude_unset=True)
    simple_map = {
        "narration_text": "narration_text",
        "book_text": "book_text",
        "visual_description": "visual_description",
    }
    for k, field in simple_map.items():
        if body.get(k) is not None:
            updates[field] = body[k]
    if body.get("image_prompt_text") is not None:
        updates["image_prompt.prompt_text"] = body["image_prompt_text"]
    if body.get("animation_motion_hint") is not None:
        updates["animation_prompt.motion_hint"] = body["animation_motion_hint"]
    if body.get("animation_camera_style") is not None:
        updates["animation_prompt.camera_style"] = body["animation_camera_style"]
    if "narration_text" in updates:
        wc = len([w for w in (updates["narration_text"] or "").split() if w])
        updates["word_count"] = wc

    if not updates:
        raise HTTPException(status_code=400, detail="لا توجد تحديثات")
    updates["edited_at"] = _now()
    updates["edited_by_admin"] = True

    res = await db.scene_plans.update_one({"id": scene_id}, {"$set": updates})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="المشهد غير موجود")
    return {"ok": True}


@admin_router.patch("/book-pages/{page_id}")
async def admin_edit_book_page(page_id: str, payload: BookPageEdit):
    body = payload.model_dump(exclude_unset=True)
    updates = {k: v for k, v in body.items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا توجد تحديثات")
    updates["edited_at"] = _now()
    updates["edited_by_admin"] = True
    res = await db.book_pages.update_one({"id": page_id}, {"$set": updates})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="الصفحة غير موجودة")
    return {"ok": True}


@admin_router.patch("/character-profiles/{cp_id}")
async def admin_edit_character(cp_id: str, payload: CharacterProfileEdit):
    body = payload.model_dump(exclude_unset=True)
    updates = {k: v for k, v in body.items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="لا توجد تحديثات")
    updates["edited_at"] = _now()
    updates["edited_by_admin"] = True
    res = await db.character_profiles.update_one({"id": cp_id}, {"$set": updates})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="الشخصية غير موجودة")
    return {"ok": True}
