"""Media (assets) routes — Phase 6A + Final Assembly Phase 6B."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

from db import db
from auth import get_current_user, require_admin
from models import ORDER_STATUS_AR, OrderStatus
from services.generation_orchestrator import run_asset_generation, retry_single_job
from services.final_delivery_service import run_final_assembly, retry_single_assembly_job
from services.progress_service import compute_pipeline_progress
from services.child_character_service import safe_run as run_child_character_stage, get_asset as get_child_character_asset
from services.config_service import get_pipeline_config

user_router = APIRouter(prefix="/orders", tags=["media-user"])
admin_router = APIRouter(prefix="/admin", tags=["media-admin"], dependencies=[Depends(require_admin)])


def _now():
    return datetime.now(timezone.utc).isoformat()


async def trigger_asset_generation(order_id: str, background: BackgroundTasks) -> str:
    """Called from production/approve. Returns run_id."""
    run_id = str(uuid.uuid4())
    # Wrap so that when assets finish, we auto-trigger final assembly
    async def _pipeline():
        await run_asset_generation(order_id, run_id)
        o = await db.orders.find_one({"id": order_id}, {"_id": 0, "status": 1})
        if o and o.get("status") == OrderStatus.ASSETS_READY.value:
            await run_final_assembly(order_id, str(uuid.uuid4()))

    background.add_task(_pipeline)
    return run_id


async def assets_complete(order_id: str) -> bool:
    """Everything the final assembly needs exists for the current plan, so a
    retry only re-runs the assembly. Otherwise the asset pipeline resumes, and it
    skips whatever is already drawn, voiced or animated. (Counting "at least one
    finished scene" sent a half-drawn order straight to assembly.)"""
    from models import get_order_output_type
    from services.shot_pipeline import shot_rows

    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    plan_id = (order or {}).get("production_plan_id")
    if not plan_id:
        return False
    if not await db.generation_jobs.count_documents({"order_id": order_id, "job_type": "cover_image",
                                                     "status": "completed"}):
        return False
    scenes = await db.scene_plans.find({"order_id": order_id, "production_plan_id": plan_id, "is_archived": False},
                                       {"_id": 0, "scene_index": 1, "shots": 1}).to_list(50)
    planned = sum(len(sc.get("shots") or []) for sc in scenes)
    if planned:
        # A paid premium clip is never replaced by a push-in just because a
        # retry skipped it: video orders need every clip.
        need_clip = get_order_output_type(order) in ("video", "both")
        done = [r for r in await shot_rows(order_id, plan_id)
                if r.get("keyframe_url") and r.get("narration_url") and (r.get("clip_url") or not need_clip)]
        return len(done) >= planned
    drawn = await db.generation_jobs.distinct("meta.scene_index", {"order_id": order_id, "job_type": "scene_image",
                                                                   "status": "completed"})
    return len(drawn) >= len(scenes)


async def trigger_final_assembly(order_id: str, background: BackgroundTasks) -> str:
    run_id = str(uuid.uuid4())
    background.add_task(run_final_assembly, order_id, run_id)
    return run_id


# ---------------- User endpoints ----------------
@user_router.get("/{order_id}/media-status")
async def user_media_status(order_id: str, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    summary = order.get("asset_generation_summary") or {"total": 0, "completed": 0, "failed": 0, "queued": 0, "processing": 0}
    progress = await compute_pipeline_progress(order)
    return {
        "status": order.get("status"),
        "status_ar": ORDER_STATUS_AR.get(order.get("status"), order.get("status")),
        "progress_percent": progress["percent"],
        "progress": progress,
        "summary": {
            "total": summary.get("total") or 0,
            "completed": summary.get("completed") or 0,
            "failed": summary.get("failed") or 0,
        },
    }


# ---------------- Admin endpoints ----------------
@admin_router.get("/orders/{order_id}/media")
async def admin_get_media(order_id: str):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    jobs = await db.generation_jobs.find({"order_id": order_id}, {"_id": 0}).sort("created_at", -1).to_list(200)
    scene_images = await db.scene_images.find({"order_id": order_id}, {"_id": 0}).sort("scene_index", 1).to_list(50)
    narration = await db.narration_assets.find({"order_id": order_id}, {"_id": 0}).sort("scene_index", 1).to_list(50)
    book_assets = await db.book_assets.find({"order_id": order_id}, {"_id": 0}).sort("page_number", 1).to_list(50)

    # Counts
    counts = {"queued": 0, "processing": 0, "completed": 0, "failed": 0, "total": len(jobs)}
    for j in jobs:
        s = j.get("status")
        if s in counts:
            counts[s] += 1

    return {
        "order_id": order_id,
        "status": order.get("status"),
        "status_ar": ORDER_STATUS_AR.get(order.get("status"), order.get("status")),
        "asset_generation_run_id": order.get("asset_generation_run_id"),
        "asset_generation_started_at": order.get("asset_generation_started_at"),
        "asset_generation_completed_at": order.get("asset_generation_completed_at"),
        "summary": order.get("asset_generation_summary") or counts,
        "counts": counts,
        "jobs": jobs,
        "scene_images": scene_images,
        "narration_assets": narration,
        "book_assets": book_assets,
    }


@admin_router.post("/orders/{order_id}/media/regenerate")
async def admin_regenerate_media(order_id: str, background: BackgroundTasks, admin=Depends(require_admin)):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if not order.get("production_approved"):
        raise HTTPException(status_code=400, detail="يجب اعتماد خطة الإنتاج أولاً")
    # Archive prior assets
    await db.generation_jobs.update_many({"order_id": order_id}, {"$set": {"status_archived": True}})
    await db.scene_images.delete_many({"order_id": order_id})
    await db.narration_assets.delete_many({"order_id": order_id})
    await db.book_assets.delete_many({"order_id": order_id})
    await db.generation_jobs.delete_many({"order_id": order_id})
    run_id = str(uuid.uuid4())
    background.add_task(run_asset_generation, order_id, run_id)
    return {"ok": True, "run_id": run_id}


@admin_router.post("/jobs/{job_id}/retry")
async def admin_retry_job(job_id: str, background: BackgroundTasks):
    job = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        raise HTTPException(status_code=404, detail="الوظيفة غير موجودة")
    # route assembly jobs to the delivery retry, asset jobs to the media retry
    if job.get("job_type") in ("final_video_assembly", "final_pdf_assembly"):
        background.add_task(retry_single_assembly_job, job_id)
    else:
        background.add_task(retry_single_job, job_id)
    return {"ok": True, "queued": True}


# ---------------- Child character (Phase C) ----------------
@admin_router.get("/orders/{order_id}/child-character")
async def admin_get_child_character(order_id: str):
    """Return the current child_character_i2i asset + stage status for admin UI."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "data": 1, "status": 1})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    asset = await get_child_character_asset(order_id)
    child = (order.get("data") or {}).get("child") or {}
    # Use the resolver so defaults/merge stay consistent with the orchestrator.
    pipeline_cfg = await get_pipeline_config()
    stage_cfg = ((pipeline_cfg or {}).get("stages") or {}).get("child_character_i2i") or {}
    return {
        "order_id": order_id,
        "stage_enabled": bool(stage_cfg.get("enabled", False)),
        "stage_config": stage_cfg,
        "source_image_url": child.get("image_url"),
        "child_name": child.get("name"),
        "asset": asset,
    }


# ---------------- Shots (admin): see every shot, redo one ----------------
_SHOT_FIELDS = ("scene_index", "shot_index", "narration_line", "shot_type", "characters", "keyframe_url",
                "keyframe_review", "motion_prompt", "clip_url", "clip_state", "clip_error", "clip_review",
                "clip_calm_redo", "clip_prompt_used", "clip_seconds", "narration_seconds", "redo", "updated_at")


@admin_router.get("/orders/{order_id}/shots")
async def admin_order_shots(order_id: str):
    from services.shot_pipeline import shot_rows

    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "production_plan_id": 1, "status": 1})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    rows = await shot_rows(order_id, order["production_plan_id"]) if order.get("production_plan_id") else []
    return {"status": order.get("status"), "shots": [{k: r.get(k) for k in _SHOT_FIELDS} for r in rows]}


class ShotRedoIn(BaseModel):
    target: str = Field("clip", pattern="^(clip|both)$")  # both = new start frame and new clip
    motion_prompt: str | None = Field(None, max_length=1200)
    reassemble: bool = True


@admin_router.post("/orders/{order_id}/shots/{scene_index}/{shot_index}/redo")
async def admin_redo_shot(order_id: str, scene_index: int, shot_index: int, payload: ShotRedoIn,
                          background: BackgroundTasks, admin=Depends(require_admin)):
    """Fix one bad shot of a customer's story — a new clip (optionally with an
    edited motion prompt) or a new start frame and clip — then re-assemble the
    video, without redoing the rest of the story."""
    from services.audit_service import record_audit
    from services.engine_health import ensure_available

    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order or not order.get("production_plan_id"):
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if order.get("status") in (OrderStatus.ASSETS_GENERATING.value, OrderStatus.ASSEMBLING.value):
        raise HTTPException(status_code=409, detail="الطلب لسه بيتجهّز — استنى لما يخلص")
    key = {"order_id": order_id, "production_plan_id": order["production_plan_id"],
           "scene_index": scene_index, "shot_index": shot_index}
    row = await db.shot_assets.find_one(key, {"_id": 0})
    if not row:
        raise HTTPException(status_code=404, detail="اللقطة مش موجودة")
    if (row.get("redo") or {}).get("state") == "running":
        raise HTTPException(status_code=409, detail="اللقطة دي بتتعاد دلوقتي")
    await ensure_available()
    reset = {"clip_url": None, "clip_request_id": None, "clip_prompt_id": None, "clip_rescue": None,
             "clip_state": None, "clip_error": None, "clip_review": None,
             "clip_run_id": None, "redo": {"state": "running", "target": payload.target, "by": admin.get("email"),
                                           "at": _now()}}
    if payload.target == "both":
        # A stale Comfy job id would hand back the old picture instead of a new one.
        reset.update({"keyframe_url": None, "keyframe_review": None, "keyframe_prompt_id": None,
                      "keyframe_prompt_attempt": None})
    if payload.motion_prompt is not None and payload.motion_prompt.strip():
        reset["motion_prompt"] = payload.motion_prompt.strip()
        # The plan keeps the edit too, so a later full rerun uses it.
        await db.scene_plans.update_one(
            {"id": row["scene_plan_id"], "shots.shot_index": shot_index},
            {"$set": {"shots.$.motion_prompt": reset["motion_prompt"]}})
    await db.shot_assets.update_one(key, {"$set": reset})
    await record_audit(entity_type="order", entity_id=order_id, action="shot.redo", actor_id=admin.get("id"),
                       actor_email=admin.get("email"), summary=f"إعادة اللقطة {scene_index}_{shot_index} "
                       f"({'الصورة والمقطع' if payload.target == 'both' else 'المقطع'})",
                       before={k: row.get(k) for k in ("keyframe_url", "clip_url", "motion_prompt")},
                       after={"target": payload.target, "motion_prompt": reset.get("motion_prompt")})

    async def _redo():
        from services import shot_pipeline
        from services.ai.fake_providers import CURRENT_ORDER

        CURRENT_ORDER.set(order_id)  # a fix for a delivered story keeps its order's place in Comfy's line
        state, error = "done", None
        try:
            plan = await db.production_plans.find_one({"id": order["production_plan_id"]}, {"_id": 0})
            if payload.target == "both":
                # Redraws only the shots without a start frame (this one), seeing the previous shot.
                await shot_pipeline.execute_scene_keyframes(
                    {"id": f"admin-redo-{uuid.uuid4()}", "target_id": row["scene_plan_id"]}, order, plan)
            result = await shot_pipeline.run_shot_clips(order, plan, f"admin-redo-{uuid.uuid4()}",
                                                        scene_index=scene_index, summarize=False)
            if not result.get("saved"):
                raise RuntimeError(result.get("reason") or "the clip wasn't made")
            fresh = await db.shot_assets.find_one(key, {"_id": 0, "clip_url": 1})
            if not (fresh or {}).get("clip_url"):
                raise RuntimeError("the clip wasn't made")
            if payload.reassemble:
                await run_final_assembly(order_id, str(uuid.uuid4()))
        except Exception as e:  # noqa: BLE001
            state, error = "failed", f"{type(e).__name__}: {str(e)[:200]}"
        await db.shot_assets.update_one(key, {"$set": {"redo.state": state, "redo.error": error,
                                                       "redo.finished_at": _now()}})

    background.add_task(_redo)
    return {"ok": True}


@admin_router.post("/orders/{order_id}/child-character/regenerate")
async def admin_regenerate_child_character(order_id: str, background: BackgroundTasks):
    """Re-run the child_character_i2i stage in the background.

    Works even if the stage is disabled in pipeline_config → the service
    will detect and return a `skipped` descriptor that the UI can surface.
    """
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    plan = None
    if order.get("production_plan_id"):
        plan = await db.production_plans.find_one({"id": order["production_plan_id"]}, {"_id": 0})

    async def _run():
        await run_child_character_stage(order, plan, force=True)

    background.add_task(_run)
    return {"ok": True, "queued": True}


# ---------------- Final delivery ----------------
@user_router.get("/{order_id}/delivery")
async def user_delivery(order_id: str, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    video = await db.final_videos.find_one({"order_id": order_id}, {"_id": 0}, sort=[("created_at", -1)])
    pdf = await db.final_pdfs.find_one({"order_id": order_id}, {"_id": 0}, sort=[("created_at", -1)])
    summary = order.get("final_assembly_summary") or {}
    total = summary.get("total") or 0
    completed = summary.get("completed") or 0
    pct = int((completed / total) * 100) if total else (100 if order.get("status") == "delivered" else 0)
    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0, "title": 1, "story_summary": 1, "main_message": 1, "audio_background": 1})
    return {
        "status": order.get("status"),
        "status_ar": ORDER_STATUS_AR.get(order.get("status"), order.get("status")),
        "progress_percent": pct,
        "summary": summary,
        "plan": plan,
        "video": {
            "video_url": (video or {}).get("video_url"),
            "thumbnail_url": (video or {}).get("thumbnail_url"),
            "duration_seconds": (video or {}).get("duration_seconds"),
            "audio_background_mode": (video or {}).get("audio_background_mode"),
        } if video else None,
        "pdf": {
            "pdf_url": (pdf or {}).get("pdf_url"),
            "page_count": (pdf or {}).get("page_count"),
        } if pdf else None,
    }


@admin_router.get("/orders/{order_id}/delivery")
async def admin_get_delivery(order_id: str):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    video = await db.final_videos.find_one({"order_id": order_id}, {"_id": 0}, sort=[("created_at", -1)])
    pdf = await db.final_pdfs.find_one({"order_id": order_id}, {"_id": 0}, sort=[("created_at", -1)])
    jobs = await db.generation_jobs.find(
        {"order_id": order_id, "job_type": {"$in": ["final_video_assembly", "final_pdf_assembly"]}},
        {"_id": 0},
    ).sort("created_at", -1).to_list(20)
    return {
        "order_id": order_id,
        "status": order.get("status"),
        "status_ar": ORDER_STATUS_AR.get(order.get("status"), order.get("status")),
        "final_assembly_run_id": order.get("final_assembly_run_id"),
        "final_assembly_started_at": order.get("final_assembly_started_at"),
        "final_assembly_completed_at": order.get("final_assembly_completed_at"),
        "summary": order.get("final_assembly_summary"),
        "jobs": jobs,
        "video": video,
        "pdf": pdf,
    }


@admin_router.post("/orders/{order_id}/delivery/regenerate")
async def admin_regenerate_delivery(order_id: str, background: BackgroundTasks, admin=Depends(require_admin)):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if order.get("status") not in (OrderStatus.ASSETS_READY.value, OrderStatus.DELIVERED.value,
                                    OrderStatus.MEDIA_FAILED.value, OrderStatus.ASSEMBLING.value):
        raise HTTPException(status_code=400, detail="يجب أن تكون الوسائط جاهزة قبل التجميع")
    run_id = str(uuid.uuid4())
    background.add_task(run_final_assembly, order_id, run_id)
    return {"ok": True, "run_id": run_id}


@user_router.post("/{order_id}/retry-delivery")
async def user_retry_delivery(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    """User-initiated retry after a media_failed state.

    Resumes from whichever phase stopped:
    * If assets never finished  → re-run the asset pipeline (which auto-kicks assembly).
    * If assembly failed         → re-run final assembly only.
    """
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if not order.get("production_approved"):
        raise HTTPException(status_code=400, detail="لم يتم اعتماد خطة الإنتاج بعد")
    from services.order_state import MAX_USER_DELIVERY_RETRIES, claim
    if order.get("status") != OrderStatus.MEDIA_FAILED.value:
        raise HTTPException(status_code=400, detail="إعادة المحاولة متاحة فقط إذا توقف التجهيز")
    if int(order.get("user_delivery_retries") or 0) >= MAX_USER_DELIVERY_RETRIES:
        raise HTTPException(status_code=429, detail="استخدمت محاولات الإعادة المتاحة — فريقنا هيتابع الطلب")
    from services.engine_health import ensure_available
    await ensure_available()
    assembly_only = await assets_complete(order_id)
    to_status = OrderStatus.ASSEMBLING.value if assembly_only else OrderStatus.ASSETS_GENERATING.value
    if not await claim(order_id, (OrderStatus.MEDIA_FAILED.value,), to_status, "user", actor_id=current["id"],
                       reason="user retry", inc={"user_delivery_retries": 1}):
        raise HTTPException(status_code=409, detail="الطلب اتغيّر — حدّث الصفحة")
    if assembly_only:
        run_id = str(uuid.uuid4())
        background.add_task(run_final_assembly, order_id, run_id)
    else:
        run_id = await trigger_asset_generation(order_id, background)
    return {"ok": True, "run_id": run_id}
