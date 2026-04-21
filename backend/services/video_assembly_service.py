"""Final video assembly — ffmpeg-based slideshow from scene images + silent audio tracks.

Phase 6B design:
  * Download scene images (in order) + cover image from storage.
  * Each scene's duration = narration_assets[scene].duration_seconds (or fallback 5s).
  * Produce a concatenated MP4 with:
      - cover shown for 2s as an intro
      - each scene image displayed for its estimated narration duration
      - silent audio track (real TTS/music comes in Phase 6C)
  * Thumbnail = cover image directly.
  * audio_background.mode is stored in metadata for later mixing.
"""
import asyncio
import logging
import os
import subprocess
import tempfile
import uuid
from typing import Sequence

from db import db
from storage import put_object, get_object, APP_NAME

logger = logging.getLogger("video_assembly_service")

COVER_DURATION_SEC = 2.0
MIN_SCENE_DURATION_SEC = 3.0
MAX_SCENE_DURATION_SEC = 20.0


def _ffmpeg_available() -> bool:
    import shutil
    return bool(shutil.which("ffmpeg"))


async def _fetch_file_bytes(file_id: str) -> bytes | None:
    """Look up file record and return bytes from object storage."""
    rec = await db.files.find_one({"id": file_id}, {"_id": 0})
    if not rec:
        return None
    sp = rec.get("storage_path")
    if not sp:
        return None
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, lambda: get_object(sp))
    # storage.get_object returns (bytes, content_type) tuple
    if isinstance(result, tuple):
        return result[0]
    return result


def _file_id_from_url(url: str) -> str | None:
    if not url:
        return None
    # Format: /api/uploads/file/{file_id}
    parts = url.rstrip("/").split("/")
    return parts[-1] if parts else None


def _run_ffmpeg(args: Sequence[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["ffmpeg", "-y", *args], capture_output=True, text=True, timeout=timeout)


async def assemble_video(
    order_id: str,
    plan: dict,
    cover_image_url: str | None,
    scenes: list[dict],
    narrations: list[dict],
) -> tuple[str, str, dict]:
    """
    Returns (video_url, thumbnail_url, metadata).
    scenes: list of scene_images rows (kind='scene') sorted by scene_index.
    narrations: list of narration_assets (sorted by scene_index).
    """
    audio_background_mode = (plan.get("audio_background") or {}).get("mode", "music")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "user_id": 1})
    user_id = (order or {}).get("user_id")

    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed")

    # Map scene_index -> duration
    dur_by_idx: dict[int, float] = {}
    for n in narrations:
        idx = n.get("scene_index")
        d = float(n.get("duration_seconds") or 0)
        if idx is not None and d > 0:
            dur_by_idx[int(idx)] = max(MIN_SCENE_DURATION_SEC, min(MAX_SCENE_DURATION_SEC, d))

    # Build input frames in order: cover + scenes
    work_dir = tempfile.mkdtemp(prefix=f"gheras-video-{order_id[:8]}-")
    try:
        concat_items: list[tuple[str, float]] = []  # (path, duration_seconds)

        # Cover
        if cover_image_url:
            fid = _file_id_from_url(cover_image_url)
            b = await _fetch_file_bytes(fid) if fid else None
            if b:
                cpath = os.path.join(work_dir, "cover.png")
                with open(cpath, "wb") as f:
                    f.write(b)
                concat_items.append((cpath, COVER_DURATION_SEC))

        # Scenes
        for s in scenes:
            idx = int(s.get("scene_index") or 0)
            fid = _file_id_from_url(s.get("image_url"))
            b = await _fetch_file_bytes(fid) if fid else None
            if not b:
                continue
            spath = os.path.join(work_dir, f"scene_{idx:02d}.png")
            with open(spath, "wb") as f:
                f.write(b)
            dur = dur_by_idx.get(idx, 6.0)
            concat_items.append((spath, dur))

        if not concat_items:
            raise ValueError("no image frames available for video assembly")

        # Normalize images (ffmpeg concat demuxer expects same dimensions).
        # Re-encode each image with a consistent scale+pad to 1280x720 and create a per-scene video clip.
        clip_paths: list[str] = []
        for i, (img_path, dur) in enumerate(concat_items):
            clip_path = os.path.join(work_dir, f"clip_{i:02d}.mp4")
            vf = (
                "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1"
            )
            args = [
                "-loop", "1",
                "-t", f"{dur:.2f}",
                "-i", img_path,
                "-f", "lavfi",
                "-t", f"{dur:.2f}",
                "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-vf", vf,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-shortest",
                "-r", "24",
                clip_path,
            ]
            res = _run_ffmpeg(args, timeout=60)
            if res.returncode != 0:
                logger.error(f"ffmpeg clip {i} failed: {res.stderr[-400:]}")
                raise RuntimeError(f"ffmpeg clip encoding failed: {res.stderr[-200:]}")
            clip_paths.append(clip_path)

        # Concat list file
        concat_file = os.path.join(work_dir, "concat.txt")
        with open(concat_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")

        out_path = os.path.join(work_dir, "final.mp4")
        res = _run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            out_path,
        ], timeout=120)
        if res.returncode != 0:
            logger.error(f"ffmpeg concat failed: {res.stderr[-400:]}")
            raise RuntimeError(f"ffmpeg concat failed: {res.stderr[-200:]}")

        with open(out_path, "rb") as f:
            video_bytes = f.read()
        total_duration = sum(d for _, d in concat_items)

        # Upload video to storage
        video_file_id = str(uuid.uuid4())
        storage_path = f"{APP_NAME}/orders/{order_id}/generated/final-video/{video_file_id}.mp4"
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: put_object(storage_path, video_bytes, "video/mp4"))
        await db.files.insert_one({
            "id": video_file_id,
            "user_id": user_id,
            "scope": "final-video",
            "storage_path": result.get("path", storage_path),
            "original_filename": "story.mp4",
            "content_type": "video/mp4",
            "size": result.get("size", len(video_bytes)),
            "is_deleted": False,
            "created_at": None,
        })
        video_url = f"/api/uploads/file/{video_file_id}"

        # Thumbnail = cover image (already stored). Reuse its URL.
        thumbnail_url = cover_image_url

        meta = {
            "audio_background_mode": audio_background_mode,
            "audio_track": "silent-placeholder",
            "total_duration_seconds": round(total_duration, 2),
            "clip_count": len(clip_paths),
            "encoder": "ffmpeg",
            "resolution": "1280x720",
            "real_narration_used": False,
            "note": "Phase 6B: silent video. Real TTS + music mixing in later phase.",
        }
        return video_url, thumbnail_url, meta
    finally:
        # Best-effort cleanup
        try:
            for f in os.listdir(work_dir):
                try:
                    os.remove(os.path.join(work_dir, f))
                except OSError:
                    pass
            os.rmdir(work_dir)
        except OSError:
            pass
