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


# ---------------------------------------------------------------- shot engine
_FRAME_16_9 = "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,fps=24,setsar=1,format=yuv420p"
MUSIC_VOLUME = 0.2           # soft bed under the narration, like the reference videos
# Assembly never holds frames (clips are cut to their lines, a short clip is
# slowed, a missing one gets a moving push-in), so a still span can only come
# from the video model itself. A child pausing in a "tired" shot can sit still
# ~1 s and looks natural; a clip that's a still image for 2 s+ is the defect.
# Shorter still spans are kept in the report for review.
QA_FREEZE_SECONDS = 2.0
QA_STILL_REPORT_SECONDS = 1.0
QA_MAX_DURATION_DRIFT = 0.35  # vs the length the parent ordered
# Clips are generated at least as long as their line; if one comes back short it
# may be slowed this much (slow motion still moves) — beyond that the order fails.
MAX_SLOWDOWN = 1.6


# A clip that comes back nearly still (a shot with nobody in it, or a toy frozen in
# place) gets a slow digital push-in: a uniform zoom of the finished picture, so it
# never stretches anything the way a camera move inside the video model does.
STILL_CLIP_SECONDS = 1.5
_PUSH_IN = ("scale=2560:1440,zoompan=z='min(1+0.0009*on,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            ":d=1:s=1280x720:fps=24,setsar=1,format=yuv420p")


async def _still_seconds(path: str) -> float:
    """The longest span in which the clip doesn't move (0 when it always moves)."""
    res = await asyncio.to_thread(subprocess.run, [
        _ffmpeg_bin(), "-hide_banner", "-i", path, "-vf", f"freezedetect=n=0.003:d={STILL_CLIP_SECONDS}",
        "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=300)
    spans = [float(x) for x in re.findall(r"freeze_duration: ([0-9.]+)", res.stderr or "")]
    if not spans and "freeze_start" in (res.stderr or ""):
        return await _media_duration(path) or STILL_CLIP_SECONDS  # still until the end
    return max(spans, default=0.0)


# ---------------------------------------------------------------- brand logo
# The owner wants the Gheras logo in every video, top-left, looking good and moving gently
# the whole time. The first version (a milky glow, ffmpeg rotating a 108 px picture,
# bottom-right on the grass) looked cheap: the logo is now a die-cut sticker (a clean white
# edge from its own outline and a soft shadow, readable on grass, sky or skin) drawn once
# from the 2048 px file, and its float and breath are drawn frame by frame at sub-pixel
# precision instead of rotated by ffmpeg. The icon and the name only: the tagline can't be
# read at this size. It goes on after the quality gate, so its motion never hides a frozen shot.
BRAND_LOGO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "brand",
                          "gheras-logo.png")
LOGO_TAGLINE_TOP = 1541     # first row of the tagline in the 2048px logo
LOGO_HEIGHT = 120           # px of the 720p frame
LOGO_MARGIN = (20, 16)      # from the left and the top edges
LOGO_BORDER = 5             # the sticker's white edge, px
LOGO_SHADOW = (3, 6, 0.35)  # drop (px), blur, opacity
LOGO_LOOP_SECONDS, LOGO_FPS = 4, 24
LOGO_FLOAT_PX, LOGO_BREATH = 2.0, 0.02


def _logo_badge(path: str, height: int = LOGO_HEIGHT) -> tuple[int, int]:
    """The logo (icon + name) as a sticker: a white edge around its outline and a soft
    shadow, on a transparent PNG. Returns its size."""
    from PIL import Image, ImageFilter

    src = Image.open(BRAND_LOGO).convert("RGBA")
    logo = src.crop((0, 0, src.width, min(src.height, LOGO_TAGLINE_TOP)))
    logo = logo.crop(logo.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox())
    logo = logo.resize((round(logo.width * height / logo.height), height), Image.LANCZOS)
    drop, blur, opacity = LOGO_SHADOW
    pad = LOGO_BORDER + 2 * blur + drop
    size = (logo.width + 2 * pad, logo.height + 2 * pad)
    shape = Image.new("L", size, 0)
    shape.paste(logo.getchannel("A").point(lambda v: 255 if v > 60 else 0), (pad, pad))
    # A round grow (blur, then a low cut) gives the sticker's smooth die-cut edge.
    edge = shape.filter(ImageFilter.GaussianBlur(LOGO_BORDER)).point(lambda v: 255 if v > 12 else 0)
    edge = edge.filter(ImageFilter.GaussianBlur(0.7))
    shadow = Image.new("L", size, 0)
    shadow.paste(edge, (0, drop))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * opacity))
    badge = Image.new("RGBA", size, (0, 0, 0, 0))
    badge.putalpha(shadow)
    white = Image.new("RGBA", size, (255, 255, 255, 0))
    white.putalpha(edge)
    badge.alpha_composite(white)
    badge.alpha_composite(logo, (pad, pad))
    badge.save(path)
    return badge.size


