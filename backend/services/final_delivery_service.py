"""Final delivery orchestrator — Phase 6B.

Pipeline:
  assets_ready → assembling → delivered | media_failed

Creates 2 assembly jobs (final_video_assembly + final_pdf_assembly),
runs them with retry (max_attempts=3), persists to final_videos / final_pdfs,
and returns delivery summary.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone

from db import db
from models import OrderStatus, ORDER_STATUS_AR
from services.video_assembly_service import assemble_video
from services.pdf_assembly_service import assemble_pdf

logger = logging.getLogger("final_delivery_service")

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = [1, 3, 7]


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _append_status(order_id, from_status, to_status, by, actor_id=None, reason=None):
    entry = {"from": from_status, "to": to_status, "at": _now(),
             "by": by, "actor_id": actor_id, "reason": reason}
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"status": to_status, "updated_at": _now()},
         "$push": {"status_history": entry}},
    )


async def _update_job(job_id: str, patch: dict):
    patch["updated_at"] = _now()
    await db.generation_jobs.update_one({"id": job_id}, {"$set": patch})


async def _run_video_job(job: dict, order: dict, plan: dict) -> dict:
    # Gather scene images + narrations
    scene_images = await db.scene_images.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "kind": "scene"},
        {"_id": 0},
    ).sort("scene_index", 1).to_list(50)
    cover = await db.scene_images.find_one(
        {"order_id": order["id"], "production_plan_id": plan["id"], "kind": "cover"},
        {"_id": 0},
    )
    narrations = await db.narration_assets.find(
        {"order_id": order["id"], "production_plan_id": plan["id"]},
        {"_id": 0},
    ).sort("scene_index", 1).to_list(50)

    video_url, thumbnail_url, meta = await assemble_video(
        order_id=order["id"],
        plan=plan,
        cover_image_url=(cover or {}).get("image_url"),
        scenes=scene_images,
        narrations=narrations,
    )

    fv_id = str(uuid.uuid4())
    await db.final_videos.insert_one({
        "id": fv_id,
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "generation_job_id": job["id"],
        "video_url": video_url,
        "thumbnail_url": thumbnail_url,
        "duration_seconds": meta.get("total_duration_seconds"),
        "audio_background_mode": meta.get("audio_background_mode"),
        "provider": "ffmpeg",
        "source_type": "fallback" if "silent" in (meta.get("audio_track") or "") else "ai",
        "assembly_metadata": meta,
        "created_at": _now(),
    })
    return {"provider": "ffmpeg", "output_url": video_url, "final_video_id": fv_id}


async def _run_pdf_job(job: dict, order: dict, plan: dict) -> dict:
    cover = await db.scene_images.find_one(
        {"order_id": order["id"], "production_plan_id": plan["id"], "kind": "cover"},
        {"_id": 0},
    )
    book_assets = await db.book_assets.find(
        {"order_id": order["id"], "production_plan_id": plan["id"]},
        {"_id": 0},
    ).sort("page_number", 1).to_list(50)

    pdf_url, page_count, meta = await assemble_pdf(
        order_id=order["id"],
        plan=plan,
        cover_image_url=(cover or {}).get("image_url"),
        book_assets=book_assets,
    )

    fp_id = str(uuid.uuid4())
    await db.final_pdfs.insert_one({
        "id": fp_id,
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "generation_job_id": job["id"],
        "pdf_url": pdf_url,
        "page_count": page_count,
        "cover_image_url": (cover or {}).get("image_url"),
        "provider": "reportlab",
        "assembly_metadata": meta,
        "created_at": _now(),
    })
    return {"provider": "reportlab", "output_url": pdf_url, "final_pdf_id": fp_id}


async def _process_with_retry(job: dict, order: dict, plan: dict, executor) -> bool:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        await _update_job(job["id"], {"status": "processing", "attempt_count": attempt})
        try:
            out = await executor(job, order, plan)
            await _update_job(job["id"], {
                "status": "completed",
                "provider": out.get("provider"),
                "output_url": out.get("output_url"),
                "output_metadata": out,
                "error_message": None,
            })
            return True
        except Exception as e:
            err = f"attempt {attempt}: {type(e).__name__}: {e}"
            logger.warning(f"assembly job {job['id']} ({job['job_type']}) failed {err}")
            await _update_job(job["id"], {"error_message": err})
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
            else:
                await _update_job(job["id"], {"status": "failed"})
                return False
    return False


async def run_final_assembly(order_id: str, run_id: str):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0})
    if not plan:
        await _append_status(order_id, order.get("status"), OrderStatus.MEDIA_FAILED.value, "system",
                             reason="final assembly: no production plan")
        return

    # Prepare jobs (clear prior final-assembly jobs for this order)
    await db.generation_jobs.delete_many({"order_id": order_id, "job_type": {"$in": ["final_video_assembly", "final_pdf_assembly"]}})
    await db.final_videos.delete_many({"order_id": order_id})
    await db.final_pdfs.delete_many({"order_id": order_id})

    jobs = []
    for jt in ["final_video_assembly", "final_pdf_assembly"]:
        j = {
            "id": str(uuid.uuid4()),
            "order_id": order_id,
            "run_id": run_id,
            "job_type": jt,
            "target_id": plan["id"],
            "meta": {"plan_id": plan["id"]},
            "status": "queued",
            "provider": None,
            "attempt_count": 0,
            "max_attempts": MAX_ATTEMPTS,
            "error_message": None,
            "output_url": None,
            "output_metadata": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        jobs.append(j)
    await db.generation_jobs.insert_many(jobs)

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "final_assembly_run_id": run_id,
            "final_assembly_started_at": _now(),
            "final_assembly_summary": {"total": 2, "completed": 0, "failed": 0},
        }},
    )
    await _append_status(order_id, order.get("status"), OrderStatus.ASSEMBLING.value, "system",
                         reason=f"start final assembly (run {run_id[:8]})")

    # Run video first, then PDF
    results = {"video": False, "pdf": False}
    for job in jobs:
        executor = _run_video_job if job["job_type"] == "final_video_assembly" else _run_pdf_job
        ok = await _process_with_retry(job, order, plan, executor)
        key = "video" if job["job_type"] == "final_video_assembly" else "pdf"
        results[key] = ok
        completed = sum(1 for v in results.values() if v)
        failed = sum(1 for v in results.values() if not v)
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {"final_assembly_summary.completed": completed,
                      "final_assembly_summary.failed": failed,
                      "updated_at": _now()}},
        )

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"final_assembly_completed_at": _now()}},
    )
    # Delivery is successful only if BOTH assembled
    if all(results.values()):
        await _append_status(order_id, OrderStatus.ASSEMBLING.value, OrderStatus.DELIVERED.value, "system",
                             reason="final video + PDF ready")
    else:
        missing = ", ".join(k for k, v in results.items() if not v)
        await _append_status(order_id, OrderStatus.ASSEMBLING.value, OrderStatus.MEDIA_FAILED.value, "system",
                             reason=f"final assembly failed: {missing}")


async def retry_single_assembly_job(job_id: str) -> dict:
    job = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        return {"ok": False, "error": "job not found"}
    order = await db.orders.find_one({"id": job["order_id"]}, {"_id": 0})
    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0})
    await _update_job(job_id, {"status": "queued", "attempt_count": 0, "error_message": None, "output_url": None})
    job = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    executor = _run_video_job if job["job_type"] == "final_video_assembly" else _run_pdf_job
    ok = await _process_with_retry(job, order, plan, executor)
    # Re-evaluate order status if both complete
    order = await db.orders.find_one({"id": job["order_id"]}, {"_id": 0})
    video = await db.final_videos.find_one({"order_id": job["order_id"]}, {"_id": 0})
    pdf = await db.final_pdfs.find_one({"order_id": job["order_id"]}, {"_id": 0})
    if video and pdf and order.get("status") != OrderStatus.DELIVERED.value:
        await _append_status(job["order_id"], order.get("status"), OrderStatus.DELIVERED.value, "admin",
                             reason="both finals present after retry")
    return {"ok": ok}
