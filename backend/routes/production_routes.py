"""Production planning routes — user + admin endpoints for Phase 5.

Flow:
  scenario_selected -> ready_for_ai -> (auto) production_planning -> production_ready
  User views summary -> approves -> production_approved -> (Phase 6: generating)
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from db import db
from auth import get_current_user, require_admin
from models import OrderStatus, ORDER_STATUS_AR, SceneEdit, BookPageEdit, CharacterProfileEdit
from services.production_service import generate_production_plan, build_docs, target_scene_count
from services.progress_service import compute_pipeline_progress

MAX_USER_PRODUCTION_REGENERATIONS = 1

user_router = APIRouter(prefix="/orders", tags=["production-user"])
admin_router = APIRouter(prefix="/admin", tags=["production-admin"], dependencies=[Depends(require_admin)])


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------------- Background task ----------------
async def run_production_generation(order_id: str, run_id: str):
    """Production planning, with a heartbeat on the order (see order_heartbeat)."""
    from services.order_heartbeat import beating

    async with beating(order_id):
        await _run_production_generation(order_id, run_id)


async def _run_production_generation(order_id: str, run_id: str):
    """Generate a new production plan in background, archiving any previous plans."""
    from services.ai.fake_providers import CURRENT_ORDER
    CURRENT_ORDER.set(order_id)  # rehearsals build their fake plan from this order
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    scenario = order.get("selected_scenario_snapshot")
    target_scenes = target_scene_count(order, scenario)
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
                # The plan model marked a sensitive topic: an admin reviews it first (PL-13).
                "safety_flag": (docs["plan"].get("safety_check") or "ok") != "ok",
                "safety_review": None,
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
    from services.notify_service import on_status
    on_status(order_id, to_status)


async def trigger_production_planning(order_id: str, background: BackgroundTasks):
    """Called from order_routes after ready_for_ai transitions.

    Wave 3 — try to RESERVE a bundle credit at this exact moment (start of
    production). If no usable bundle exists the order proceeds as a normal
    paid order; if a credit is reserved the order is linked to that purchase
    and will either consume the credit on DELIVERED or refund it on FAILED.
    """
    run_id = str(uuid.uuid4())
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"production_generation": {"run_id": run_id, "source": "pending", "error": None, "started_at": _now()}}},
    )
    o = await db.orders.find_one({"id": order_id}, {"_id": 0, "status": 1, "user_id": 1, "data": 1})
    if o:
        try:
            from services.bundle_service import reserve_for_order
            from models import get_order_output_type
            await reserve_for_order(
                user_id=o.get("user_id"),
                order_id=order_id,
                output_type=get_order_output_type(o),
            )
        except Exception:  # noqa: BLE001
            pass  # bundle reservation is best-effort, never blocks production
    await _append_status(order_id, (o or {}).get("status"), OrderStatus.PRODUCTION_PLANNING.value, "system",
                         reason="auto after ready_for_ai")
    background.add_task(run_production_generation, order_id, run_id)


# ---------------- User endpoints ----------------
def _user_summary(plan: dict | None, order: dict) -> dict | None:
    if not plan:
        return None
    output_type = ((order.get("data") or {}).get("delivery") or {}).get("output_type") or "both"
    return {
        "plan_id": plan["id"],
        "title": plan.get("title"),
        "child_name": ((order.get("data") or {}).get("child") or {}).get("name"),
        "story_summary": plan.get("story_summary"),
        "main_message": plan.get("main_message"),
        "target_scene_count": plan.get("target_scene_count"),
        "estimated_image_count": plan.get("estimated_image_count"),
        "duration_label": plan.get("duration_label"),
        "duration_seconds": plan.get("duration_seconds"),
        "audio_background": plan.get("audio_background") or {"mode": "music"},
        "output_type": output_type,
        "safety_check": plan.get("safety_check"),
        "safety_review": (order.get("safety_review") or {}).get("decision"),
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
    summary = _user_summary(plan, order) if plan_is_live else None
    if summary:
        summary["scenes"] = await db.scene_plans.find(
            {"production_plan_id": plan["id"]},
            {"_id": 0, "scene_index": 1, "title": 1, "narration_text": 1,
             "shots.shot_index": 1, "shots.narration_line": 1},
        ).sort("scene_index", 1).to_list(50)
        summary["max_line_words"] = await _max_line_words()
        summary["narration_edited"] = bool(order.get("narration_edited_at"))
    return {
        "status": effective_status,
        "raw_status": status,
        "status_ar": ORDER_STATUS_AR.get(effective_status, effective_status),
        "summary": summary,
        "production_approved": bool(order.get("production_approved", False)),
        "production_approved_at": order.get("production_approved_at"),
        "production_regeneration_count": used,
        "max_user_production_regenerations": MAX_USER_PRODUCTION_REGENERATIONS,
        "production_regenerations_remaining": max(0, MAX_USER_PRODUCTION_REGENERATIONS - used),
        "progress": progress,
        "photos_deleted_at": order.get("photos_deleted_at"),
        # Waiting for a generation slot (services/limits.py): its place in line.
        "queue": ({k: order["generation_queue"].get(k) for k in ("position", "since")}
                  if status == OrderStatus.PRODUCTION_APPROVED.value and order.get("generation_queue") else None),
    }


@user_router.post("/{order_id}/production/approve")
async def user_approve_production(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if order.get("status") != OrderStatus.PRODUCTION_READY.value:
        raise HTTPException(status_code=400, detail="خطة الإنتاج ليست جاهزة بعد")
    if order.get("safety_flag") and (order.get("safety_review") or {}).get("decision") != "approve":
        raise HTTPException(status_code=400, detail="تحتاج القصة إلى مراجعة سريعة من فريقنا قبل الرسم — ستتمكن من اعتمادها هنا بعد ذلك")
    from services.order_state import claim
    if not await claim(order_id, (OrderStatus.PRODUCTION_READY.value,), OrderStatus.PRODUCTION_APPROVED.value, "user",
                       actor_id=current["id"], reason="user approved production plan",
                       extra={"production_approved": True, "production_approved_at": _now()}):
        raise HTTPException(status_code=409, detail="اعتُمدت الخطة بالفعل")
    # Trigger asset generation pipeline (phase 6A)
    from routes.media_routes import trigger_asset_generation
    run_id = await trigger_asset_generation(order_id, background)
    return {"ok": True, "asset_run_id": run_id}


# ---------------------------------------------------------------- the parent checks the pictures
class PictureKey(BaseModel):
    scene_index: int = Field(ge=0, le=200)
    shot_index: int = Field(ge=0, le=200)


class PictureRedrawIn(BaseModel):
    shots: list[PictureKey] = Field(min_length=1, max_length=12)
    reason: str = Field("other", max_length=20)


@user_router.get("/{order_id}/pictures")
async def user_order_pictures(order_id: str, current=Depends(get_current_user)):
    from services import picture_review

    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    return {"status": order.get("status"), **await picture_review.pictures(order)}


@user_router.post("/{order_id}/pictures/redraw")
async def user_redraw_pictures(order_id: str, payload: PictureRedrawIn, current=Depends(get_current_user)):
    from services import picture_review

    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    try:
        return await picture_review.redraw(order, [(k.scene_index, k.shot_index) for k in payload.shots],
                                           payload.reason, current["id"])
    except picture_review.ReviewError as e:
        raise HTTPException(status_code=409, detail=str(e))


@user_router.post("/{order_id}/pictures/approve")
async def user_approve_pictures(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    from services import picture_review

    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0, "id": 1})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if not await picture_review.approve(order_id, "user", current["id"], background):
        raise HTTPException(status_code=409, detail="الصور اعتُمدت بالفعل أو لسه بتترسم")
    return {"ok": True}


@admin_router.post("/orders/{order_id}/pictures/approve")
async def admin_approve_pictures(order_id: str, background: BackgroundTasks, admin=Depends(require_admin)):
    """For a parent who asked us by phone: the story goes on as if they approved."""
    from services import picture_review
    from services.audit_service import record_audit

    if not await picture_review.approve(order_id, "admin", admin.get("id"), background):
        raise HTTPException(status_code=409, detail="الطلب مش مستني مراجعة الصور")
    await record_audit(entity_type="order", entity_id=order_id, action="pictures.approve", actor_id=admin.get("id"),
                       actor_email=admin.get("email"), summary="اعتماد صور القصة بدل ولي الأمر")
    return {"ok": True}


async def _max_line_words() -> int:
    """The longest narration line that still fits one shot (same rule the plan follows)."""
    from services import engine_config, house_style

    pacing = await engine_config.get_pacing()
    return house_style.max_line_words(pacing["shot_seconds"], pacing["words_per_second"])


class NarrationEditIn(BaseModel):
    # [{"scene_index": 1, "lines": ["…one line per shot…"]}]
    scenes: list[dict] = Field(min_length=1, max_length=20)


@user_router.put("/{order_id}/production/narration")
async def user_edit_narration(order_id: str, payload: NarrationEditIn, current=Depends(get_current_user)):
    """The parent rewords the narrator's lines before approving the plan. One
    line per shot, the same count and length limit the plan was written to, so
    each line still fits its animated shot (the drawings follow the plan)."""
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]},
                                     {"_id": 0, "status": 1, "production_plan_id": 1, "production_approved": 1})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if order.get("status") != OrderStatus.PRODUCTION_READY.value or order.get("production_approved"):
        raise HTTPException(status_code=400, detail="يمكن تعديل النص قبل اعتماد الخطة فقط")
    max_words = await _max_line_words()
    updates = []
    for edit in payload.scenes:
        scene = await db.scene_plans.find_one(
            {"production_plan_id": order.get("production_plan_id"), "scene_index": edit.get("scene_index")},
            {"_id": 0, "id": 1, "scene_index": 1, "shots": 1})
        if not scene:
            raise HTTPException(status_code=404, detail="المشهد غير موجود")
        shots = scene.get("shots") or []
        lines = edit.get("lines") or []
        if not isinstance(lines, list) or len(lines) != len(shots):
            raise HTTPException(status_code=400, detail=f"يجب أن يبقى عدد السطور في المشهد {scene['scene_index']} كما هو ({len(shots)})")
        clean = []
        for i, line in enumerate(lines, 1):
            text = " ".join(str(line or "").split())
            if not text:
                raise HTTPException(status_code=400, detail=f"السطر {i} في المشهد {scene['scene_index']} فارغ")
            if len(text.split()) > max_words or len(text) > 220:
                raise HTTPException(status_code=400,
                                    detail=f"السطر {i} في المشهد {scene['scene_index']} أطول من {max_words} كلمات — اختصره ليناسب اللقطة")
            clean.append(text)
        new_shots = [{**sh, "narration_line": clean[i]} for i, sh in enumerate(shots)]
        narration = " ".join(clean)
        updates.append((scene["id"], new_shots, narration))
    for scene_id, new_shots, narration in updates:
        await db.scene_plans.update_one({"id": scene_id}, {"$set": {
            "shots": new_shots, "narration_text": narration, "word_count": len(narration.split()),
            "narration_edited_by_parent": True, "updated_at": _now()}})
    await db.orders.update_one({"id": order_id}, {"$set": {"narration_edited_at": _now()}})
    from services.audit_service import record_audit
    await record_audit(entity_type="order", entity_id=order_id, action="order.narration_edit",
                       actor_id=current["id"], actor_email=current.get("email"),
                       summary=f"ولي الأمر عدّل سطور الراوي في {len(updates)} مشهد",
                       metadata={"scenes": [s.get("scene_index") for s in payload.scenes]})
    return {"ok": True, "scenes": len(updates)}


@user_router.post("/{order_id}/production/regenerate")
async def user_regenerate_production(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    from services.order_state import PLAN_REGENERABLE, claim
    plan_failed = order.get("status") == OrderStatus.FAILED.value and \
        (order.get("production_generation") or {}).get("source") == "error"
    if order.get("production_approved") or order.get("status") not in PLAN_REGENERABLE or \
            (order.get("status") == OrderStatus.FAILED.value and not plan_failed):
        raise HTTPException(status_code=400, detail="لا يمكن إعادة التوليد بعد بدء الإنتاج")
    from services.engine_health import ensure_available
    await ensure_available()
    used = int(order.get("production_regeneration_count", 0))
    if used >= MAX_USER_PRODUCTION_REGENERATIONS:
        raise HTTPException(
            status_code=429,
            detail="لقد استخدمت محاولة إعادة توليد خطة الإنتاج المتاحة.",
        )
    run_id = str(uuid.uuid4())
    if not await claim(order_id, PLAN_REGENERABLE, OrderStatus.PRODUCTION_PLANNING.value, "user", actor_id=current["id"],
                       reason=f"user regenerate production ({used + 1}/{MAX_USER_PRODUCTION_REGENERATIONS})",
                       extra={"production_generation": {"run_id": run_id, "source": "pending", "error": None,
                                                        "started_at": _now()}},
                       inc={"production_regeneration_count": 1}):
        raise HTTPException(status_code=409, detail="تغيّر الطلب — حدّث الصفحة")
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
        raise HTTPException(status_code=400, detail="لم تُختر الحكاية بعد")
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