def _logo_loop(badge_path: str, out_path: str) -> tuple[int, int]:
    """A seamless LOGO_LOOP_SECONDS loop of the sticker floating and breathing gently, drawn
    frame by frame (sub-pixel, no jagged steps), as a transparent .mov. Returns its frame size."""
    import math

    from PIL import Image

    badge = Image.open(badge_path).convert("RGBA")
    room = math.ceil(LOGO_FLOAT_PX + 1)
    w = badge.width + 2 * math.ceil(badge.width * LOGO_BREATH / 2 + 1)
    h = badge.height + 2 * math.ceil(badge.height * LOGO_BREATH / 2 + room)
    frames = LOGO_LOOP_SECONDS * LOGO_FPS
    work = os.path.dirname(out_path)
    for i in range(frames):
        phase = 2 * math.pi * i / frames
        scale = 1 + LOGO_BREATH * (0.5 - 0.5 * math.cos(phase))
        dy = LOGO_FLOAT_PX * math.sin(phase)
        # The output pixel (x, y) takes the badge pixel ((x - cx) / s + bw/2, (y - cy - dy) / s + bh/2).
        cx, cy = w / 2, h / 2
        coeffs = (1 / scale, 0, badge.width / 2 - cx / scale, 0, 1 / scale, badge.height / 2 - (cy + dy) / scale)
        frame = badge.transform((w, h), Image.AFFINE, coeffs, resample=Image.BICUBIC)
        frame.save(os.path.join(work, f"logo_{i:03d}.png"))
    res = subprocess.run([_ffmpeg_bin(), "-v", "error", "-y", "-framerate", str(LOGO_FPS),
                          "-i", os.path.join(work, "logo_%03d.png"), "-c:v", "qtrle", "-pix_fmt", "argb", out_path],
                         capture_output=True, text=True, timeout=120)
    if res.returncode != 0:
        raise RuntimeError(f"logo loop: {res.stderr[-200:]}")
    return w, h


def logo_filter(total: float) -> str:
    """The logo's entrance and exit for a `total`-second video: it fades in sliding down into
    the top-left corner, keeps its gentle loop the whole time, and fades out with the ending."""
    end = max(0.0, total - 0.6)
    mx, my = LOGO_MARGIN
    return (f"[1:v]format=rgba,fade=t=in:st=0.3:d=0.8:alpha=1,fade=t=out:st={end:.3f}:d=0.6:alpha=1[logo];"
            f"[0:v][logo]overlay=x={mx}:y='{my}-14*max(0,min(1,(1.1-t)/0.8))':shortest=1,format=yuv420p[v]")


async def logo_on() -> bool:
    s = await db.settings.find_one({"key": "video.logo"}, {"_id": 0, "value": 1})
    return (s or {}).get("value", True) is not False


