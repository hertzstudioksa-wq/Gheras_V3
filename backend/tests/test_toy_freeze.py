"""A still toy keeps its first-frame pixels through the clip; a toy really moved is left alone."""
import asyncio
import io
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import storage  # noqa: E402
from services import toy_freeze  # noqa: E402
from services.video_assembly_service import _ffmpeg_bin  # noqa: E402

W, H = 320, 180
TOY = (120, 60, 200, 140)  # where the toy sits


def _clip(frames: list[np.ndarray]) -> bytes:
    p = subprocess.run([_ffmpeg_bin(), "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "24",
                        "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "10", "-f", "mp4",
                        "-movflags", "frag_keyframe+empty_moov", "-"],
                       input=b"".join(f.tobytes() for f in frames), capture_output=True, check=True)
    return p.stdout


def _decode(data: bytes) -> np.ndarray:
    raw = subprocess.run([_ffmpeg_bin(), "-v", "error", "-i", "-", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         input=data, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3)


def _scene(t: int, toy_shift: int = 0, blink: bool = False) -> np.ndarray:
    img = Image.new("RGB", (W, H), (230, 200, 160))
    d = ImageDraw.Draw(img)
    d.rectangle((20 + t, 40, 60 + t, 150), fill=(200, 120, 90))  # a child moving next to the toy
    x0, y0, x1, y1 = TOY
    d.rectangle((x0 + toy_shift, y0, x1 + toy_shift, y1), fill=(30, 80, 220))
    d.ellipse((x0 + 20 + toy_shift, y0 + 15, x0 + 35 + toy_shift, y0 + 30), fill=(30, 80, 220) if blink else (255, 255, 255))
    return np.asarray(img)


def _mask() -> bytes:
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rectangle(TOY, fill=255)
    out = io.BytesIO()
    m.save(out, "PNG")
    return out.getvalue()


@pytest.fixture(autouse=True)
def tmp_storage(monkeypatch, tmp_path):
    monkeypatch.setattr(storage, "STORAGE_DIR", tmp_path)


def test_a_blinking_toy_is_frozen_and_the_child_still_moves():
    frames = [_scene(t, blink=8 <= t <= 12) for t in range(24)]
    frozen, info = toy_freeze.freeze_clip(_clip(frames), {"the toy": _mask()})
    assert frozen and info["frozen"] == ["the toy"]
    out = _decode(frozen)
    eye = (slice(TOY[1] + 18, TOY[1] + 27), slice(TOY[0] + 23, TOY[0] + 32))
    assert out[10][eye].mean() > 200  # the eye stays open in the middle of the blink
    assert abs(out[20][60:120, 40:80].astype(int) - out[0][60:120, 40:80].astype(int)).mean() > 20  # the child moved


def test_a_toy_someone_moves_is_left_alone():
    frames = [_scene(t, toy_shift=min(t * 4, 60)) for t in range(24)]
    frozen, info = toy_freeze.freeze_clip(_clip(frames), {"the toy": _mask()})
    assert frozen is None and info["frozen"] == [] and info["moved"]["the toy"] > toy_freeze.MOVED_LIMIT


def test_no_toys_or_no_mask_keeps_the_clip(monkeypatch):
    async def none(keyframe, names):
        return {}

    monkeypatch.setattr(toy_freeze, "toy_masks", none)
    clip = b"not a video"
    assert asyncio.run(toy_freeze.freeze_toys(clip, b"png", None)) == (clip, None)
    out, info = asyncio.run(toy_freeze.freeze_toys(clip, b"png", ["the toy"]))
    assert out == clip and info["frozen"] == []


ARM = (200, 70, 250, 85)  # an arm Wan raises out of the toy's first-frame outline


def _arm_scene(t: int) -> np.ndarray:
    frame = _scene(t)
    if t >= 8:
        img = Image.fromarray(frame.copy())
        ImageDraw.Draw(img).rectangle(ARM, fill=(30, 80, 220))
        frame = np.asarray(img)
    return frame


def _outline(t: int, arm: bool = False, shift: int = 0) -> np.ndarray:
    img = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle((TOY[0] + shift, TOY[1], TOY[2] + shift, TOY[3]), fill=(255, 255, 255))
    if arm and t >= 8:
        d.rectangle(ARM, fill=(255, 255, 255))
    return np.asarray(img)


def test_a_limb_moved_out_of_the_first_outline_is_put_back():
    # the hugged doll's arm rose and waved while its body stayed frozen
    frames = [_arm_scene(t) for t in range(24)]
    arm = (slice(ARM[1] + 3, ARM[3] - 3), slice(ARM[0] + 15, ARM[2] - 3))
    only_first, _ = toy_freeze.freeze_clip(_clip(frames), {"the toy": _mask()})
    assert _decode(only_first)[15][arm][..., 2].mean() > 180  # the arm still waves outside the outline
    tracks = {"the toy": _clip([_outline(t, arm=True) for t in range(24)])}
    frozen, info = toy_freeze.freeze_clip(_clip(frames), {"the toy": _mask()}, tracks)
    out = _decode(frozen)
    assert info["followed"] == ["the toy"]
    assert abs(out[15][arm].astype(int) - np.array([230, 200, 160])).mean() < 25  # the background is back
    assert abs(out[20][60:120, 40:80].astype(int) - out[0][60:120, 40:80].astype(int)).mean() > 20  # the child moved


def test_a_toy_nobody_holds_stays_put_even_when_it_walks_off():
    # a doll alone at the end of the path walked away in its clip
    frames = [_scene(t, toy_shift=min(t * 4, 60)) for t in range(24)]
    tracks = {"the toy": _clip([_outline(t, shift=min(t * 4, 60)) for t in range(24)])}
    left, info = toy_freeze.freeze_clip(_clip(frames), {"the toy": _mask()}, tracks)
    assert left is None  # held (or unknown): someone may carry it
    frozen, info = toy_freeze.freeze_clip(_clip(frames), {"the toy": _mask()}, tracks, {"the toy"})
    out = _decode(frozen)
    assert info["frozen"] == ["the toy"] and info["untouched"] == ["the toy"]
    assert out[20][TOY[1] + 40, TOY[0] + 5][2] > 180  # still at its first place
    assert abs(out[20][TOY[1] + 40, TOY[2] + 50].astype(int) - np.array([230, 200, 160])).mean() < 25  # not at the new one


def test_the_held_check_and_the_tracks_reach_the_freeze(monkeypatch):
    from services import clip_review

    seen = {}

    async def masks(keyframe, names):
        return {"the toy": {"mask": _mask(), "box": TOY, "size": (W, H)}, "the kite": {"mask": _mask(), "box": TOY,
                                                                                        "size": (W, H)}}

    async def held(image, names):
        return {"the toy": False, "the kite": True}

    async def tracks(clip, found, size):
        seen["size"] = size
        return {"the toy": b"track"}

    def freeze(clip, m, t, untouched):
        seen.update(masks=sorted(m), tracks=t, untouched=untouched)
        return None, {"frozen": []}

    monkeypatch.setattr(toy_freeze, "toy_masks", masks)
    monkeypatch.setattr(clip_review, "toys_held", held)
    monkeypatch.setattr(toy_freeze, "toy_tracks", tracks)
    monkeypatch.setattr(toy_freeze, "freeze_clip", freeze)
    clip = _clip([_scene(t) for t in range(4)])
    out, info = asyncio.run(toy_freeze.freeze_toys(clip, b"png", ["the toy", "the kite"]))
    assert out == clip and seen["size"] == (W, H) and seen["masks"] == ["the kite", "the toy"]
    assert seen["untouched"] == {"the toy"} and seen["tracks"] == {"the toy": b"track"}
