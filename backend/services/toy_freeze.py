"""A toy with a face stays a toy in its clip (owner, 2026-10-26).

Wan animates any face it sees: a plush sitting by itself blinked, and one hugged
by a child nodded and closed its eyes, whatever the prompt said ("never blinks",
"frozen like a statue"). The toy is lifeless and the camera is still, so the
toy's own pixels from the clip's first frame are pasted over every frame: its
outline comes from the start picture (Florence-2 finds the box from the toy's
name, SAM 2 cuts it out, both on fal for a fraction of a cent), grown a few
pixels and feathered. When someone really moves the toy (a large share of its
pixels change), that toy is left as Wan drew it. Anything failing leaves the
clip untouched: this never blocks a story.

Two holes the first real story showed: a hugged doll's arm rose out of its
first-frame outline and waved (the outline stayed still, the arm didn't), and a
doll nobody held walked away down the path (it "really moved", so it was left
alone). SAM 2's video model now follows the toy through the clip, and wherever it
shows up outside its first-frame place that spot gets the first frame's pixels
back; and a toy nobody touches in the start picture is always frozen.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile

logger = logging.getLogger("toy_freeze")

DETECT_MODEL = "fal-ai/florence-2-large/open-vocabulary-detection"
SEGMENT_MODEL = "fal-ai/sam2/image"
TRACK_MODEL = "fal-ai/sam2/video"
# Share of a toy's inner pixels that changed from the first frame: a blink or a
# child swaying behind it stayed under 0.3, a toy really moved is far above.
MOVED_LIMIT = 0.45
GROW_PX, FEATHER_PX = 6, 4
# The followed outline is grown and feathered on a quarter-size copy (fast enough
# for every frame without OpenCV).
TRACK_SCALE = 4


async def toy_masks(keyframe: bytes, names: list[str]) -> dict[str, dict]:
    """name → {"mask": PNG of that toy in the start picture, "box": (x0, y0, x1, y1),
    "size": (w, h) of the picture}; toys that can't be found are left out."""
    from PIL import Image

    from services.ai import fake_providers, fal

    if fake_providers.enabled() or not names:
        return {}
    size = Image.open(io.BytesIO(keyframe)).size
    url = await fal.upload(env_key="FAL_KEY_TEXT", data=keyframe, content_type="image/png", file_name="start.png")
    masks: dict[str, dict] = {}
    for name in dict.fromkeys(names):
        try:
            found = await fal.run(stage="toy_freeze", env_key="FAL_KEY_TEXT", model=DETECT_MODEL,
                                  arguments={"image_url": url, "text_input": re.sub(r"^the\s+", "", name, flags=re.I)},
                                  timeout=180)
            boxes = (found.get("results") or {}).get("bboxes") or []
            if not boxes:
                logger.info(f"[toy_freeze] {name!r} not found in the start picture")
                continue
            b = boxes[0]
            box = (int(b["x"]), int(b["y"]), int(b["x"] + b["w"]), int(b["y"] + b["h"]))
            cut = await fal.run(stage="toy_freeze", env_key="FAL_KEY_TEXT", model=SEGMENT_MODEL,
                                arguments={"image_url": url, "box_prompts": [{
                                    "x_min": box[0], "y_min": box[1], "x_max": box[2], "y_max": box[3]}]}, timeout=180)
            image = (cut.get("image") or {}).get("url")
            if image:
                masks[name] = {"mask": await fal.download(image), "box": box, "size": size}
        except Exception as e:  # noqa: BLE001 — that toy stays as drawn
            logger.warning(f"[toy_freeze] mask for {name!r} failed: {type(e).__name__}: {str(e)[:160]}")
    return masks


