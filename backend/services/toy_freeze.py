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

A held toy moves with the hands that hold it: pinned to its first-frame place, a
teddy hugged closer showed two faces at once (its first-frame copy on top of the
one Wan moved). Each frame now finds where the toy went (its first-frame pixels
matched around the last place) and the first-frame toy is pasted there: it moves
as one piece with the hug and its face never changes.

The model first (owner, 2026-10-28): the paste is the last resort, not the rule. A
plush Wan had drawn right was frozen anyway, and the still patch around it showed
against the moving plants behind. Each clip's toys are now checked in Wan's own clip
(`toy_check`: crops around the toy over the clip, one cheap vision question); a toy
that didn't move by itself leaves the clip exactly as Wan made it, one that did
sends the take back for a redo, and only a toy still alive in the kept take is
pasted (`freeze_alive`), with a tight outline that carries no background along.
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
# The pasted outline: grown 6 px it carried a ring of the background from the first frame.
GROW_PX, FEATHER_PX = 2, 2
# The followed outline is grown and feathered on a quarter-size copy (fast enough
# for every frame without OpenCV).
TRACK_SCALE = 4
# How far a held toy may move from one frame to the next (px of the clip), searched
# in steps of COARSE_PX then refined; every other pixel of the toy is compared.
FOLLOW_PX, COARSE_PX = 24, 4


def detect_words(name: str) -> str:
    """What the detector looks for: the thing, without its owner. Asked for "<child>'s little
    brown teddy bear", Florence boxed the child, and the whole child was frozen while the
    teddy moved between his still hands."""
    words = re.sub(r"^the\s+", "", name.strip(), flags=re.I)
    words = re.sub(r"^(?:[^\s'’]+\s){0,3}?[^\s'’]+['’]s\s+", "", words)
    return words.strip() or name


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
                                  arguments={"image_url": url, "text_input": detect_words(name)},
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


ALIVE_CROPS = 6        # crops of the toy across the clip for the alive check
ALIVE_CROP_HEIGHT = 240


def _toy_strip(clip_path: str, box: tuple, size: tuple, clip_size: tuple, count: int = ALIVE_CROPS) -> bytes:
    """Crops around one toy (its start-picture box grown by half on each side) taken
    evenly through the clip, side by side in time order, as a JPEG."""
    from PIL import Image

    from services.video_assembly_service import _ffmpeg_bin

    ff = _ffmpeg_bin()
    w, h = clip_size
    sx, sy = w / size[0], h / size[1]
    x0, y0, x1, y1 = box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy
    gx, gy = max(24, (x1 - x0) / 2), max(24, (y1 - y0) / 2)
    crop = (max(0, int(x0 - gx)), max(0, int(y0 - gy)), min(w, int(x1 + gx)), min(h, int(y1 + gy)))
    info = subprocess.run([ff, "-hide_banner", "-i", clip_path], capture_output=True, text=True, timeout=30).stderr or ""
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", info)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", info)
    total = round((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) * float(fps.group(1)))         if m and fps else 0
    wanted = {round(i * max(0, total - 2) / max(1, count - 1)) for i in range(count)}
    picks = [raw for i, raw in enumerate(_frames(ff, clip_path, w, h)) if i in wanted]
    if not picks:
        raise ValueError("no frames")
    tiles = []
    for raw in picks:
        tile = Image.frombytes("RGB", (w, h), raw).crop(crop)
        tiles.append(tile.resize((round(tile.width * ALIVE_CROP_HEIGHT / tile.height), ALIVE_CROP_HEIGHT), Image.LANCZOS))
    gap = 8
    strip = Image.new("RGB", (sum(t.width for t in tiles) + gap * (len(tiles) - 1), ALIVE_CROP_HEIGHT), "white")
    x = 0
    for t in tiles:
        strip.paste(t, (x, 0))
        x += t.width + gap
    out = io.BytesIO()
    strip.save(out, "JPEG", quality=88)
    return out.getvalue()


