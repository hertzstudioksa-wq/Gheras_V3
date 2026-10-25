"""Generation orchestrator — Phase 6A.

Responsibilities:
  * Create generation_jobs (cover + scene_image × N + narration × N + book_asset × N).
  * Process jobs sequentially with retry (max_attempts=3) and simple backoff.
  * Persist outputs into scene_images / narration_assets / book_assets collections.
  * Update order status: production_approved → assets_generating → assets_ready / media_failed.

Design principles:
  * Every provider call is abstracted (image_generation_service / audio_generation_service).
  * Every job records: attempt_count, provider, error_message, target_id.
  * Failures are isolated; order fails only if mandatory assets can't complete after retries.
"""
import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone

from db import db
from models import OrderStatus, ORDER_STATUS_AR, get_order_output_type
from storage import put_object, APP_NAME
from services.ai import AIPermanentError
from services.image_generation_service import generate_image
from services.audio_generation_service import generate_audio, estimate_duration_seconds
from services.tts_service import narration_voice_for_order
from services.config_service import resolve_prompt
from services.child_character_service import safe_run as run_child_character_stage, _fetch_source_bytes
from services.extra_characters_service import safe_run as run_extra_characters_stage
from services.scene_reference_service import resolve_scene_references
from services.video_generation_service import (
    submit_clip, poll_and_download, video_real_call_available,
)
from services.music_generation_service import (
    generate_music, music_real_call_available,
)
from services.config_service import get_pipeline_config
from services import shot_pipeline
from services.ai.image_client import WIDE

logger = logging.getLogger("generation_orchestrator")


def _safe_dict(value) -> dict:
    """Return value if it's a dict, else empty dict. Defensive read for fields
    whose schema has drifted across plan versions (e.g. video_prompt stored as
    string by new Claude prompts, dict by older fallback)."""
    return value if isinstance(value, dict) else {}