async def toy_tracks(clip: bytes, masks: dict[str, dict], clip_size: tuple[int, int]) -> dict[str, bytes]:
    """name → a video of the toy's outline in every frame of the clip (SAM 2 video,
    started from its box in the first frame); toys it can't follow are left out."""
    from services.ai import fal

    if not masks:
        return {}
    url = await fal.upload(env_key="FAL_KEY_TEXT", data=clip, content_type="video/mp4", file_name="clip.mp4")
    tracks: dict[str, bytes] = {}
    for name, m in masks.items():
        try:
            sx, sy = clip_size[0] / m["size"][0], clip_size[1] / m["size"][1]
            x0, y0, x1, y1 = m["box"]
            res = await fal.run(stage="toy_freeze", env_key="FAL_KEY_TEXT", model=TRACK_MODEL, timeout=600,
                                arguments={"video_url": url, "apply_mask": False, "box_prompts": [{
                                    "x_min": int(x0 * sx), "y_min": int(y0 * sy), "x_max": int(x1 * sx),
                                    "y_max": int(y1 * sy), "frame_index": 0}]})
            video = (res.get("video") or {}).get("url")
            if video:
                tracks[name] = await fal.download(video)
        except Exception as e:  # noqa: BLE001 — that toy keeps its first-frame outline only
            logger.warning(f"[toy_freeze] following {name!r} failed: {type(e).__name__}: {str(e)[:160]}")
    return tracks


def _probe(ff: str, path: str) -> tuple[int, int, float]:
    info = subprocess.run([ff, "-hide_banner", "-i", path], capture_output=True, text=True, timeout=30).stderr or ""
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", info)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", info)
    if not m:
        raise ValueError("no video stream")
    return int(m.group(1)), int(m.group(2)), float(fps.group(1)) if fps else 24.0


