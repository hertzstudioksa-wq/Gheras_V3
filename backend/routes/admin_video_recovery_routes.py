"""Admin video-clip recovery — Phase N.

Manual recovery for fal.ai Kling video clips when polling/import missed a
successful generation. Use cases:

  * Process crashed mid-poll → request_id was persisted but never imported.
  * Polling timed out (>15min) but the clip eventually completed on fal.ai.
  * fal.ai dashboard shows COMPLETED but our row is `submitted_no_result`.

Endpoint:
    POST /api/admin/orders/{order_id}/video-clips/import-by-request-id
    {
      "scene_index": int,
      "request_id":  str,                # required
      "model_slug":  str,    (optional)  # falls back to current default
      "force":       bool,   (optional)  # re-import even if already imported
    }

Returns:
    {ok: bool, state: str, video_url: str|None, clip_id: str|None,
     bytes: int, import_status: str, error: str|None}

Behavior:
  1. Resolves FAL_KEY_VIDEO via secret_overrides.
  2. Polls fal.ai once for the request_id (no submit, no extra cost).
  3. If COMPLETED + has video_url → downloads bytes → saves to internal
     storage → updates the existing video_clips row to import_status=imported.
  4. If still IN_QUEUE / IN_PROGRESS → returns the truth.
  5. If FAILED on fal.ai side → returns the error and updates fallback_reason.
  6. Idempotent: re-running on an already-imported clip is a no-op unless
     `force=true`.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import require_admin
from db import db
from storage import put_object, APP_NAME
from services.video_generation_service import (
    poll_clip, download_clip, _resolve_video_provider,
)
from services.audit_service import record_audit

logger = logging.getLogger("admin_video_recovery")
router = APIRouter(
    prefix="/admin", tags=["admin-video-recovery"], dependencies=[Depends(require_admin)],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ImportByRequestIdPayload(BaseModel):
    scene_index: int
    request_id:  str
    model_slug:  Optional[str] = None
    force:       bool = False


@router.post("/orders/{order_id}/video-clips/import-by-request-id")
async def import_clip_by_request_id(
    order_id: str,
    payload: ImportByRequestIdPayload,
    admin=Depends(require_admin),
):
    """Manually recover a fal.ai Kling clip that succeeded on fal.ai but
    didn't make it into our DB."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "id": 1, "user_id": 1})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")

    existing = await db.video_clips.find_one(
        {"order_id": order_id, "scene_index": payload.scene_index}, {"_id": 0},
    )

    # Idempotency: if already imported, no-op unless force=true.
    if existing and existing.get("import_status") == "imported" and not payload.force:
        return {
            "ok":            True,
            "state":         "ALREADY_IMPORTED",
            "video_url":     existing.get("video_url"),
            "clip_id":       existing.get("id"),
            "bytes":         existing.get("size") or 0,
            "import_status": "imported",
            "error":         None,
            "note":          "Already imported. Use force=true to re-download.",
        }

    # Resolve model slug — prefer caller's hint, fall back to current default.
    model_slug = payload.model_slug
    if not model_slug:
        _, model_slug = await _resolve_video_provider()

    # Single poll tick — costs nothing if request_id is valid.
    state, info = await poll_clip(payload.request_id, model_slug)

    base_patch = {
        "request_id":     payload.request_id,
        "model":          model_slug,
        "state":          state,
        "updated_at":     _now(),
    }

    if state in ("IN_QUEUE", "IN_PROGRESS"):
        await db.video_clips.update_one(
            {"order_id": order_id, "scene_index": payload.scene_index},
            {"$set": {**base_patch, "import_status": "still_pending"}},
            upsert=False,
        )
        return {
            "ok": False, "state": state, "video_url": None, "clip_id": None,
            "bytes": 0, "import_status": "still_pending",
            "error": "fal.ai is still processing; try again later.",
        }

    if state in ("FAILED", "UNKNOWN") or not info.get("video_url"):
        err = info.get("error") or f"final_state={state}"
        await db.video_clips.update_one(
            {"order_id": order_id, "scene_index": payload.scene_index},
            {"$set": {
                **base_patch,
                "import_status":   "import_failed",
                "fallback_reason": err,
                "error":           err,
            }},
            upsert=False,
        )
        return {
            "ok": False, "state": state, "video_url": None, "clip_id": None,
            "bytes": 0, "import_status": "import_failed", "error": err,
        }

    # COMPLETED — download bytes + persist.
    video_url = info["video_url"]
    bytes_ = await download_clip(video_url)
    if not bytes_:
        await db.video_clips.update_one(
            {"order_id": order_id, "scene_index": payload.scene_index},
            {"$set": {
                **base_patch,
                "remote_video_url": video_url,
                "import_status":    "import_failed_remote_url_only",
                "fallback_reason":  "download_failed",
                "error":            "download_failed",
            }},
            upsert=False,
        )
        return {
            "ok": False, "state": "COMPLETED", "video_url": None, "clip_id": None,
            "bytes": 0, "import_status": "import_failed_remote_url_only",
            "error": "fal.ai returned a URL but our download failed. Saved the remote URL for retry.",
        }

    file_id = str(uuid.uuid4())
    storage_path = f"{APP_NAME}/orders/{order_id}/generated/clips/{file_id}.mp4"
    loop = asyncio.get_running_loop()
    try:
        stored = await loop.run_in_executor(
            None, lambda: put_object(storage_path, bytes_, "video/mp4"),
        )
        await db.files.insert_one({
            "id": file_id,
            "user_id": order.get("user_id"),
            "scope": "generated-video-clip",
            "storage_path": stored.get("path", storage_path),
            "original_filename": f"scene-{payload.scene_index:02d}.mp4",
            "content_type": "video/mp4",
            "size": stored.get("size", len(bytes_)),
            "is_deleted": False,
            "created_at": _now(),
        })
        clip_url = f"/api/uploads/file/{file_id}"

        await db.video_clips.update_one(
            {"order_id": order_id, "scene_index": payload.scene_index},
            {"$set": {
                **base_patch,
                "remote_video_url": video_url,
                "video_url":        clip_url,
                "size":             len(bytes_),
                "real_call":        True,
                "fallback_to_mock": False,
                "error":            None,
                "fallback_reason":  None,
                "import_status":    "imported",
                "imported_at":      _now(),
                "imported_by":      admin.get("email"),
                "manually_recovered": True,
            }},
            upsert=False,
        )

        try:
            await record_audit(
                entity_type="video_clip",
                entity_id=f"{order_id}:{payload.scene_index}",
                action="import_by_request_id",
                actor_id=admin.get("id"),
                actor_email=admin.get("email"),
                summary=f"Manually imported clip request_id={payload.request_id}",
                before=existing,
                after={"video_url": clip_url, "request_id": payload.request_id},
            )
        except Exception:  # noqa: BLE001
            pass

        return {
            "ok": True, "state": "COMPLETED", "video_url": clip_url,
            "clip_id": file_id, "bytes": len(bytes_),
            "import_status": "imported", "error": None,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"manual import storage failed: {e}")
        await db.video_clips.update_one(
            {"order_id": order_id, "scene_index": payload.scene_index},
            {"$set": {
                **base_patch,
                "remote_video_url": video_url,
                "import_status":    "import_failed_storage",
                "fallback_reason":  f"{type(e).__name__}: {e}",
                "error":            f"{type(e).__name__}: {e}",
            }},
            upsert=False,
        )
        return {
            "ok": False, "state": "COMPLETED", "video_url": None, "clip_id": None,
            "bytes": 0, "import_status": "import_failed_storage",
            "error": f"{type(e).__name__}: {e}",
        }


@router.get("/orders/{order_id}/video-clips")
async def list_clips_for_recovery(order_id: str, admin=Depends(require_admin)):
    """List all video_clips rows for an order — admin recovery view."""
    rows = await db.video_clips.find(
        {"order_id": order_id}, {"_id": 0},
    ).sort("scene_index", 1).to_list(50)
    return {
        "order_id": order_id,
        "count":    len(rows),
        "clips":    rows,
    }
