"""Final video assembly with ffmpeg.

Builds the story in order — cover (2s), then each scene as its provider clip
(Kling) or, when there is no clip, its still illustration — and mixes the
per-scene narration (each line starts with its scene) over optional
background music, ducked while narrating.

  * A scene lasts as long as its real narration (+ a short tail); clips
    shorter than that hold their last frame.
  * Every segment carries an audio track so clips and stills concat cleanly.
  * ffmpeg runs in worker threads (never blocks the event loop).
  * Missing cover/scene images or a failed audio mix raise: a blank page or a
    silent "narrated" video is never delivered.
"""
import asyncio
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from typing import Sequence


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
SCENE_TAIL_SEC = 0.8  # breath after each narration line before the next scene


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


async def _ffmpeg(args: Sequence[str], timeout: int = 180) -> subprocess.CompletedProcess:
    """Run ffmpeg in a worker thread so encoding never blocks the event loop."""
    return await asyncio.to_thread(_run_ffmpeg, args, timeout)


async def _media_duration(path: str) -> float | None:
    """Duration in seconds read from ffmpeg's probe output (no ffprobe needed)."""
    res = await asyncio.to_thread(
        subprocess.run, [_ffmpeg_bin(), "-i", path], capture_output=True, text=True, timeout=30,
    )
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr or "")
    if not m:
        return None
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


