"""Media (assets) routes — Phase 6A.

User: polling + light status view.
Admin: full job board, previews, per-job retry, bulk regenerate.
"""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from db import db
from auth import get_current_user, require_admin
from models import ORDER_STATUS_AR
from services.generation_orchestrator import run_asset_generation, retry_single_job

user_router = APIRouter(prefix="/orders", tags=["media-user"])
admin_router = APIRouter(prefix="/admin", tags=["media-admin"], dependencies=[Depends(require_admin)])


def _now():
    return datetime.now(timezone.utc).isoformat()


async def trigger_asset_generation(order_id: str, background: BackgroundTasks) -> str:
    """Called from production/approve. Returns run_id."""
    run_id = str(uuid.uuid4())
    background.add_task(run_asset_generation, order_id, run_id)
    return run_id


# ---------------- User endpoints ----------------
@user_router.get("/{order_id}/media-status")
async def user_media_status(order_id: str, current=Depends(get_current_user)):
    order = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    summary = order.get("asset_generation_summary") or {"total": 0, "completed": 0, "failed": 0, "queued": 0, "processing": 0}
    total = summary.get("total") or 0
    completed = summary.get("completed") or 0
    pct = int((completed / total) * 100) if total else 0
    return {
        "status": order.get("status"),
        "status_ar": ORDER_STATUS_AR.get(order.get("status"), order.get("status")),
        "progress_percent": pct,
        "summary": summary,
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
    # Fire-and-forget via background
    background.add_task(retry_single_job, job_id)
    return {"ok": True, "queued": True}