def _frames(ff: str, path: str, w: int, h: int):
    """rgb24 frames of `path`, scaled to w×h."""
    proc = subprocess.Popen([ff, "-v", "error", "-i", path, "-vf", f"scale={w}:{h}", "-f", "rawvideo",
                             "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    size = w * h * 3
    try:
        while True:
            raw = proc.stdout.read(size)
            if len(raw) < size:
                break
            yield raw
    finally:
        proc.stdout.close()
        proc.wait()


def _soft(mask, w: int, h: int):
    """A followed outline (bool w×h) grown, feathered and back to full size as 0..1."""
    import numpy as np
    from PIL import Image, ImageFilter

    small = Image.fromarray((mask * 255).astype(np.uint8)).resize((w // TRACK_SCALE, h // TRACK_SCALE), Image.BOX)
    small = small.point(lambda v: 255 if v > 20 else 0)
    grown = small.filter(ImageFilter.MaxFilter(2 * max(1, GROW_PX // TRACK_SCALE) + 1)).filter(
        ImageFilter.GaussianBlur(max(1, FEATHER_PX // TRACK_SCALE)))
    return np.asarray(grown.resize((w, h), Image.BILINEAR), dtype=np.float32)[..., None] / 255


def freeze_clip(clip: bytes, masks: dict[str, bytes], tracks: dict[str, bytes] | None = None,
                untouched: set[str] | frozenset = frozenset()) -> tuple[bytes | None, dict]:
    """The clip with each still toy pasted from its first frame, or None when no toy
    was frozen. A toy in `untouched` (nobody holds it) is always still; `tracks` (its
    outline in every frame) also put the first frame back wherever it shows up outside
    its first-frame place. Info: per toy, the share of its pixels that moved."""
    import numpy as np
    from PIL import Image, ImageFilter

    from services.video_assembly_service import _ffmpeg_bin
    from storage import STORAGE_DIR

    ff = _ffmpeg_bin()
    root = STORAGE_DIR / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    work = tempfile.mkdtemp(prefix="toyfreeze-", dir=str(root))
    try:
        src, dst = os.path.join(work, "clip.mp4"), os.path.join(work, "frozen.mp4")
        with open(src, "wb") as f:
            f.write(clip)
        w, h, fps = _probe(ff, src)
        inner, soft = {}, {}
        for name, png in masks.items():
            m = Image.open(io.BytesIO(png)).convert("L").resize((w, h), Image.BILINEAR).point(lambda v: 255 if v > 127 else 0)
            inner[name] = np.asarray(m.filter(ImageFilter.MinFilter(9))) > 127
            grown = m.filter(ImageFilter.MaxFilter(2 * GROW_PX + 1)).filter(ImageFilter.GaussianBlur(FEATHER_PX))
            soft[name] = np.asarray(grown, dtype=np.float32)[..., None] / 255
        # Pass 1: does anyone really move the toy?
        first, moved = None, {n: 0.0 for n in masks}
        for raw in _frames(ff, src, w, h):
            g = np.frombuffer(raw, np.uint8).reshape(h, w, 3).mean(axis=2)
            if first is None:
                first = g
                continue
            for n, m in inner.items():
                if m.any():
                    moved[n] = max(moved[n], float((np.abs(g - first)[m] > 30).mean()))
        still = [n for n in masks if inner[n].any() and (n in untouched or moved[n] <= MOVED_LIMIT)]
        info = {"moved": {n: round(v, 3) for n, v in moved.items()}, "frozen": still,
                "untouched": sorted(set(untouched) & set(masks))}
        if not still:
            return None, info
        mask = np.clip(sum(soft[n] for n in still), 0, 1)
        followed = {}
        for n in still:
            if (tracks or {}).get(n):
                path = os.path.join(work, f"track-{len(followed)}.mp4")
                with open(path, "wb") as f:
                    f.write(tracks[n])
                followed[n] = _frames(ff, path, w, h)
        info["followed"] = sorted(followed)
        # Pass 2: paste the still toys from the first frame onto every frame, and wherever
        # a followed toy shows up outside its first-frame place.
        enc = subprocess.Popen([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                                "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17",
                                "-preset", "medium", "-movflags", "+faststart", dst], stdin=subprocess.PIPE)
        base, last_out = None, {}
        for raw in _frames(ff, src, w, h):
            frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.float32)
            if base is None:
                base = frame
            region = mask
            for n, frames in followed.items():
                out = next(frames, None)
                if out is not None:  # a shorter outline video keeps its last outline
                    last_out[n] = np.frombuffer(out, np.uint8).reshape(h, w, 3).mean(axis=2) > 127
                if n in last_out:
                    region = np.maximum(region, _soft(last_out[n], w, h))
            enc.stdin.write((frame * (1 - region) + base * region).round().astype(np.uint8).tobytes())
        for frames in followed.values():
            frames.close()
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("encoding the frozen clip failed")
        with open(dst, "rb") as f:
            return f.read(), info
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def freeze_toys(clip: bytes, keyframe: bytes | None, toys: list[str] | None) -> tuple[bytes, dict | None]:
    """(clip, info): the clip with its still toys frozen, or the clip as it came."""
    from services import clip_review

    if not toys or not keyframe:
        return clip, None
    try:
        found = await toy_masks(keyframe, toys)
        if not found:
            return clip, {"frozen": [], "note": "toy not found in the start picture"}
        held = await clip_review.toys_held(keyframe, list(found))
        untouched = {n for n in found if held is not None and held.get(n) is False}
        from services.video_assembly_service import _ffmpeg_bin

        root = tempfile.mkdtemp(prefix="toyprobe-")
        try:
            path = os.path.join(root, "clip.mp4")
            with open(path, "wb") as f:
                f.write(clip)
            w, h, _fps = await asyncio.to_thread(_probe, _ffmpeg_bin(), path)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        tracks = await toy_tracks(clip, found, (w, h))
        frozen, info = await asyncio.to_thread(freeze_clip, clip, {n: m["mask"] for n, m in found.items()}, tracks,
                                               untouched)
        logger.info(f"[toy_freeze] {info}")
        return (frozen or clip), info
    except Exception as e:  # noqa: BLE001 — the clip as Wan drew it
        logger.warning(f"[toy_freeze] skipped: {type(e).__name__}: {str(e)[:160]}")
        return clip, {"frozen": [], "error": f"{type(e).__name__}: {str(e)[:160]}"}