async def toy_check(clip: bytes, keyframe: bytes | None, toys: list[str] | None) -> dict | None:
    """Which of the shot's toys Wan brought to life, asked on crops around each toy in its
    own clip: {"keyframe", "found" (name → start-picture mask), "alive" [names], "notes"}.
    None when the shot has no toy; a toy that can't be checked counts as fine (the clip is
    never blocked or changed on a guess)."""
    from services import clip_review, engine_health
    from services.video_assembly_service import _ffmpeg_bin

    if not toys or not keyframe:
        return None
    try:
        found = await toy_masks(keyframe, toys)
        check = {"keyframe": keyframe, "found": found, "alive": [], "notes": {}}
        if not found:
            check["notes"] = {"_": "toy not found in the start picture"}
            return check
        root = tempfile.mkdtemp(prefix="toycheck-")
        try:
            path = os.path.join(root, "clip.mp4")
            with open(path, "wb") as f:
                f.write(clip)
            w, h, _fps = await asyncio.to_thread(_probe, _ffmpeg_bin(), path)
            strips = {n: await asyncio.to_thread(_toy_strip, path, m["box"], m["size"], (w, h))
                      for n, m in found.items()}
        finally:
            shutil.rmtree(root, ignore_errors=True)
        for n, strip in strips.items():
            verdict = await clip_review.toy_alive(strip, n)
            if verdict is None:
                check["notes"][n] = "not checked"
                continue
            check["notes"][n] = verdict["note"]
            if verdict["alive"]:
                check["alive"].append(n)
        logger.info(f"[toy_freeze] check {public(check)}")
        return check
    except Exception as e:  # noqa: BLE001 — the clip as Wan drew it
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[toy_freeze] check skipped: {type(e).__name__}: {str(e)[:160]}")
        return None


def public(check: dict | None) -> dict | None:
    """What the review keeps of a toy check (no pictures)."""
    if check is None:
        return None
    return {"checked": sorted(check.get("found") or {}), "alive": list(check.get("alive") or []),
            "notes": dict(check.get("notes") or {})}


def with_check(review: dict, check: dict | None) -> dict:
    """The clip review with the toy check: a toy alive counts against the take like any problem."""
    if check is None:
        return review
    review = {**review, "toy_check": public(check)}
    if check.get("alive"):
        review["ok"] = False
        review["problems"] = list(dict.fromkeys([*(review.get("problems") or []), "object_alive"]))
    return review


async def freeze_alive(clip: bytes, check: dict) -> tuple[bytes, dict]:
    """The last resort: the toys still alive in the kept take keep their start-picture look
    (pinned when nobody holds them, carried with the hands otherwise)."""
    alive = {n: check["found"][n] for n in check.get("alive") or [] if n in (check.get("found") or {})}
    if not alive:
        return clip, {"frozen": []}
    return await freeze_toys(clip, check.get("keyframe"), list(alive), found=alive)


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


def _fit(g, tmpl, weight, top: int, left: int, near: tuple[int, int], radius: int, step: int) -> tuple[int, int]:
    """The offset around `near` where the toy's first-frame pixels fit frame `g` best."""
    h, w = 2 * tmpl.shape[0] - 1, 2 * tmpl.shape[1] - 1
    best, at = None, near
    for dy in range(near[0] - radius, near[0] + radius + 1, step):
        y = top + dy
        if y < 0 or y + h > g.shape[0]:
            continue
        for dx in range(near[1] - radius, near[1] + radius + 1, step):
            x = left + dx
            if x < 0 or x + w > g.shape[1]:
                continue
            d = float((((g[y:y + h:2, x:x + w:2] - tmpl) ** 2) * weight).sum())
            if best is None or d < best:
                best, at = d, (dy, dx)
    return at


def _follow(g, tmpl, weight, top: int, left: int, last: tuple[int, int]) -> tuple[int, int]:
    near = _fit(g, tmpl, weight, top, left, last, FOLLOW_PX, COARSE_PX)
    return _fit(g, tmpl, weight, top, left, near, COARSE_PX, 1)


def _smooth(offsets: list[tuple[int, int]], k: int = 2) -> list[tuple[int, int]]:
    """A running median, so a hand passing over the toy doesn't make it jump."""
    import numpy as np

    a = np.array(offsets)
    return [tuple(int(v) for v in np.median(a[max(0, i - k):i + k + 1], axis=0).round()) for i in range(len(a))]


def _shifted(a, dy: int, dx: int):
    """`a` moved by (dy, dx), zero where nothing came in."""
    import numpy as np

    if not dy and not dx:
        return a
    out = np.zeros_like(a)
    h, w = a.shape[:2]
    out[max(dy, 0):h + min(dy, 0), max(dx, 0):w + min(dx, 0)] = a[max(-dy, 0):h - max(dy, 0),
                                                                  max(-dx, 0):w - max(dx, 0)]
    return out


