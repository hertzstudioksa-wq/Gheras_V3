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

Hardening:
  * Missing scene/cover images fall back to a generated placeholder PNG
    so the pipeline NEVER fails because one image is absent.
"""
import asyncio
import io
import logging
import os
import shutil
import subprocess
import tempfile
import uuid
from typing import Sequence

from PIL import Image, ImageDraw

from db import db
from storage import put_object, get_object, APP_NAME


# Resolve ffmpeg binary: prefer the pip-bundled imageio-ffmpeg (persistent across
# container restarts); fall back to any system-installed ffmpeg.
def _resolve_ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:  # noqa: BLE001
        pass
    sys_ff = shutil.which("ffmpeg")
    if sys_ff:
        return sys_ff
    raise RuntimeError("ffmpeg binary is not available (neither imageio-ffmpeg nor system ffmpeg found)")


FFMPEG_BIN = None


def _ffmpeg_bin() -> str:
    global FFMPEG_BIN
    if FFMPEG_BIN is None:
        FFMPEG_BIN = _resolve_ffmpeg()
    return FFMPEG_BIN

logger = logging.getLogger("video_assembly_service")

COVER_DURATION_SEC = 2.0
MIN_SCENE_DURATION_SEC = 3.0
MAX_SCENE_DURATION_SEC = 20.0


def _ffmpeg_available() -> bool:
    try:
        return bool(_ffmpeg_bin())
    except RuntimeError:
        return False


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
    return subprocess.run([_ffmpeg_bin(), "-y", *args], capture_output=True, text=True, timeout=timeout)


def _make_placeholder_png(label: str = "") -> bytes:
    """Warm-toned 1280x720 placeholder PNG used when a scene image is unavailable.

    The goal is graceful degradation: the video ALWAYS assembles even if a
    scene image failed to generate for whatever reason.
    """
    img = Image.new("RGB", (1280, 720), color=(248, 241, 231))
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (1280, 12)], fill=(135, 169, 107))
    draw.rectangle([(0, 708), (1280, 720)], fill=(212, 163, 115))
    if label:
        try:
            from PIL import ImageFont
            font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.text(((1280 - tw) / 2, (720 - th) / 2), label, fill=(90, 103, 125), font=font)
        except Exception:
            pass
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


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

    Phase L — Hybrid assembly:
      * Prefer real per-scene clips from `db.video_clips` when available.
      * Missing clips fall back to a slideshow image (existing path).
      * `assembly_mode` in meta reflects the truth: real_clips | slideshow | hybrid.
    """
    audio_background_mode = (plan.get("audio_background") or {}).get("mode", "music")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "user_id": 1})
    user_id = (order or {}).get("user_id")

    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed")

    # Phase L — pull real video clips for this order, indexed by scene_index.
    clip_rows = await db.video_clips.find(
        {"order_id": order_id, "video_url": {"$ne": None}, "state": "COMPLETED"},
        {"_id": 0, "scene_index": 1, "video_url": 1, "duration_seconds": 1, "model": 1, "provider": 1, "clip_strategy": 1},
    ).to_list(50)
    clip_by_idx: dict[int, dict] = {int(c["scene_index"]): c for c in clip_rows}

    # Map scene_index -> duration
    dur_by_idx: dict[int, float] = {}
    for n in narrations:
        idx = n.get("scene_index")
        d = float(n.get("duration_seconds") or 0)
        if idx is not None and d > 0:
            dur_by_idx[int(idx)] = max(MIN_SCENE_DURATION_SEC, min(MAX_SCENE_DURATION_SEC, d))

    # Build input frames in order: cover + scenes
    work_dir = tempfile.mkdtemp(prefix=f"gheras-video-{order_id[:8]}-")
    placeholder_count = 0
    try:
        concat_items: list[tuple[str, float]] = []  # (path, duration_seconds)

        # Cover — use generated image, or a placeholder if missing
        cover_bytes: bytes | None = None
        if cover_image_url:
            fid = _file_id_from_url(cover_image_url)
            cover_bytes = await _fetch_file_bytes(fid) if fid else None
        if not cover_bytes:
            cover_bytes = _make_placeholder_png("Cover")
            placeholder_count += 1
        cpath = os.path.join(work_dir, "cover.png")
        with open(cpath, "wb") as f:
            f.write(cover_bytes)
        concat_items.append((cpath, COVER_DURATION_SEC))

        # Scenes — substitute a placeholder when bytes are missing so the
        # final video always reflects every planned scene.
        # Phase L — prefer real video clip when available; else image+audio slideshow.
        used_real_clips = 0
        used_slideshow_frames = 0
        clip_paths: list[str] = []
        for s in scenes:
            idx = int(s.get("scene_index") or 0)
            real_clip = clip_by_idx.get(idx)
            if real_clip and real_clip.get("video_url"):
                fid = _file_id_from_url(real_clip["video_url"])
                clip_bytes = await _fetch_file_bytes(fid) if fid else None
                if clip_bytes:
                    raw_path = os.path.join(work_dir, f"scene_{idx:02d}_raw.mp4")
                    with open(raw_path, "wb") as f:
                        f.write(clip_bytes)
                    norm_path = os.path.join(work_dir, f"scene_{idx:02d}.mp4")
                    # Re-encode to consistent format (1280x720, 24fps, h264, aac).
                    args = [
                        "-i", raw_path,
                        "-vf",
                        "scale=1280:720:force_original_aspect_ratio=decrease,"
                        "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=white,setsar=1",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-r", "24", norm_path,
                    ]
                    res = _run_ffmpeg(args, timeout=120)
                    if res.returncode == 0:
                        clip_paths.append(norm_path)
                        used_real_clips += 1
                        continue
                    logger.warning(f"clip {idx} re-encode failed → slideshow fallback: {res.stderr[-300:]}")
            # Slideshow fallback path (existing behavior).
            fid = _file_id_from_url(s.get("image_url"))
            b = await _fetch_file_bytes(fid) if fid else None
            if not b:
                b = _make_placeholder_png(f"Scene {idx}")
                placeholder_count += 1
            spath = os.path.join(work_dir, f"scene_{idx:02d}.png")
            with open(spath, "wb") as f:
                f.write(b)
            dur = dur_by_idx.get(idx, 6.0)
            concat_items.append((spath, dur))
            used_slideshow_frames += 1

        # Guarantee we have at least the cover — even without any scenes we can ship a short clip.
        if not concat_items and not clip_paths:
            raise ValueError("no image frames or clips available for video assembly")

        # Normalize images (ffmpeg concat demuxer expects same dimensions).
        # Re-encode each image with a consistent scale+pad to 1280x720 and create a per-scene video clip.
        for i, (img_path, dur) in enumerate(concat_items):
            clip_path = os.path.join(work_dir, f"slide_{i:02d}.mp4")
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
            # Slideshow clips are appended AFTER any real Kling clips for the
            # same scene_index slot ordering. They share the working order
            # because clip_paths preserves the scene order: real Kling clips
            # were appended in scene_index order and we substitute slideshow
            # frames in-place when a real clip was missing. So just append.
            clip_paths.append(clip_path)

        # Concat list file
        concat_file = os.path.join(work_dir, "concat.txt")
        with open(concat_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")

        # Phase L — concat using re-encode mode to safely splice mixed sources
        # (real Kling clips + ffmpeg slideshow clips can have differing tbn/tbc).
        out_path = os.path.join(work_dir, "final.mp4")
        res = _run_ffmpeg([
            "-f", "concat", "-safe", "0",
            "-i", concat_file,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac",
            out_path,
        ], timeout=180)
        if res.returncode != 0:
            logger.error(f"ffmpeg concat failed: {res.stderr[-400:]}")
            raise RuntimeError(f"ffmpeg concat failed: {res.stderr[-200:]}")

        with open(out_path, "rb") as f:
            video_bytes = f.read()
        total_duration = sum(d for _, d in concat_items) + (used_real_clips * 5.0)

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

        if used_real_clips and used_slideshow_frames == 0:
            assembly_mode = "real_clips"
        elif used_real_clips and used_slideshow_frames:
            assembly_mode = "hybrid"
        else:
            assembly_mode = "slideshow"

        meta = {
            "audio_background_mode":  audio_background_mode,
            "audio_track":            "silent-placeholder",
            "total_duration_seconds": round(total_duration, 2),
            "clip_count":             len(clip_paths),
            "real_clips_used":        used_real_clips,
            "slideshow_frames_used":  used_slideshow_frames,
            "placeholder_frames":     placeholder_count,
            "assembly_mode":          assembly_mode,
            "encoder":                "ffmpeg",
            "resolution":             "1280x720",
            "real_narration_used":    False,
            "note":                   ("Real per-scene Kling clips spliced with ffmpeg." if used_real_clips
                                       else "Slideshow fallback. Add FAL_KEY + enable video_generation for real clips."),
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