async def _with_logo(work: str, src: str, total: float) -> str:
    """`src` with the moving logo, or `src` itself when that fails (never blocks a story)."""
    badge = os.path.join(work, "logo.png")
    loop = os.path.join(work, "logo_loop.mov")
    out = os.path.join(work, "branded.mp4")
    try:
        await asyncio.to_thread(_logo_badge, badge)
        await asyncio.to_thread(_logo_loop, badge, loop)
        res = await _ffmpeg(["-i", src, "-stream_loop", "-1", "-i", loop,
                             "-filter_complex", logo_filter(total), "-map", "[v]", "-map", "0:a?",
                             "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "copy",
                             "-movflags", "+faststart", out], timeout=600)
        if res.returncode == 0 and os.path.getsize(out) > 0:
            return out
        logger.warning(f"[assembly] logo skipped: {res.stderr[-300:]}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[assembly] logo skipped: {type(e).__name__}: {str(e)[:200]}")
    return src


async def _quality_gate(path: str, ordered_seconds: float | None, shots: int) -> dict:
    """Measure the finished video the way the reference videos were measured.
    Raises when it would be delivered with frozen frames or the wrong length."""
    res = await asyncio.to_thread(subprocess.run, [
        _ffmpeg_bin(), "-hide_banner", "-i", path, "-vf", f"freezedetect=n=0.003:d={QA_STILL_REPORT_SECONDS}",
        "-an", "-f", "null", "-"], capture_output=True, text=True, timeout=600)
    still = [float(x) for x in re.findall(r"freeze_duration: ([0-9.]+)", res.stderr or "")]
    frozen = [s for s in still if s >= QA_FREEZE_SECONDS]
    total = await _media_duration(path) or 0.0
    drift = abs(total - ordered_seconds) / ordered_seconds if ordered_seconds else 0.0
    report = {"duration_seconds": round(total, 2), "ordered_seconds": ordered_seconds,
              "duration_drift": round(drift, 3), "frozen_spans": frozen, "still_spans": still, "shots": shots,
              "mean_shot_seconds": round(total / shots, 2) if shots else None}
    if frozen:
        raise RuntimeError(f"quality gate: {len(frozen)} frozen span(s) ≥{QA_FREEZE_SECONDS}s in the video")
    if drift > QA_MAX_DURATION_DRIFT:
        raise RuntimeError(f"quality gate: video is {total:.0f}s for a {ordered_seconds}s order")
    return report


async def _store_final_video(order_id: str, user_id: str | None, out_path: str) -> str:
    with open(out_path, "rb") as f:
        video_bytes = f.read()
    video_file_id = str(uuid.uuid4())
    storage_path = f"{APP_NAME}/orders/{order_id}/generated/final-video/{video_file_id}.mp4"
    result = await asyncio.to_thread(put_object, storage_path, video_bytes, "video/mp4")
    await db.files.insert_one({
        "id": video_file_id, "user_id": user_id, "scope": "final-video",
        "storage_path": result.get("path", storage_path), "original_filename": "story.mp4",
        "content_type": "video/mp4", "size": result.get("size", len(video_bytes)),
        "is_deleted": False, "created_at": None,
    })
    return f"/api/uploads/file/{video_file_id}"