def freeze_clip(clip: bytes, masks: dict[str, bytes], tracks: dict[str, bytes] | None = None,
                untouched: set[str] | frozenset = frozenset()) -> tuple[bytes | None, dict]:
    """The clip with each still toy pasted from its first frame, or None when no toy
    was frozen. A toy in `untouched` (nobody holds it) is always still at its place;
    a held one is pasted wherever the hands carried it. `tracks` (its outline in every
    frame) also put the first frame back wherever it shows up outside that place.
    Info: per toy, the share of its pixels that changed (after following a held one)."""
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
        # Pass 1: where is each held toy in every frame, and does anyone really change it
        # (turn it around, squeeze it out of shape)?
        first, moved = None, {n: 0.0 for n in masks}
        boxes = {}
        for n, m in inner.items():
            if m.any():
                ys, xs = np.nonzero(m)
                boxes[n] = (int(ys.min()), int(ys.max()) + 1, int(xs.min()), int(xs.max()) + 1)
        offsets = {n: [(0, 0)] for n in boxes if n not in untouched}
        for raw in _frames(ff, src, w, h):
            g = np.frombuffer(raw, np.uint8).reshape(h, w, 3).mean(axis=2)
            if first is None:
                first = g
                continue
            for n, (y0, y1, x0, x1) in boxes.items():
                dy, dx = 0, 0
                if n in offsets:
                    dy, dx = _follow(g, first[y0:y1:2, x0:x1:2], inner[n][y0:y1:2, x0:x1:2], y0, x0, offsets[n][-1])
                    offsets[n].append((dy, dx))
                seen = g[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
                if seen.shape == (y1 - y0, x1 - x0):
                    changed = np.abs(seen - first[y0:y1, x0:x1])[inner[n][y0:y1, x0:x1]] > 30
                    moved[n] = max(moved[n], float(changed.mean()))
        still = [n for n in masks if inner[n].any() and (n in untouched or moved[n] <= MOVED_LIMIT)]
        info = {"moved": {n: round(v, 3) for n, v in moved.items()}, "frozen": still,
                "untouched": sorted(set(untouched) & set(masks))}
        if not still:
            return None, info
        shifts = {n: _smooth(offsets[n]) for n in still if n in offsets}
        if shifts:
            info["carried_px"] = {n: max(max(abs(dy), abs(dx)) for dy, dx in s) for n, s in shifts.items()}
        mask = np.clip(sum((soft[n] for n in still if n not in shifts), np.zeros((h, w, 1), np.float32)), 0, 1)
        followed = {}
        for n in still:
            if (tracks or {}).get(n):
                path = os.path.join(work, f"track-{len(followed)}.mp4")
                with open(path, "wb") as f:
                    f.write(tracks[n])
                followed[n] = _frames(ff, path, w, h)
        info["followed"] = sorted(followed)
        # Pass 2: paste the still toys from the first frame onto every frame (a held one
        # where it was carried), and wherever a followed toy shows up outside that place.
        enc = subprocess.Popen([ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                                "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17",
                                "-preset", "medium", "-movflags", "+faststart", dst], stdin=subprocess.PIPE)
        base, last_out = None, {}
        for i, raw in enumerate(_frames(ff, src, w, h)):
            frame = np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.float32)
            if base is None:
                base = frame
            region, carried = mask, {}
            for n, frames in followed.items():
                out = next(frames, None)
                if out is not None:  # a shorter outline video keeps its last outline
                    last_out[n] = np.frombuffer(out, np.uint8).reshape(h, w, 3).mean(axis=2) > 127
                if n in last_out:
                    if n in shifts:
                        carried[n] = _soft(last_out[n], w, h)
                    else:
                        region = np.maximum(region, _soft(last_out[n], w, h))
            frame = frame * (1 - region) + base * region
            for n, s in shifts.items():
                dy, dx = s[min(i, len(s) - 1)]
                part = _shifted(soft[n], dy, dx)
                if n in carried:
                    part = np.maximum(part, carried[n])
                frame = frame * (1 - part) + _shifted(base, dy, dx) * part
            enc.stdin.write(frame.round().astype(np.uint8).tobytes())
        for frames in followed.values():
            frames.close()
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("encoding the frozen clip failed")
        with open(dst, "rb") as f:
            return f.read(), info
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def freeze_toys(clip: bytes, keyframe: bytes | None, toys: list[str] | None,
                      found: dict | None = None) -> tuple[bytes, dict | None]:
    """(clip, info): the clip with these toys frozen, or the clip as it came. `found`: their
    start-picture masks when a toy check already has them."""
    from services import clip_review

    if not toys or not keyframe:
        return clip, None
    try:
        found = found if found is not None else await toy_masks(keyframe, toys)
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