def _safe_dict_or_str(value):
    """Like _safe_dict but preserves a non-empty string so the caller can
    branch (dict vs string). Empty/None → empty string."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        return value
    return ""



MAX_ATTEMPTS = 3
# Job providers that mean "no real asset was produced" (dev mocks, legacy
# placeholders). Mandatory jobs with these never count as ready.
NON_DELIVERABLE_PROVIDERS = {"mock", "fallback", "placeholder"}


class PermanentJobError(RuntimeError):
    """A job failure that retrying cannot fix (e.g. its input asset is missing)."""


async def _run_video_generation_stage(order: dict, plan: dict, run_id: str) -> dict:
    """Phase L — fal.ai Kling per-scene video generation.

    Honest gates:
      * output_type must include video
      * pipeline_config.video_generation.enabled must be True
      * video_real_call_available() must be True (provider+key resolved)
    On any miss, returns {"ran": False, "reason": ...} — the assembly stage
    will fall back to the existing slideshow path automatically.
    """
    output_type = get_order_output_type(order)
    if output_type not in ("video", "both"):
        return {"ran": False, "reason": "output_type does not include video"}

    cfg = await get_pipeline_config()
    stage_cfg = (cfg.get("stages") or {}).get("video_generation") or {}
    if not stage_cfg.get("enabled", False):
        return {"ran": False, "reason": "video_generation disabled in pipeline_config"}

    if not await video_real_call_available():
        return {"ran": False, "reason": "FAL_KEY missing or provider not callable"}

    scenes = await db.scene_plans.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "is_archived": False},
        {"_id": 0},
    ).sort("scene_index", 1).to_list(50)
    if not scenes:
        return {"ran": False, "reason": "no scenes"}

    # Build scene packages — hybrid I2V/T2V driven by whether a scene image exists.
    sis = await db.scene_images.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "kind": "scene"},
        {"_id": 0, "scene_index": 1, "image_url": 1},
    ).to_list(50)
    img_by_idx = {int(s.get("scene_index") or 0): s.get("image_url") for s in sis}

    from services.ai import fal

    payloads: list[dict] = []
    skipped_scenes: list[int] = []
    for s in scenes:
        idx = int(s.get("scene_index") or 0)
        local_img = img_by_idx.get(idx)
        # Kling fetches its input by URL, and our /api/uploads URLs need auth,
        # so the scene illustration goes to fal's CDN (1-day expiry) first. No
        # text-only clips: without the illustration the child's likeness is lost.
        src = await _fetch_source_bytes(local_img) if local_img else None
        if not src:
            skipped_scenes.append(idx)
            continue
        try:
            public_img = await fal.upload(env_key="FAL_KEY_VIDEO", data=src[0],
                                          content_type=src[1] or "image/png", file_name=f"scene{idx}.png")
        except Exception as e:  # noqa: BLE001 — that scene falls back to its still image in assembly
            logger.warning(f"[video_generation] scene {idx} upload failed: {e}")
            skipped_scenes.append(idx)
            continue
        ip = _safe_dict(s.get("image_prompt")).get("prompt_text") or ""
        vp_obj = _safe_dict_or_str(s.get("video_prompt"))
        vp = vp_obj.get("prompt_text") if isinstance(vp_obj, dict) else (vp_obj or "")
        prompt = (vp or ip or s.get("visual_description") or s.get("scene_goal") or "warm storybook scene")
        # Include emotional_tone + camera hint to help motion direction.
        cam = vp_obj.get("camera_motion_hint") if isinstance(vp_obj, dict) else ""
        if cam:
            prompt = f"{prompt}. Camera: {cam}"
        payloads.append({
            "prompt":        prompt[:480],
            "image_url":     public_img,
            "duration":      5,
            "aspect_ratio":  "16:9",
            "_scene_index":  idx,
            "_scene_id":     s.get("id"),
        })

    logger.info(f"[video_generation] submitting {len(payloads)} clips order={order['id']} "
                f"(no clip, still image instead: scenes {skipped_scenes or 'none'})")
    if not payloads:
        return {"ran": False, "reason": "no scene images available for clips"}

    # Phase N hardening — pre-create video_clips rows in `submitted` state with
    # request_id PERSISTED IMMEDIATELY after submit. This guarantees that if
    # the process crashes mid-poll OR the poll loop times out, we still have
    # a paper-trail (request_id + model + scene_index) so the admin can later
    # recover the result via /api/admin/orders/{id}/video-clips/import-by-request-id.
    submitted_rows: list[dict] = []
    for sc in payloads:
        req_id, sub_meta = await submit_clip(sc)
        submitted_rows.append({
            "scene_payload": sc,
            "request_id":    req_id,
            "sub_meta":      sub_meta,
        })
        # Persist as soon as the request_id exists — even if it's None we still
        # mark the row as 'submit_failed' so the storyboard surfaces the truth.
        await db.video_clips.update_one(
            {"order_id": order["id"], "scene_index": sc["_scene_index"]},
            {"$set": {
                "id":                 str(uuid.uuid4()) if True else None,  # noqa: SIM222
                "order_id":           order["id"],
                "production_plan_id": plan["id"],
                "scene_plan_id":      sc["_scene_id"],
                "scene_index":        sc["_scene_index"],
                "run_id":             run_id,
                "provider":           sub_meta.get("provider") or "kling",
                "model":              sub_meta.get("model") or sub_meta.get("endpoint_used"),
                "request_id":         req_id,
                "submit_state":       "submitted" if req_id else "submit_failed",
                "submit_error":       None if req_id else sub_meta.get("error"),
                "import_status":      "pending" if req_id else "submit_failed",
                "submitted_at":       _now(),
                "updated_at":         _now(),
            }, "$setOnInsert": {"created_at": _now()}},
            upsert=True,
        )

    # Now run a poll-only loop using the request_ids we just persisted.
    poll_input = [
        {
            "index":      i,
            "scene":      row["scene_payload"],
            "request_id": row["request_id"],
            "meta":       row["sub_meta"],
            "model":      row["sub_meta"].get("model"),
            "state":      "IN_QUEUE" if row["request_id"] else "FAILED",
            "info":       {},
        }
        for i, row in enumerate(submitted_rows)
    ]
    results = await poll_and_download(poll_input, max_wait_s=900, poll_interval_s=10)

    # Persist clips and per-scene results.
    saved = 0
    for r, sc in zip(results, payloads):
        # Patch the request_id from our pre-submit if the lib lost it.
        if not r.get("request_id"):
            row = next((x for x in submitted_rows if x["scene_payload"]["_scene_index"] == sc["_scene_index"]), None)
            if row and row.get("request_id"):
                r["request_id"] = row["request_id"]
        clip_url: str | None = None
        if r.get("bytes"):
            file_id = str(uuid.uuid4())
            storage_path = f"{APP_NAME}/orders/{order['id']}/generated/clips/{file_id}.mp4"
            loop = asyncio.get_running_loop()
            try:
                stored = await loop.run_in_executor(
                    None, lambda: put_object(storage_path, r["bytes"], r["mime"]),
                )
                await db.files.insert_one({
                    "id": file_id,
                    "user_id": order.get("user_id"),
                    "scope": "generated-video-clip",
                    "storage_path": stored.get("path", storage_path),
                    "original_filename": f"scene-{sc['_scene_index']:02d}.mp4",
                    "content_type": r["mime"],
                    "size": stored.get("size", len(r["bytes"])),
                    "is_deleted": False,
                    "created_at": _now(),
                })
                clip_url = f"/api/uploads/file/{file_id}"
                saved += 1
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[video_generation] storage failed: {e}")

        # Phase N — derive a stable import_status from the result.
        meta_dict = r.get("meta") or {}
        if clip_url:
            import_status = "imported"
            fallback_reason = None
        elif r.get("video_url"):
            # fal.ai succeeded but our download failed → recoverable.
            import_status = "import_failed_remote_url_only"
            fallback_reason = "download_failed_after_completion"
        elif meta_dict.get("fallback_to_mock"):
            import_status = "fallback"
            fallback_reason = meta_dict.get("error") or f"final_state={r.get('state')}"
        elif r.get("request_id"):
            import_status = "submitted_no_result"
            fallback_reason = meta_dict.get("error") or f"final_state={r.get('state')}"
        else:
            import_status = "submit_failed"
            fallback_reason = meta_dict.get("error") or "no_request_id"

        await db.video_clips.update_one(
            {"order_id": order["id"], "scene_index": sc["_scene_index"]},
            {"$set": {
                "production_plan_id": plan["id"],
                "scene_plan_id":     sc["_scene_id"],
                "run_id":            run_id,
                "provider":          meta_dict.get("provider") or "kling",
                "model":             meta_dict.get("model") or meta_dict.get("endpoint_used"),
                "clip_strategy":     meta_dict.get("clip_strategy"),
                "request_id":        r.get("request_id"),
                "state":             r.get("state"),
                "video_url":         clip_url,
                "remote_video_url":  r.get("video_url"),
                "duration_seconds":  sc.get("duration") or 5,
                "aspect_ratio":      sc.get("aspect_ratio") or "16:9",
                "fallback_to_mock":  bool(meta_dict.get("fallback_to_mock")),
                "real_call":         bool(meta_dict.get("real_call")),
                "error":             meta_dict.get("error"),
                "import_status":     import_status,
                "fallback_reason":   fallback_reason,
                "imported_at":       _now() if import_status == "imported" else None,
                "updated_at":        _now(),
            }, "$setOnInsert": {"created_at": _now(), "id": str(uuid.uuid4())}},
            upsert=True,
        )

    await db.orders.update_one(
        {"id": order["id"]},
        {"$set": {
            "video_generation_summary": {
                "total":    len(payloads),
                "saved":    saved,
                "failed":   len(payloads) - saved,
                "run_id":   run_id,
                "ran_at":   _now(),
            },
        }},
    )
    return {"ran": True, "saved": saved, "total": len(payloads)}


async def _run_music_generation_stage(order: dict, plan: dict, run_id: str) -> dict:
    """Phase M — per-story ElevenLabs Music background track.

    Honest gates:
      * pipeline_config.music_generation.enabled must be True
      * audio_background_mode must NOT be 'none'
      * music_real_call_available() must be True (key present)
    On any miss → records a `music_tracks` row with skip_reason and returns
    {"ran": False, ...}. The assembly stage will produce video without music.
    """
    cfg = await get_pipeline_config()
    stage_cfg = (cfg.get("stages") or {}).get("music_generation") or {}
    if not stage_cfg.get("enabled", False):
        return {"ran": False, "reason": "music_generation disabled in pipeline_config"}

    audio_mode = (plan.get("audio_background") or {}).get("mode") or \
                 (order.get("data") or {}).get("audio_background_mode") or "music"

    # Always persist a row so storyboard can show the requested vs actual mode.
    track_id = str(uuid.uuid4())
    base = {
        "id":                  track_id,
        "order_id":            order["id"],
        "production_plan_id":  plan["id"],
        "run_id":              run_id,
        "requested_mode":      audio_mode,
        "actual_mode":         audio_mode,
        "created_at":          _now(),
        "updated_at":          _now(),
    }

    if audio_mode == "none":
        await db.music_tracks.insert_one({
            **base, "actual_mode": "none", "skipped": True,
            "skip_reason": "mode_none",
            "audio_url": None, "duration_seconds": 0,
            "provider": "skipped", "model": None, "real_call": False,
            "mode_implementation": "skipped_by_request",
        })
        return {"ran": False, "reason": "audio_background_mode=none"}

    if not await music_real_call_available():
        await db.music_tracks.insert_one({
            **base, "skipped": True,
            "skip_reason": "missing_key",
            "audio_url": None, "duration_seconds": 0,
            "provider": "elevenlabs", "model": None, "real_call": False,
            "mode_implementation": "skipped_missing_key",
            "error": "ELEVENLABS_API_KEY not configured",
        })
        return {"ran": False, "reason": "missing_key"}

    # Estimate duration from scene plans.
    scenes = await db.scene_plans.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "is_archived": False},
        {"_id": 0, "estimated_duration_seconds": 1},
    ).to_list(50)
    total_dur = int(sum((s.get("estimated_duration_seconds") or 6) for s in scenes)) + 5
    shot_len = await shot_pipeline.story_seconds(order["id"], plan["id"])
    if shot_len:
        total_dur = int(shot_len) + 2  # the real narrated length of a shot story

    story_keywords = (plan.get("story_keywords") or [])[:6]
    emotional_arc = plan.get("emotional_arc") or plan.get("story_summary")
    base_prompt = (plan.get("story_music_prompt")
                   or _safe_dict(plan.get("music_prompt")).get("prompt_text"))

    audio_bytes, mime, meta = await generate_music(
        audio_background_mode=audio_mode,
        base_prompt=base_prompt,
        duration_seconds=total_dur,
        story_keywords=story_keywords,
        emotional_arc=emotional_arc,
    )

    # Persist audio if any.
    audio_url = None
    if audio_bytes:
        file_id = str(uuid.uuid4())
        storage_path = f"{APP_NAME}/orders/{order['id']}/generated/music/{file_id}.mp3"
        loop = asyncio.get_running_loop()
        try:
            stored = await loop.run_in_executor(
                None, lambda: put_object(storage_path, audio_bytes, mime),
            )
            await db.files.insert_one({
                "id": file_id,
                "user_id": order.get("user_id"),
                "scope": "generated-music",
                "storage_path": stored.get("path", storage_path),
                "original_filename": "music.mp3",
                "content_type": mime,
                "size": stored.get("size", len(audio_bytes)),
                "is_deleted": False,
                "created_at": _now(),
            })
            audio_url = f"/api/uploads/file/{file_id}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[music_generation] storage failed: {e}")
            meta["storage_error"] = f"{type(e).__name__}: {e}"

    skip_reason = meta.get("skip_reason")
    skipped = (audio_url is None) or (skip_reason in ("plan_required", "auth_failed", "provider_unavailable"))

    await db.music_tracks.insert_one({
        **base,
        "skipped":             bool(skipped),
        "skip_reason":         skip_reason if skipped else None,
        "audio_url":           audio_url,
        "duration_seconds":    meta.get("duration_seconds") or total_dur,
        "provider":            meta.get("provider"),
        "model":               meta.get("model"),
        "real_call":           bool(meta.get("real_call")),
        "mode_implementation": meta.get("mode_implementation"),
        "prompt_used":         meta.get("prompt_used"),
        "error":               meta.get("error"),
        "latency_ms":          meta.get("latency_ms"),
        "bytes":               meta.get("bytes"),
    })
    await db.orders.update_one(
        {"id": order["id"]},
        {"$set": {"music_generation_summary": {
            "skipped": bool(skipped),
            "skip_reason": skip_reason if skipped else None,
            "audio_url": audio_url,
            "duration_seconds": meta.get("duration_seconds"),
            "provider": meta.get("provider"),
            "ran_at": _now(),
        }}},
    )
    return {"ran": not skipped, "audio_url": audio_url, "skip_reason": skip_reason}


BACKOFF_SECONDS = [1, 3, 7]  # between attempts (index = attempt_count - 1)


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
    from services.notify_service import on_status
    on_status(order_id, to_status)


# ---------------- Job creation ----------------
async def _plan_jobs(order: dict) -> list[dict]:
    """Inspect approved plan and return a list of job descriptors to create."""
    plan_id = order.get("production_plan_id")
    plan = await db.production_plans.find_one({"id": plan_id}, {"_id": 0}) if plan_id else None
    if not plan:
        return []
    scenes = await db.scene_plans.find(
        {"order_id": order["id"], "production_plan_id": plan_id, "is_archived": False},
        {"_id": 0},
    ).sort("scene_index", 1).to_list(50)
    pages = await db.book_pages.find(
        {"order_id": order["id"], "production_plan_id": plan_id, "is_archived": False},
        {"_id": 0},
    ).sort("page_number", 1).to_list(50)

    jobs = []
    output_type = get_order_output_type(order)
    needs_video = output_type in ("video", "both")
    needs_pdf = output_type in ("pdf", "both")

    # 1 cover image — always (used by both video and PDF cover page)
    jobs.append({
        "job_type": "cover_image",
        "target_id": plan["id"],
        "meta": {"plan_id": plan["id"]},
    })
    # Shot plans: one keyframe per shot, drawn scene by scene (the first shot
    # also illustrates the book page). Legacy plans: one image per scene.
    image_job = "scene_keyframes" if shot_pipeline.has_shots(scenes) else "scene_image"
    for s in scenes:
        jobs.append({"job_type": image_job, "target_id": s["id"], "meta": {"scene_index": s["scene_index"]}})
    # narration audio (1 per scene) — only when video is requested.
    # (Wave 1 PDF is text + image; narration is only consumed by the video.)
    if needs_video:
        for s in scenes:
            jobs.append({"job_type": "narration_audio", "target_id": s["id"], "meta": {"scene_index": s["scene_index"]}})
    # book_asset (1 per page) — only when PDF is requested.
    if needs_pdf:
        for p in pages:
            jobs.append({"job_type": "book_page_asset", "target_id": p["id"], "meta": {"page_number": p["page_number"]}})
    return jobs


async def _insert_jobs(order_id: str, run_id: str, jobs: list[dict]) -> list[dict]:
    docs = []
    for j in jobs:
        docs.append({
            "id": str(uuid.uuid4()),
            "order_id": order_id,
            "run_id": run_id,
            "job_type": j["job_type"],
            "target_id": j["target_id"],
            "meta": j.get("meta", {}),
            "status": "queued",
            "provider": None,
            "attempt_count": 0,
            "max_attempts": MAX_ATTEMPTS,
            "error_message": None,
            "output_url": None,
            "output_metadata": None,
            "created_at": _now(),
            "updated_at": _now(),
        })
    if docs:
        await db.generation_jobs.insert_many(docs)
    return docs


async def _update_job(job_id: str, patch: dict):
    patch["updated_at"] = _now()
    await db.generation_jobs.update_one({"id": job_id}, {"$set": patch})


async def _save_image_to_storage(order_id: str, kind: str, image_bytes: bytes, mime: str, user_id: str) -> str:
    """Save image bytes to object storage + files collection, return served URL."""
    file_id = str(uuid.uuid4())
    ext = "png" if "png" in mime else "jpg"
    storage_path = f"{APP_NAME}/orders/{order_id}/generated/{kind}/{file_id}.{ext}"
    # put_object is synchronous (requests); run in threadpool to avoid blocking loop
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: put_object(storage_path, image_bytes, mime))
    await db.files.insert_one({
        "id": file_id,
        "user_id": user_id,
        "scope": f"generated-{kind}",
        "storage_path": result.get("path", storage_path),
        "original_filename": f"{kind}.{ext}",
        "content_type": mime,
        "size": result.get("size", len(image_bytes)),
        "is_deleted": False,
        "created_at": _now(),
    })
    return f"/api/uploads/file/{file_id}"


# ---------------- Per-job executors ----------------
async def _execute_cover_image(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    # A resumed or retried run keeps the cover it already drew for this plan
    # (the admin's "regenerate media" clears it first).
    drawn = await db.scene_images.find_one({"order_id": order["id"], "production_plan_id": plan["id"], "kind": "cover"},
                                           {"_id": 0, "image_url": 1, "provider": 1}, sort=[("created_at", -1)])
    if drawn and drawn.get("image_url"):
        return drawn["image_url"], {"provider": drawn.get("provider"), "reused": True}
    shot_plan = bool(await db.scene_plans.find_one(
        {"production_plan_id": plan["id"], "shots.0": {"$exists": True}}, {"_id": 1}))
    if shot_plan:
        # The whole cast with their sheets (a cover drawn from the child's sheet
        # alone invented the other characters' faces).
        prompt, references, _cast = await shot_pipeline.cover_request(order, plan)
        image_bytes, mime, meta = await generate_image(
            scene_prompt=prompt, references=references or None, size=WIDE, quality="high", raw_prompt=True,
            session_hint=f"cover-{order['id'][:6]}")
        return await _store_cover(job, order, plan, image_bytes, mime, meta)

    prompt = plan.get("cover_prompt") or f"Book cover for children's story: {plan.get('title','')}"
    references = []
    child_asset = await db.child_character_assets.find_one(
        {"order_id": order["id"], "status": "completed", "generated_image_url": {"$ne": None}}, {"_id": 0})
    if child_asset:
        ref = await _fetch_source_bytes(child_asset["generated_image_url"])
        if ref:
            references.append({"image_bytes": ref[0], "mime_type": ref[1], "kind": "child",
                               "name": ((order.get("data") or {}).get("child") or {}).get("name")})
    image_bytes, mime, meta = await generate_image(
        size="1024x1024",
        quality="high",  # the cover is the PDF front page and the video thumbnail
        scene_prompt=prompt,
        style_guide=plan.get("style_guide"),
        character_note="",
        session_hint=f"cover-{order['id'][:6]}",
        references=references or None,
        prompt_augmentation=("The child on the cover is the child in the reference image: keep the same "
                             "face, hair and skin tone." if references else ""),
    )
    return await _store_cover(job, order, plan, image_bytes, mime, meta)


async def _store_cover(job: dict, order: dict, plan: dict, image_bytes: bytes, mime: str, meta: dict) -> tuple[str, dict]:
    url = await _save_image_to_storage(order["id"], "cover", image_bytes, mime, order["user_id"])
    # The cover lives in scene_images with scene_plan_id=None and kind="cover".
    await db.scene_images.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "scene_plan_id": None,
        "generation_job_id": job["id"],
        "kind": "cover",
        "image_url": url,
        "prompt_used": meta.get("prompt_used"),
        "provider": meta.get("provider"),
        "source_type": meta.get("provider"),
        "model": meta.get("model"),
        "gpu_seconds": meta.get("gpu_seconds"),  # Comfy: what the cover cost
        "created_at": _now(),
    })
    return url, meta


def _build_scene_image_context(order: dict, plan: dict, scene: dict) -> dict:
    """Flat variable context for admin-configurable scene_image_generation prompt.

    Only fields that are actually available are exposed — no invented values.
    Lists are joined into comma-separated strings so $vars always stringify cleanly.
    """
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    duration = order.get("duration", {}) or {}
    child = data.get("child", {}) or {}
    pers = data.get("personalization", {}) or {}
    chars = data.get("characters", []) or []
    audio_bg = (data.get("audio_background") or {}).get("mode") or "music"

    img_prompt_obj = _safe_dict(scene.get("image_prompt"))

    # Phase D.3 — include auto-extracted visuals for uploaded assets.
    toy_desc = pers.get("toy_description_auto") or ""
    toy_name = ((pers.get("favorites") or {}).get("toy") or {}).get("name") or ""
    toy_block = ""
    if toy_desc or toy_name:
        toy_block = (f"{toy_name}: " if toy_name else "") + (toy_desc or "")
    extra_chars_visuals = "; ".join(
        f"{c.get('name') or c.get('type')}: {c['visual_description_auto']}"
        for c in chars
        if c.get("role") == "visible" and c.get("visual_description_auto")
    )

    return {
        # Child
        "child_name":         child.get("name", ""),
        "child_age":          child.get("age", ""),
        "child_gender":       "ولد" if child.get("gender") == "male" else "بنت",
        "child_appearance_notes": child.get("appearance_notes", "") or "",
        "child_hijab":        "نعم" if child.get("hijab") else "لا",
        # Scene
        "scene_index":        scene.get("scene_index", ""),
        "scene_title":        scene.get("title", ""),
        "scene_goal":         scene.get("scene_goal", ""),
        "narration_text":     scene.get("narration_text", ""),
        "book_text":          scene.get("book_text", ""),
        "emotional_tone":     scene.get("emotional_tone", ""),
        "visual_description": scene.get("visual_description", ""),
        "background_setting": scene.get("background_setting", ""),
        "key_objects":        ", ".join(scene.get("key_objects", []) or []) or "لا يوجد",
        "continuity_notes":   scene.get("continuity_notes", ""),
        # Plan-level
        "selected_scenario_title":           plan.get("title", ""),
        "selected_scenario_emotional_angle": plan.get("emotional_angle", "") or "",
        "selected_scenario_visual_style":    _safe_dict(plan.get("style_guide")).get("art_direction", ""),
        "style_guide":                       ", ".join(f"{k}:{v}" for k, v in _safe_dict(plan.get("style_guide")).items()) or "",
        "character_reference_note":          img_prompt_obj.get("character_reference_note", ""),
        # Style
        "story_type":  enriched.get("type_name", "") or "",
        "tone":        enriched.get("tone_name", "") or "",
        "setting":     enriched.get("setting_name", "") or "",
        "language":    enriched.get("language_name", "") or "",
        "voice":       enriched.get("voice_name", "") or "",
        # Duration
        "duration_label":   duration.get("label", ""),
        "duration_seconds": duration.get("seconds", ""),
        "scene_target":     duration.get("scene_target", ""),
        # Extras
        "favorites_summary":  "، ".join(
            f"{k}:{(v or {}).get('name','')}"
            for k, v in (pers.get("favorites") or {}).items() if (v or {}).get("selected")
        ) or "لا يوجد",
        "characters_summary": "، ".join(
            f"{c.get('type','')}:{c.get('name','')}" for c in chars if c.get("name")
        ) or "لا يوجد",
        "extra_characters_visuals": extra_chars_visuals or "لا يوجد",
        "toy_summary":             toy_block or "لا يوجد",
        "audio_background_mode":   audio_bg,
    }


async def _resolve_scene_image_prompt(order: dict, plan: dict, scene: dict) -> tuple[str | None, str, str]:
    """Try admin template; returns (rendered, source, reason). On any failure
    the caller uses the hardcoded `scene.image_prompt.prompt_text` from DB.
    """
    try:
        ctx = _build_scene_image_context(order, plan, scene)
    except Exception as e:  # noqa: BLE001 — never crash the pipeline
        return None, "default", f"context_error:{type(e).__name__}"
    return await resolve_prompt("scene_image_generation", ctx)


async def _execute_scene_image(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    scene = await db.scene_plans.find_one({"id": job["target_id"]}, {"_id": 0})
    if not scene:
        raise ValueError(f"scene_plan {job['target_id']} not found")
    default_prompt = _safe_dict(scene.get("image_prompt")).get("prompt_text") or scene.get("visual_description") or ""
    char_note = _safe_dict(scene.get("image_prompt")).get("character_reference_note") or ""

    # Phase B.3 — admin prompt override (scene-level, falls back cleanly).
    admin_prompt, prompt_src, reason = await _resolve_scene_image_prompt(order, plan, scene)
    if prompt_src == "admin":
        logger.info(f"[config] stage=scene_image_generation prompt_source=admin {reason}")
        img_prompt = admin_prompt
    else:
        logger.info(f"[config] stage=scene_image_generation prompt_source=default reason={reason}")
        img_prompt = default_prompt

    # Phase D.3 — auto-inject uploaded toy/object and extra-character visual
    # descriptions so they appear in scenes. Appended only when present;
    # legacy orders with no uploads are unaffected.
    data = order.get("data") or {}
    pers = data.get("personalization") or {}
    toy_desc = pers.get("toy_description_auto") or ""
    toy_name = ((pers.get("favorites") or {}).get("toy") or {}).get("name") or ""
    if toy_desc or toy_name:
        if toy_name and toy_name.lower() in (img_prompt or "").lower():
            # toy is already referenced in the prompt — only inject the visual detail
            img_prompt = (img_prompt or "") + f" Visual reference for {toy_name}: {toy_desc}" if toy_desc else img_prompt
        else:
            pref = f" Important recurring object: {toy_name + ' — ' if toy_name else ''}{toy_desc}".rstrip()
            img_prompt = (img_prompt or "") + pref
    extra_visuals = [
        f"{(c.get('name') or c.get('type'))}: {c['visual_description_auto']}"
        for c in (data.get("characters") or [])
        if c.get("role") == "visible" and c.get("visual_description_auto")
    ]
    if extra_visuals:
        img_prompt = (img_prompt or "") + " Extra characters visual hints — " + " | ".join(extra_visuals)

    # Phase E — Reference Asset Injection -----------------------------------
    # Resolve which existing reference images (child/extras/toy) belong in this
    # scene, then fetch their bytes from internal storage. Failures are
    # recorded as granular `skipped_reasons` so the storyboard shows the truth.
    ref_pkg = await resolve_scene_references(order, plan, scene)
    ref_payload: list[dict] = []
    ref_skipped: list[dict] = list(ref_pkg.get("skipped_reasons") or [])

    async def _attach(kind: str, ref: dict | None):
        if not ref or not ref.get("url"):
            return
        bytes_tuple = await _fetch_source_bytes(ref["url"])
        if not bytes_tuple:
            ref_skipped.append({
                "kind": kind, "id": ref.get("character_id"),
                "character_index": ref.get("character_index"),
                "name": ref.get("name"),
                "reason": "reference_fetch_failed",
            })
            return
        ref_payload.append({
            "image_bytes": bytes_tuple[0],
            "mime_type":   bytes_tuple[1],
            "kind":        kind,
            "name":        ref.get("name"),
        })

    await _attach("child", ref_pkg.get("child_ref"))
    for r in ref_pkg.get("extra_char_refs") or []:
        await _attach("extra", r)
    await _attach("toy", ref_pkg.get("toy_ref"))

    image_bytes, mime, meta = await generate_image(
        scene_prompt=img_prompt,
        style_guide=plan.get("style_guide"),
        character_note=char_note,
        session_hint=f"scene-{scene.get('scene_index')}-{order['id'][:6]}",
        references=ref_payload,
        support_true_refs=True,
        prompt_augmentation=ref_pkg.get("prompt_augmentation", ""),
    )
    url = await _save_image_to_storage(order["id"], "scene", image_bytes, mime, order["user_id"])

    # Phase E — record reference usage on scene_plans for storyboard + cost.
    log_extra_ids = [r.get("character_id") for r in ref_pkg.get("extra_char_refs", []) if r.get("character_id")]
    log_extra_idxs = [r.get("character_index") for r in ref_pkg.get("extra_char_refs", [])
                      if r.get("character_index") is not None]
    scene_ref_log = {
        "available": ref_pkg.get("available", {}),
        "child_reference_used":             bool(ref_pkg.get("child_ref")),
        "extra_character_reference_ids_used":   log_extra_ids,
        "extra_character_reference_indexes_used": log_extra_idxs,
        "toy_reference_used":               bool(ref_pkg.get("toy_ref")),
        "references_injected_count":        meta.get("references_count", 0) if meta.get("references_used") else 0,
        "references_attempted":             bool(meta.get("references_attempted")),
        "references_used":                  bool(meta.get("references_used")),
        "fallback_path":                    meta.get("fallback_path"),
        "fallback_reason":                  meta.get("fallback_reason"),
        "skipped_reasons":                  ref_skipped,
        "final_effective_image_prompt":     meta.get("prompt_used"),
        "updated_at":                       _now(),
    }
    await db.scene_plans.update_one(
        {"id": scene["id"]},
        {"$set": {"scene_reference_log": scene_ref_log}},
    )

    await db.scene_images.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "scene_plan_id": scene["id"],
        "generation_job_id": job["id"],
        "kind": "scene",
        "scene_index": scene.get("scene_index"),
        "image_url": url,
        "prompt_used": meta.get("prompt_used"),
        "provider": meta.get("provider"),
        "source_type": meta.get("provider"),
        "references_used": bool(meta.get("references_used")),
        "references_count": meta.get("references_count", 0),
        "reference_fallback_path": meta.get("fallback_path"),
        "created_at": _now(),
    })
    return url, meta


async def _execute_narration_audio(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    scene = await db.scene_plans.find_one({"id": job["target_id"]}, {"_id": 0})
    if not scene:
        raise ValueError(f"scene_plan {job['target_id']} not found")
    if scene.get("shots"):
        return await shot_pipeline.execute_scene_narration(job, order, plan)
    text = scene.get("narration_text") or ""
    voice = await narration_voice_for_order(order)
    language = (order.get("enriched") or {}).get("language_name") or "ar"

    # Phase N — Smart Narration voice settings.
    from services.smart_narration_service import compute_voice_settings
    audio_bg = (
        (order.get("data") or {}).get("audio_background", {}).get("mode")
        or (plan.get("audio_background") or {}).get("mode")
        or "music"
    )
    smart = await compute_voice_settings(
        narration_text=text,
        emotional_tone=scene.get("emotional_tone"),
        audio_background_mode=audio_bg,
        scene_index=scene.get("scene_index"),
        duration_label=(order.get("duration") or {}).get("label"),
    )
    # Strip metadata fields before passing to adapter.
    tts_settings = {k: smart[k] for k in ("speed", "stability", "similarity_boost", "style")
                    if k in smart}

    audio_bytes, mime, meta = await generate_audio(
        text=text, voice=voice, language=language,
        voice_settings=tts_settings,
    )
    # Surface the smart-narration decision in meta for the storyboard.
    meta["smart_narration"] = {
        "source":  smart.get("source"),
        "reason":  smart.get("reason"),
        "model":   smart.get("model"),
        "settings": tts_settings,
    }
    # In mock mode audio_bytes is None. Persist metadata-only record with URL=None.
    url = None
    if audio_bytes:
        # (Reserved for real provider): upload bytes to storage.
        file_id = str(uuid.uuid4())
        ext = "mp3" if "mpeg" in mime else "wav"
        storage_path = f"{APP_NAME}/orders/{order['id']}/generated/audio/{file_id}.{ext}"
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: put_object(storage_path, audio_bytes, mime))
        await db.files.insert_one({
            "id": file_id,
            "user_id": order["user_id"],
            "scope": "generated-audio",
            "storage_path": result.get("path", storage_path),
            "original_filename": f"narration.{ext}",
            "content_type": mime,
            "size": result.get("size", len(audio_bytes)),
            "is_deleted": False,
            "created_at": _now(),
        })
        url = f"/api/uploads/file/{file_id}"
    duration = meta.get("duration_seconds") or estimate_duration_seconds(text)
    await db.narration_assets.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "scene_plan_id": scene["id"],
        "generation_job_id": job["id"],
        "scene_index": scene.get("scene_index"),
        "text": text,
        "voice_type": meta.get("voice"),
        "language": language,
        "audio_url": url,
        "duration_seconds": duration,
        "provider": meta.get("provider"),
        "smart_narration": meta.get("smart_narration"),
        "voice_settings_used": tts_settings,
        "created_at": _now(),
    })
    return url or f"(mock) {duration}s", meta


async def _execute_book_page_asset(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    page = await db.book_pages.find_one({"id": job["target_id"]}, {"_id": 0})
    if not page:
        raise ValueError(f"book_page {job['target_id']} not found")
    # Reuse scene image for the same scene_index (Phase 6A rule).
    scene_img = await db.scene_images.find_one(
        {"order_id": order["id"], "production_plan_id": plan["id"],
         "scene_index": page.get("scene_index"), "kind": "scene"},
        {"_id": 0},
    )
    illustration_url = scene_img.get("image_url") if scene_img else None
    if not illustration_url:
        raise PermanentJobError(f"no scene image to reuse for page {page.get('page_number')}")
    provider = "reused"
    # A resumed run keeps the page row (and its cached tashkeel) when nothing changed.
    existing = await db.book_assets.find_one({"order_id": order["id"], "production_plan_id": plan["id"],
                                              "book_page_id": page["id"]}, {"_id": 0, "id": 1, "illustration_url": 1})
    if existing and existing.get("illustration_url") == illustration_url:
        return illustration_url, {"provider": provider}
    await db.book_assets.delete_many({"order_id": order["id"], "production_plan_id": plan["id"],
                                      "book_page_id": page["id"]})
    await db.book_assets.insert_one({
        "id": str(uuid.uuid4()),
        "order_id": order["id"],
        "production_plan_id": plan["id"],
        "book_page_id": page["id"],
        "generation_job_id": job["id"],
        "page_number": page.get("page_number"),
        "scene_index": page.get("scene_index"),
        "illustration_url": illustration_url,
        "page_text": page.get("text"),
        "provider": provider,
        "created_at": _now(),
    })
    return illustration_url, {"provider": provider}


# ---------------- Job dispatcher ----------------
JOB_EXECUTORS = {
    "cover_image": _execute_cover_image,
    "scene_image": _execute_scene_image,
    "scene_keyframes": shot_pipeline.execute_scene_keyframes,
    "narration_audio": _execute_narration_audio,
    "book_page_asset": _execute_book_page_asset,
}


async def _process_job_with_retry(job: dict, order: dict, plan: dict) -> bool:
    executor = JOB_EXECUTORS.get(job["job_type"])
    if not executor:
        await _update_job(job["id"], {"status": "failed", "error_message": f"unknown job_type {job['job_type']}"})
        return False

    for attempt in range(1, MAX_ATTEMPTS + 1):
        await _update_job(job["id"], {"status": "processing", "attempt_count": attempt})
        try:
            output, meta = await executor(job, order, plan)
            await _update_job(job["id"], {
                "status": "completed",
                "provider": meta.get("provider"),
                "output_url": output if isinstance(output, str) else None,
                "output_metadata": meta,
                "error_message": None,
            })
            return True
        except Exception as e:
            err = f"attempt {attempt} failed: {type(e).__name__}: {e}"
            logger.warning(f"job {job['id']} ({job['job_type']}) {err}")
            await _update_job(job["id"], {"error_message": err})
            # Missing credits/keys or a missing input won't fix themselves on retry.
            if isinstance(e, (AIPermanentError, PermanentJobError)):
                await _update_job(job["id"], {"status": "failed"})
                return False
            if attempt < MAX_ATTEMPTS:
                await asyncio.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
            else:
                await _update_job(job["id"], {"status": "failed"})
                return False
    return False


async def _extras_stage(order: dict) -> None:
    """extra_character_i2i: every visible relative with an uploaded photo.
    Always safe: per-character try/except in the service, plus this one."""
    try:
        ec_result = await run_extra_characters_stage(order)
        if ec_result.get("ran"):
            logger.info(f"[extra_character_i2i] processed count={ec_result.get('count')} "
                        f"results={[r.get('status') for r in (ec_result.get('results') or [])]}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[extra_character_i2i] unexpected crash (ignored): {e}")


async def _text_sheets(order: dict, plan: dict) -> None:
    """Sheets for cast members without a photo (drawn from the plan), alongside
    the photo-based ones; _run_shot_assets fills in anything still missing."""
    try:
        await shot_pipeline.ensure_character_sheets(order, plan, photo_free_only=True)
    except Exception as e:  # noqa: BLE001 — the later pass retries, keyframes fail loudly on a dead key
        logger.warning(f"[shots] order={order['id']} text-drawn sheets failed: {e}")


async def _run_jobs(jobs: list[dict], process) -> list[bool]:
    """Jobs one after another, in scene order."""
    results = []
    for job in sorted(jobs, key=lambda j: (j.get("meta") or {}).get("scene_index") or 0):
        results.append(await process(job))
    return results


async def _music_stage(order: dict, plan: dict, run_id: str) -> None:
    """One background track per video story. Optional by design: on a miss the
    track row records why, and the video is assembled without music."""
    if get_order_output_type(order) not in ("video", "both"):
        return
    try:
        music_result = await _run_music_generation_stage(order, plan, run_id)
        logger.info(f"[music_generation] order={order['id']} result={music_result}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[music_generation] unexpected crash (video continues without music): {e}")


async def _run_shot_assets(order: dict, plan: dict, run_id: str, jobs: list[dict], process,
                           narration_task: asyncio.Task) -> None:
    """Shot plans, overlapped instead of one stage after another:
      * narration was voiced while the sheets were drawn; music (it needs the
        narrated length) starts as soon as narration is done,
      * the cover is drawn alongside the keyframes,
      * keyframes go scene by scene (each shot sees the previous one), and a
        finished scene's shots go to Kling at once instead of after all scenes.
    Clip requests are saved before polling, so a restart still resumes them."""
    order_id = order["id"]
    # Draw a reference sheet for every cast member without one (e.g. the mother)
    # so they look the same in every shot.
    try:
        sheets = await shot_pipeline.ensure_character_sheets(order, plan)
        logger.info(f"[shots] order={order_id} character sheets: {sorted(sheets)}")
    except Exception as e:  # noqa: BLE001 — keyframes still run (and fail loudly on a dead key)
        logger.warning(f"[shots] order={order_id} character sheets failed: {e}")

    async def narration_then_music() -> None:
        await asyncio.gather(narration_task, return_exceptions=True)
        await _music_stage(order, plan, run_id)

    music_task = asyncio.create_task(narration_then_music())
    cover_tasks = [asyncio.create_task(process(j)) for j in jobs if j["job_type"] == "cover_image"]
    clip_sem = asyncio.Semaphore(shot_pipeline.CLIP_CONCURRENCY)
    clip_tasks = []

    async def scene(job: dict) -> None:
        if await process(job):
            await asyncio.gather(narration_task, return_exceptions=True)  # long done by now
            clip_tasks.append(asyncio.create_task(shot_pipeline.run_shot_clips(
                order, plan, run_id, scene_index=(job.get("meta") or {}).get("scene_index"), sem=clip_sem,
                summarize=False)))

    scene_jobs = sorted((j for j in jobs if j["job_type"] == "scene_keyframes"),
                        key=lambda j: (j.get("meta") or {}).get("scene_index") or 0)
    if (await shot_pipeline.keyframe_engine())[0] == "comfy_image":
        # Comfy keyframes don't need the scene before them (people shots take no
        # previous frame), and its queue serves keyframes before clips: every scene
        # waits in it at once, so the GPU never idles while a picture is reviewed.
        await asyncio.gather(*(scene(j) for j in scene_jobs))
    else:
        for job in scene_jobs:
            await scene(job)
    await _run_jobs([j for j in jobs if j["job_type"] == "book_page_asset"], process)
    await asyncio.gather(*cover_tasks, narration_task, return_exceptions=True)
    for res in await asyncio.gather(*clip_tasks, return_exceptions=True):
        if isinstance(res, Exception):
            logger.error(f"[shots] order={order_id} clip batch crashed: {type(res).__name__}: {res}")
    try:
        # Anything not animated yet (e.g. after a resume), then the summary.
        clips = await shot_pipeline.run_shot_clips(order, plan, run_id, sem=clip_sem)
        logger.info(f"[shots] order={order_id} clips={clips}")
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[video_generation] unexpected crash (ignored): {e}")
    await music_task


# ---------------- Run (entrypoint) ----------------
async def run_asset_generation(order_id: str, run_id: str):
    """The asset pipeline, with a heartbeat on the order (see order_heartbeat)."""
    from services.ai.fake_providers import CURRENT_ORDER
    from services.limits import wait_for_generation_slot
    from services.order_heartbeat import beating

    CURRENT_ORDER.set(order_id)  # Comfy's gate serves the oldest order first
    async with beating(order_id):
        # A busy day queues approved orders instead of starting them all at once.
        await wait_for_generation_slot(order_id)
        await _run_asset_generation(order_id, run_id)


async def _run_asset_generation(order_id: str, run_id: str):
    """Full pipeline — sequential dispatch of all jobs."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    if not order.get("production_approved"):
        logger.warning(f"run_asset_generation called for unapproved order {order_id}")
        return

    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0})
    if not plan:
        await _append_status(order_id, order.get("status"), OrderStatus.MEDIA_FAILED.value, "system",
                             reason="no production plan found")
        return

    # Create jobs
    job_descriptors = await _plan_jobs(order)
    if not job_descriptors:
        await _append_status(order_id, order.get("status"), OrderStatus.MEDIA_FAILED.value, "system",
                             reason="no jobs could be planned")
        return
    jobs = await _insert_jobs(order_id, run_id, job_descriptors)
    # A resumed or retried order starts a new run; the previous run's unfinished
    # jobs would otherwise sit in "queued" forever.
    await db.generation_jobs.update_many(
        {"order_id": order_id, "run_id": {"$ne": run_id}, "status": {"$in": ["queued", "processing"]}},
        {"$set": {"status": "superseded", "updated_at": _now()}},
    )

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {
            "asset_generation_run_id": run_id,
            "asset_generation_started_at": _now(),
            "asset_generation_summary": {
                "total": len(jobs),
                "queued": len(jobs),
                "processing": 0,
                "completed": 0,
                "failed": 0,
            },
        }},
    )
    await _append_status(order_id, order.get("status"), OrderStatus.ASSETS_GENERATING.value, "system",
                         reason=f"start assets generation (run {run_id[:8]}, {len(jobs)} jobs)")
    # The status now holds the generation slot (services/limits.py).
    await db.orders.update_one({"id": order_id}, {"$unset": {"generation_queue": 1}})

    shot_mode = any(j["job_type"] == "scene_keyframes" for j in jobs)

    async def process(job: dict) -> bool:
        ok = await _process_job_with_retry(job, order, plan)
        # $inc, not $set: shot runs process jobs concurrently.
        await db.orders.update_one({"id": order_id}, {
            "$inc": {f"asset_generation_summary.{'completed' if ok else 'failed'}": 1,
                     "asset_generation_summary.queued": -1},
            "$set": {"updated_at": _now()}})
        return ok

    # Shot plans: narration only needs the plan, so it's voiced while the
    # character sheets are drawn — every clip's length comes from its line.
    narration_task = asyncio.create_task(_run_jobs(
        [j for j in jobs if j["job_type"] == "narration_audio"], process)) if shot_mode else None

    # --- Character sheets, before any scene image ---------------------------
    # They don't depend on each other: the child's, the ones from relatives'
    # photos and the ones drawn from the plan run together (a five-person story
    # spent ~8 minutes drawing them one by one). When the child's sheet ran
    # (photo present, stage enabled) and failed, stop here: drawing the scenes
    # without the child's likeness would deliver a generic book and still spend
    # the whole image budget.
    extras_task = asyncio.create_task(_extras_stage(order))
    text_sheets_task = asyncio.create_task(_text_sheets(order, plan)) if shot_mode else None
    cc_result = await run_child_character_stage(order, plan)
    side_tasks = [t for t in (extras_task, text_sheets_task) if t]
    if cc_result.get("ran") and cc_result.get("status") != "completed":
        await asyncio.gather(*side_tasks, *([narration_task] if narration_task else []), return_exceptions=True)
        reason = f"child character failed: {cc_result.get('reason')}"
        logger.warning(f"[child_character_i2i] order={order_id} {reason}")
        # The jobs were planned before this stage; close them so they don't sit
        # in "queued" forever (storyboard, retries and summaries read them).
        await db.generation_jobs.update_many(
            {"order_id": order_id, "run_id": run_id, "status": "queued"},
            {"$set": {"status": "skipped", "error_message": reason[:300], "updated_at": _now()}},
        )
        await db.orders.update_one({"id": order_id}, {"$set": {
            "asset_generation_completed_at": _now(),
            "asset_generation_summary.queued": 0,
            "asset_generation_summary.skipped": len(jobs),
        }})
        await _append_status(order_id, OrderStatus.ASSETS_GENERATING.value, OrderStatus.MEDIA_FAILED.value,
                             "system", reason=reason[:300])
        return

    await asyncio.gather(*side_tasks, return_exceptions=True)

    if shot_mode:
        await _run_shot_assets(order, plan, run_id, jobs, process, narration_task)
    else:
        # Legacy scene-image plans: cover, scene images, narration, book assets.
        priority = {"cover_image": 0, "scene_image": 1, "narration_audio": 2, "book_page_asset": 3}
        jobs.sort(key=lambda j: (priority.get(j["job_type"], 9), j.get("meta", {}).get("scene_index", 0)))
        for job in jobs:
            await process(job)
        await _music_stage(order, plan, run_id)
        try:
            await _run_video_generation_stage(order, plan, run_id)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[video_generation] unexpected crash (ignored): {e}")
    completed = await db.generation_jobs.count_documents({"order_id": order_id, "run_id": run_id, "status": "completed"})

    # Decide terminal status
    # Mandatory job set depends on the requested deliverable:
    #   * video only → cover + scene_images + narration
    #   * pdf   only → cover + scene_images + book_assets
    #   * both       → cover + scene_images + narration + book_assets
    output_type = get_order_output_type(order)
    mandatory_types: set[str] = {"cover_image", "scene_image", "scene_keyframes"}
    if output_type in ("video", "both"):
        mandatory_types.add("narration_audio")
    if output_type in ("pdf", "both"):
        mandatory_types.add("book_page_asset")
    # A mandatory asset produced by a mock/placeholder path counts as failed:
    # it must never reach assembly and be announced as a finished story.
    failed_mandatory = await db.generation_jobs.count_documents({
        "order_id": order_id,
        "run_id": run_id,
        "job_type": {"$in": list(mandatory_types)},
        "$or": [
            {"status": "failed"},
            {"provider": {"$in": list(NON_DELIVERABLE_PROVIDERS)}},
        ],
    })
    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"asset_generation_completed_at": _now()}},
    )
    if failed_mandatory == 0:
        await _append_status(order_id, OrderStatus.ASSETS_GENERATING.value, OrderStatus.ASSETS_READY.value, "system",
                             reason=f"all assets ready ({completed}/{len(jobs)})")
    else:
        await _append_status(order_id, OrderStatus.ASSETS_GENERATING.value, OrderStatus.MEDIA_FAILED.value, "system",
                             reason=f"{failed_mandatory} mandatory jobs failed after retries")


async def retry_single_job(job_id: str) -> dict:
    """Admin endpoint can call this to retry a single failed job fresh."""
    job = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    if not job:
        return {"ok": False, "error": "job not found"}
    order = await db.orders.find_one({"id": job["order_id"]}, {"_id": 0})
    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0})
    # Reset counters and run
    await _update_job(job_id, {"status": "queued", "attempt_count": 0, "error_message": None, "output_url": None})
    # Re-fetch
    job = await db.generation_jobs.find_one({"id": job_id}, {"_id": 0})
    ok = await _process_job_with_retry(job, order, plan)
    return {"ok": ok}
