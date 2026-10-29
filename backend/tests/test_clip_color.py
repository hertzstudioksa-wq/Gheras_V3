"""A clip Wan washed out on the way between its pictures gets their colors back; a clip that kept
them is not touched (the owner saw the first ten seconds of a story faded, "like a white layer")."""
import io
import os
import subprocess
import tempfile

import numpy as np
from PIL import Image

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from services import clip_color  # noqa: E402

W, H, N = 320, 180, 24


def picture() -> np.ndarray:
    x = np.linspace(0, 1, W)[None, :, None]
    y = np.linspace(0, 1, H)[:, None, None]
    img = np.concatenate([40 + 180 * x * np.ones_like(y), 30 + 200 * y * np.ones_like(x),
                          200 - 150 * x * y], axis=2)
    img[60:120, 120:200] = (20, 20, 30)  # something dark, like hair
    return img.clip(0, 255).astype(np.uint8)


def png(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, "PNG")
    return buf.getvalue()


def clip(frames: list[np.ndarray]) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "c.mp4")
        p = subprocess.Popen([clip_color._ffmpeg(), "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                              "-s", f"{W}x{H}", "-r", "12", "-i", "-", "-c:v", "libx264", "-crf", "12",
                              "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
        for f in frames:
            p.stdin.write(f.tobytes())
        p.stdin.close()
        assert p.wait() == 0
        with open(out, "rb") as f:
            return f.read()


def middle(data: bytes) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "c.mp4")
        with open(path, "wb") as f:
            f.write(data)
        frames = list(clip_color._frames(path, W, H))
    return frames[len(frames) // 2].astype(np.float32)


def test_a_washed_out_clip_gets_its_pictures_colors_back():
    pic = picture()
    # toward white with 40% opacity in the middle, as Wan did in a bright bedroom
    fade = [np.sin(np.pi * i / (N - 1)) * 0.4 for i in range(N)]
    frames = [(pic * (1 - a) + 255 * a).astype(np.uint8) for a in fade]
    washed = clip(frames)
    assert middle(washed).std() < 0.75 * pic.std()
    fixed, done = clip_color.restore(washed, png(pic), png(pic))
    assert done["applied"] and done["contrast_kept"] < 0.8
    assert abs(middle(fixed).std() - pic.std()) < 0.1 * pic.std()
    assert abs(middle(fixed).mean() - pic.mean()) < 6


def test_a_clip_that_kept_its_colors_is_left_as_made_and_trouble_keeps_the_clip():
    pic = picture()
    steady = clip([pic] * N)
    out, done = clip_color.restore(steady, png(pic), png(pic))
    assert out == steady and not done["applied"]
    assert clip_color.restore(b"not a video", png(pic)) == (b"not a video", {"applied": False, "reason": "ValueError"})
