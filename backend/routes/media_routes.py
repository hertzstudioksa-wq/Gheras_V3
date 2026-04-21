"""Media (assets) routes — Phase 6A + Final Assembly Phase 6B."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from db import db
from auth import get_current_user, require_admin
from models import ORDER_STATUS_AR, OrderStatus
from services.generation_orchestrator import run_asset_generation, retry_single_job
from services.final_delivery_service import run_final_assembly, retry_single_assembly_job
from services.progress_service import compute_pipeline_progress

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


# ---------------- Final delivery ----------------
@user_router.get("/{order_id}/delivery")
async def user_delivery(order_id: str, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    video = await db.final_videos.find_one({"order_id": order_id}, {"_id": 0})
    pdf = await db.final_pdfs.find_one({"order_id": order_id}, {"_id": 0})
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
    video = await db.final_videos.find_one({"order_id": order_id}, {"_id": 0})
    pdf = await db.final_pdfs.find_one({"order_id": order_id}, {"_id": 0})
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
    # If cover + at least one scene image completed, we can safely retry final assembly.
    # Otherwise restart the full asset pipeline (which auto-kicks assembly when done).
    cover_done = await db.generation_jobs.count_documents({
        "order_id": order_id, "job_type": "cover_image", "status": "completed",
    })
    scene_done = await db.generation_jobs.count_documents({
        "order_id": order_id, "job_type": "scene_image", "status": "completed",
    })
    if cover_done >= 1 and scene_done >= 1:
        run_id = str(uuid.uuid4())
        background.add_task(run_final_assembly, order_id, run_id)
    else:
        run_id = await trigger_asset_generation(order_id, background)
    return {"ok": True, "run_id": run_id}
