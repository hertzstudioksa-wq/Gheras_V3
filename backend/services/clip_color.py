"""A clip's colors brought back to its own pictures'.

Wan sometimes washes a clip out on the way between its pictures: in a bright bedroom
the contrast fell by a third and the blacks rose from 45 to 79 between the clip's first
frame and its middle (owner: "the first ten seconds are faded, like a white layer"),
while the start and end pictures it was pinned to were fine and the clips after it
kept their colors. Each frame's color statistics (per channel: mean and spread, smoothed
over a few frames) are moved back to the pictures' (the start picture's, blending into
the end picture's over the clip). A clip whose colors held is left untouched, so this
only ever repairs; nothing is drawn again and nothing is paid.
"""
from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import tempfile

logger = logging.getLogger("clip_color")

DRIFT_SPREAD = 0.88   # a stretch of frames with less than 88% of the pictures' contrast...
DRIFT_MEAN = 20.0     # ...or brightness moved by more than this (0-255): a clip that kept its contrast
                      # and brightened a little (13 on a sunny shot) is left as made
SMOOTH = 9            # frames averaged, so the repair never flickers
GAIN = (0.8, 1.7)     # how far a channel's contrast may be stretched or eased


def _ffmpeg() -> str:
    from services.video_assembly_service import _ffmpeg_bin

    return _ffmpeg_bin()


def _probe(path: str) -> tuple[int, int, float]:
    out = subprocess.run([_ffmpeg(), "-i", path], capture_output=True, text=True, timeout=60).stderr
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    fps = re.search(r"(\d+(?:\.\d+)?) fps", out)
    if not m:
        raise ValueError("no video stream")
    return int(m.group(1)), int(m.group(2)), float(fps.group(1)) if fps else 24.0


def _frames(path: str, w: int, h: int):
    """The clip's frames as RGB arrays, one at a time."""
    import numpy as np

    size = w * h * 3
    proc = subprocess.Popen([_ffmpeg(), "-loglevel", "error", "-i", path, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                            stdout=subprocess.PIPE)
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield np.frombuffer(buf, np.uint8).reshape(h, w, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def _stats(a) -> tuple:
    import numpy as np

    f = a.reshape(-1, 3).astype(np.float32)
    return f.mean(axis=0), f.std(axis=0) + 1e-3


def _picture(png: bytes, w: int, h: int):
    import numpy as np
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB").resize((w, h), Image.LANCZOS))


def restore(clip: bytes, start: bytes, end: bytes | None = None) -> tuple[bytes, dict]:
    """(the clip with its pictures' colors, what was done). Any trouble keeps the clip."""
    import numpy as np

    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.mp4")
        with open(src, "wb") as f:
            f.write(clip)
        try:
            w, h, fps = _probe(src)
            means, spreads = zip(*[_stats(fr) for fr in _frames(src, w, h)])
            n = len(means)
            if n < 2:
                return clip, {"applied": False, "reason": "too short"}
            means, spreads = np.array(means), np.array(spreads)
            k = min(SMOOTH, n)
            kernel = np.ones(k) / k
            smooth = lambda a: np.stack([np.convolve(np.pad(a[:, c], (k // 2, k - 1 - k // 2), mode="edge"),
                                                     kernel, mode="valid") for c in range(3)], axis=1)
            means, spreads = smooth(means), smooth(spreads)
            s_mean, s_spread = _stats(_picture(start, w, h))
            e_mean, e_spread = _stats(_picture(end, w, h)) if end else (s_mean, s_spread)
            t = np.linspace(0.0, 1.0, n)[:, None]
            ref_mean = s_mean * (1 - t) + e_mean * t
            ref_spread = s_spread * (1 - t) + e_spread * t
            lost = float((spreads.mean(axis=1) / ref_spread.mean(axis=1)).min())
            moved = float(np.abs(means.mean(axis=1) - ref_mean.mean(axis=1)).max())
            if lost >= DRIFT_SPREAD and moved <= DRIFT_MEAN:
                return clip, {"applied": False, "contrast_kept": round(lost, 2), "brightness_moved": round(moved, 1)}
            gain = np.clip(ref_spread / spreads, *GAIN)
            out = os.path.join(tmp, "out.mp4")
            enc = subprocess.Popen([_ffmpeg(), "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                                    "-s", f"{w}x{h}", "-r", f"{fps:g}", "-i", "-", "-c:v", "libx264", "-crf", "17",
                                    "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out],
                                   stdin=subprocess.PIPE)
            for i, fr in enumerate(_frames(src, w, h)):
                if i >= n:
                    break
                fixed = (fr.astype(np.float32) - means[i]) * gain[i] + ref_mean[i]
                enc.stdin.write(np.clip(fixed, 0, 255).astype(np.uint8).tobytes())
            enc.stdin.close()
            if enc.wait() != 0:
                raise RuntimeError("encode failed")
            with open(out, "rb") as f:
                data = f.read()
            return data, {"applied": True, "contrast_kept": round(lost, 2), "brightness_moved": round(moved, 1)}
        except Exception as e:  # noqa: BLE001 — a faded clip beats no clip
            logger.warning(f"[clip_color] kept as made: {type(e).__name__}: {str(e)[:160]}")
            return clip, {"applied": False, "reason": type(e).__name__}