async def assemble_shot_video(order_id: str, plan: dict, cover_image_url: str | None) -> tuple[str, str, dict]:
    """Shot-engine assembly: every shot is its Kling clip trimmed to its
    narration line (+ a short gap), hard cuts between shots, one music bed under
    the whole story, loudness-normalised stereo. No frame is ever held."""
    from services.engine_config import get_pacing
    from services.shot_pipeline import shot_rows, work_dir

    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "user_id": 1})
    rows = await shot_rows(order_id, plan["id"])
    if not rows:
        raise RuntimeError("no shots to assemble")
    pacing = await get_pacing()
    work = work_dir(f"gheras-shots-{order_id[:8]}-")
    try:
        video_parts, narr_parts = [], []
        slowed, still_motion = 0, 0
        for i, r in enumerate(rows):
            tag = f"{r['scene_index']:02d}_{r['shot_index']:02d}"
            nar_fid = _file_id_from_url(r.get("narration_url"))
            nar_bytes = await _fetch_file_bytes(nar_fid) if nar_fid else None
            if not nar_bytes:
                raise RuntimeError(f"shot {tag} has no narration — refusing to deliver a silent shot")
            nar_path = os.path.join(work, f"nar_{tag}.audio")
            with open(nar_path, "wb") as f:
                f.write(nar_bytes)
            nar_len = await _media_duration(nar_path) or float(r.get("narration_seconds") or 0)
            dur = nar_len + pacing["line_gap_sec"] + (pacing["end_tail_sec"] if i == len(rows) - 1 else 0.0)
            narr_parts.append((nar_path, dur))

            seg = os.path.join(work, f"shot_{tag}.mp4")
            if r.get("clip_state") == "held" and not r.get("clip_url"):
                raise RuntimeError(f"shot {tag} is held: its start picture needs a new drawing")
            clip_fid = _file_id_from_url(r.get("clip_url"))
            clip_bytes = await _fetch_file_bytes(clip_fid) if clip_fid else None
            if clip_bytes:
                raw = os.path.join(work, f"raw_{tag}.mp4")
                with open(raw, "wb") as f:
                    f.write(clip_bytes)
                clip_len = await _media_duration(raw) or 0.0
                vf = _FRAME_16_9
                if clip_len and clip_len < dur:
                    factor = dur / clip_len
                    if factor > MAX_SLOWDOWN:
                        raise RuntimeError(f"shot {tag}: clip is {clip_len:.1f}s for a {dur:.1f}s line")
                    vf = f"setpts={factor:.4f}*PTS,{vf}"
                    slowed += 1
                if await _still_seconds(raw) >= STILL_CLIP_SECONDS:
                    vf = f"{vf},{_PUSH_IN}"
                    still_motion += 1
                res = await _ffmpeg(["-i", raw, "-vf", vf, "-t", f"{dur:.3f}", "-an",
                                     "-c:v", "libx264", "-preset", "medium", "-crf", "20", seg], timeout=180)
            else:
                # No clip after retries: a slow push-in on the keyframe keeps the
                # picture moving (counted in the report; never a frozen frame).
                kf_fid = _file_id_from_url(r.get("keyframe_url"))
                kf = await _fetch_file_bytes(kf_fid) if kf_fid else None
                if not kf:
                    raise RuntimeError(f"shot {tag} has neither a clip nor a keyframe")
                img = os.path.join(work, f"kf_{tag}.png")
                with open(img, "wb") as f:
                    f.write(kf)
                frames = int(dur * 24) + 1
                res = await _ffmpeg(["-loop", "1", "-i", img, "-vf",
                                     f"scale=2560:1440:force_original_aspect_ratio=increase,crop=2560:1440,"
                                     f"zoompan=z='min(zoom+0.0009,1.12)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                                     f":d={frames}:s=1280x720:fps=24,setsar=1,format=yuv420p",
                                     "-t", f"{dur:.3f}", "-c:v", "libx264", "-preset", "medium", "-crf", "20", seg],
                                    timeout=180)
                still_motion += 1
            if res.returncode != 0:
                raise RuntimeError(f"ffmpeg shot {tag} failed: {res.stderr[-300:]}")
            video_parts.append(seg)

        concat_list = os.path.join(work, "concat.txt")
        with open(concat_list, "w") as f:
            f.writelines(f"file '{p}'\n" for p in video_parts)
        picture = os.path.join(work, "picture.mp4")
        res = await _ffmpeg(["-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", picture], timeout=180)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed: {res.stderr[-300:]}")
        total = sum(d for _, d in narr_parts)

        # Narration: each line padded to its shot, back to back — line k starts
        # exactly when shot k cuts in.
        args = ["-i", picture]
        filters, labels = [], []
        for k, (p, d) in enumerate(narr_parts):
            args += ["-i", p]
            filters.append(f"[{k + 1}:a]aresample=44100,aformat=channel_layouts=mono,"
                           f"apad=whole_dur={d:.3f},atrim=0:{d:.3f}[n{k}]")
            labels.append(f"[n{k}]")
        filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[narr]")
        music = await db.music_tracks.find_one({"order_id": order_id, "skipped": False, "audio_url": {"$ne": None}},
                                               {"_id": 0}, sort=[("created_at", -1)])
        m_fid = _file_id_from_url((music or {}).get("audio_url"))
        m_bytes = await _fetch_file_bytes(m_fid) if m_fid else None
        if m_bytes:
            m_path = os.path.join(work, "music.audio")
            with open(m_path, "wb") as f:
                f.write(m_bytes)
            args += ["-stream_loop", "-1", "-i", m_path]
            fade = max(0.0, total - 1.5)
            filters.append(f"[{len(narr_parts) + 1}:a]aresample=44100,volume={MUSIC_VOLUME},atrim=0:{total:.3f},"
                           f"afade=t=out:st={fade:.3f}:d=1.5[mus]")
            filters.append("[narr][mus]amix=inputs=2:normalize=0:duration=first[mix]")
            mix = "[mix]"
        else:
            mix = "[narr]"
        filters.append(f"{mix}loudnorm=I=-16:TP=-1.5:LRA=11,aresample=44100,aformat=channel_layouts=stereo[aout]")
        out_path = os.path.join(work, "final.mp4")
        res = await _ffmpeg([*args, "-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[aout]",
                             "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-t", f"{total:.3f}",
                             "-movflags", "+faststart", out_path], timeout=300)
        if res.returncode != 0:
            raise RuntimeError(f"ffmpeg audio mix failed: {res.stderr[-300:]}")

        qa = await _quality_gate(out_path, plan.get("duration_seconds"), len(rows))
        delivered = await _with_logo(work, out_path, qa["duration_seconds"] or total) if await logo_on() else out_path
        video_url = await _store_final_video(order_id, (order or {}).get("user_id"), delivered)
        thumb = cover_image_url or rows[0].get("keyframe_url")
        meta = {
            "assembly_mode": "shots",
            "audio_background_mode": (plan.get("audio_background") or {}).get("mode", "music"),
            "audio_track": "narration+music" if m_bytes else "narration_only",
            "music_track_id": (music or {}).get("id"),
            "music_skipped": not m_bytes,
            "total_duration_seconds": qa["duration_seconds"],
            "clip_count": len(rows),
            "real_clips_used": len(rows) - still_motion,
            "keyframe_motion_shots": still_motion,
            "slowed_clips": slowed,
            "slideshow_frames_used": 0,
            "placeholder_frames": 0,
            "quality": qa,
            "encoder": "ffmpeg",
            "resolution": "1280x720",
            "real_narration_used": True,
            "logo": delivered != out_path,
        }
        return video_url, thumb, meta
    finally:
        shutil.rmtree(work, ignore_errors=True)


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
    if not _ffmpeg_available():
        raise RuntimeError("ffmpeg is not installed")
    # Shot plans (M2) assemble per shot; older orders keep the scene path below.
    if await db.shot_assets.count_documents({"order_id": order_id, "production_plan_id": plan.get("id")}):
        return await assemble_shot_video(order_id, plan, cover_image_url)

    audio_background_mode = (plan.get("audio_background") or {}).get("mode", "music")
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "user_id": 1})
    user_id = (order or {}).get("user_id")

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
    from services.shot_pipeline import work_dir as _work_dir
    work_dir = _work_dir(f"gheras-video-{order_id[:8]}-")
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