# Square illustrations/clips sit centred on a blurred, zoomed copy of
# themselves instead of white pillarbox bars.
_FIT_FRAME = ("split=2[bg][fg];"
              "[bg]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,boxblur=20:2[bgb];"
              "[fg]scale=1280:720:force_original_aspect_ratio=decrease[fgs];"
              "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
_SILENCE = "anullsrc=channel_layout=stereo:sample_rate=44100"


async def _still_segment(work_dir: str, name: str, img_bytes: bytes, dur: float) -> str:
    """Encode an image as a `dur`-second 1280x720 segment with a silent track."""
    img_path = os.path.join(work_dir, f"{name}.png")
    with open(img_path, "wb") as f:
        f.write(img_bytes)
    out = os.path.join(work_dir, f"{name}.mp4")
    res = await _ffmpeg([
        "-loop", "1", "-t", f"{dur:.2f}", "-i", img_path,
        "-f", "lavfi", "-t", f"{dur:.2f}", "-i", _SILENCE,
        "-vf", _FIT_FRAME, "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest", "-r", "24", out,
    ], timeout=60)
    if res.returncode != 0:
        raise RuntimeError(f"ffmpeg still segment {name} failed: {res.stderr[-200:]}")
    return out


async def _clip_segment(work_dir: str, idx: int, clip_bytes: bytes, min_dur: float) -> tuple[str, float] | None:
    """Normalise a provider clip to 1280x720/24fps with a silent track, holding
    the last frame when the scene's narration runs longer than the clip.
    Returns (path, duration) or None if ffmpeg can't read it."""
    raw = os.path.join(work_dir, f"scene_{idx:02d}_raw.mp4")
    with open(raw, "wb") as f:
        f.write(clip_bytes)
    dur = max(min_dur, await _media_duration(raw) or 0.0)
    out = os.path.join(work_dir, f"scene_{idx:02d}.mp4")
    res = await _ffmpeg([
        "-i", raw, "-f", "lavfi", "-i", _SILENCE,
        "-vf", f"{_FIT_FRAME},tpad=stop_mode=clone:stop_duration={dur:.2f}",
        "-map", "0:v:0", "-map", "1:a:0", "-t", f"{dur:.2f}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-r", "24", out,
    ], timeout=120)
    if res.returncode != 0:
        logger.warning(f"clip {idx} re-encode failed → still image instead: {res.stderr[-300:]}")
        return None
    return out, dur


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

    # Phase M — pull narration assets per-scene + music track (if any).
    narration_rows = await db.narration_assets.find(
        {"order_id": order_id, "audio_url": {"$ne": None}},
        {"_id": 0, "scene_index": 1, "audio_url": 1, "duration_seconds": 1},
    ).to_list(50)
    narration_by_idx: dict[int, dict] = {int(n.get("scene_index") or 0): n for n in narration_rows}
    music_track = await db.music_tracks.find_one(
        {"order_id": order_id, "skipped": False, "audio_url": {"$ne": None}},
        {"_id": 0}, sort=[("created_at", -1)],
    )

    # Map scene_index -> duration
    dur_by_idx: dict[int, float] = {}
    for n in narrations:
        idx = n.get("scene_index")
        d = float(n.get("duration_seconds") or 0)
        if idx is not None and d > 0:
            dur_by_idx[int(idx)] = max(MIN_SCENE_DURATION_SEC, min(MAX_SCENE_DURATION_SEC, d))

    # Segments are built strictly in story order: cover, then every scene as
    # either its provider clip or its still image. Each segment carries an
    # audio track so mixed sources concat cleanly.
    work_dir = tempfile.mkdtemp(prefix=f"gheras-video-{order_id[:8]}-")
    placeholder_count = 0  # placeholders are never used; kept for meta compatibility
    try:
        # Narration first: the real length of each line drives its scene's length.
        narr_path_by_idx: dict[int, str] = {}
        narr_len_by_idx: dict[int, float] = {}
        for s in scenes:
            idx = int(s.get("scene_index") or 0)
            n = narration_by_idx.get(idx)
            n_fid = _file_id_from_url((n or {}).get("audio_url"))
            n_bytes = await _fetch_file_bytes(n_fid) if n_fid else None
            if n_bytes:
                npath = os.path.join(work_dir, f"nar_{idx:02d}.mp3")
                with open(npath, "wb") as f:
                    f.write(n_bytes)
                narr_path_by_idx[idx] = npath
                narr_len_by_idx[idx] = await _media_duration(npath) or dur_by_idx.get(idx, 6.0)

        cover_bytes: bytes | None = None
        if cover_image_url:
            fid = _file_id_from_url(cover_image_url)
            cover_bytes = await _fetch_file_bytes(fid) if fid else None
        if not cover_bytes:
            raise RuntimeError("cover image is missing — refusing to assemble a video with a blank cover")
        segments: list[tuple[str, float]] = [
            (await _still_segment(work_dir, "cover", cover_bytes, COVER_DURATION_SEC), COVER_DURATION_SEC)
        ]

        used_real_clips = 0
        used_slideshow_frames = 0
        scene_start: dict[int, float] = {}
        for s in scenes:
            idx = int(s.get("scene_index") or 0)
            narr = narr_len_by_idx.get(idx)
            target = narr + SCENE_TAIL_SEC if narr else dur_by_idx.get(idx, 6.0)
            target = max(MIN_SCENE_DURATION_SEC, min(MAX_SCENE_DURATION_SEC, target))
            scene_start[idx] = sum(d for _, d in segments)
            segment = None
            real_clip = clip_by_idx.get(idx)
            if real_clip and real_clip.get("video_url"):
                fid = _file_id_from_url(real_clip["video_url"])
                clip_bytes = await _fetch_file_bytes(fid) if fid else None
                segment = await _clip_segment(work_dir, idx, clip_bytes, target) if clip_bytes else None
                if segment:
                    used_real_clips += 1
            if not segment:
                fid = _file_id_from_url(s.get("image_url"))
                img = await _fetch_file_bytes(fid) if fid else None
                if not img:
                    raise RuntimeError(f"scene {idx} image is missing — refusing to assemble a video with a blank scene")
                segment = (await _still_segment(work_dir, f"scene_{idx:02d}", img, target), target)
                used_slideshow_frames += 1
            segments.append(segment)

        clip_paths = [p for p, _ in segments]
        concat_file = os.path.join(work_dir, "concat.txt")
        with open(concat_file, "w") as f:
            for p in clip_paths:
                f.write(f"file '{p}'\n")
        concat_path = os.path.join(work_dir, "concat.mp4")
        res = await _ffmpeg([
            "-f", "concat", "-safe", "0", "-i", concat_file,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24", "-c:a", "aac",
            concat_path,
        ], timeout=180)
        if res.returncode != 0:
            logger.error(f"ffmpeg concat failed: {res.stderr[-400:]}")
            raise RuntimeError(f"ffmpeg concat failed: {res.stderr[-200:]}")

        # Audio: each narration line starts with its scene; music (if any) runs
        # under the whole story, ducked while narrating.
        narration_used = [idx for idx in scene_start if idx in narr_path_by_idx]
        narration_input_args: list[str] = []
        for idx in narration_used:
            narration_input_args += ["-i", narr_path_by_idx[idx]]

        music_path = None
        music_used = False
        m_url = (music_track or {}).get("audio_url") if music_track else None
        m_fid = _file_id_from_url(m_url) if m_url else None
        m_bytes = await _fetch_file_bytes(m_fid) if m_fid else None
        if m_bytes:
            music_path = os.path.join(work_dir, "music.mp3")
            with open(music_path, "wb") as f:
                f.write(m_bytes)
            music_used = True

        out_path = os.path.join(work_dir, "final.mp4")
        total_len = sum(d for _, d in segments)
        if not narration_input_args and not music_used:
            os.rename(concat_path, out_path)
            audio_mix_meta = {"narration_count": 0, "music_used": False, "mode": "silent"}
        else:
            args = ["-i", concat_path, *narration_input_args]
            if music_used:
                args += ["-stream_loop", "-1", "-i", music_path]
            filter_parts: list[str] = []
            nar_outs: list[str] = []
            for k, idx in enumerate(narration_used):
                msec = int(scene_start[idx] * 1000)
                filter_parts.append(f"[{k + 1}:a]adelay={msec}|{msec}[n{k}]")
                nar_outs.append(f"[n{k}]")
            if nar_outs:
                if len(nar_outs) == 1:
                    filter_parts.append(f"{nar_outs[0]}aresample=async=1[narmix]")
                else:
                    filter_parts.append(
                        f"{''.join(nar_outs)}amix=inputs={len(nar_outs)}:dropout_transition=0:normalize=0,aresample=async=1[narmix]"
                    )
            if music_used:
                vol = "0.25" if nar_outs else "0.85"
                filter_parts.append(f"[{len(narration_used) + 1}:a]volume={vol},aresample=async=1[bg]")
            if nar_outs and music_used:
                filter_parts.append("[narmix][bg]amix=inputs=2:duration=longest:normalize=0[aout]")
                final_label = "[aout]"
            elif nar_outs:
                final_label = "[narmix]"
            else:
                final_label = "[bg]"
            res = await _ffmpeg([
                *args,
                "-filter_complex", ";".join(filter_parts),
                "-map", "0:v:0", "-map", final_label,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                "-t", f"{total_len:.2f}",
                out_path,
            ], timeout=240)
            if res.returncode != 0:
                # A video without its narration is not deliverable.
                raise RuntimeError(f"ffmpeg audio mix failed: {res.stderr[-300:]}")
            audio_mix_meta = {
                "narration_count":     len(nar_outs),
                "narration_scene_idx": narration_used,
                "music_used":          music_used,
                "music_provider":      (music_track or {}).get("provider"),
                "music_model":         (music_track or {}).get("model"),
                "music_db_volume":     "0.25_when_narrating" if nar_outs and music_used else ("0.85" if music_used else None),
                "mode":                "narration+music" if (nar_outs and music_used) else
                                       ("narration_only" if nar_outs else "music_only"),
            }

        with open(out_path, "rb") as f:
            video_bytes = f.read()
        total_duration = total_len

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
            "audio_track":            audio_mix_meta.get("mode", "silent"),
            "audio_mix_meta":         audio_mix_meta,
            "music_track_id":         (music_track or {}).get("id"),
            "music_skipped":          music_track is None,
            "total_duration_seconds": round(total_duration, 2),
            "clip_count":             len(clip_paths),
            "real_clips_used":        used_real_clips,
            "slideshow_frames_used":  used_slideshow_frames,
            "placeholder_frames":     placeholder_count,
            "assembly_mode":          assembly_mode,
            "encoder":                "ffmpeg",
            "resolution":             "1280x720",
            "real_narration_used":    audio_mix_meta.get("narration_count", 0) > 0,
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
