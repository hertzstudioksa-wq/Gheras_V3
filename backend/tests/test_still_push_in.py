"""A nearly still clip (a shot with nobody in it, a frozen toy) gets a slow push-in, so the
finished video never has the frozen span the quality gate refuses."""
import asyncio
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from services import video_assembly_service as vas  # noqa: E402


def _make(path, moving: bool):
    """A picture with detail like a real frame: moving, or one frame held for 4 s."""
    ff = vas._ffmpeg_bin()
    if moving:
        subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24", "-t", "4",
                        "-pix_fmt", "yuv420p", path], check=True)
        return
    png = path + ".png"
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=24", "-frames:v", "1",
                    png], check=True)
    subprocess.run([ff, "-v", "error", "-y", "-loop", "1", "-i", png, "-t", "4", "-r", "24", "-pix_fmt", "yuv420p", path],
                   check=True)


def _frozen_spans(path):
    res = subprocess.run([vas._ffmpeg_bin(), "-hide_banner", "-i", path, "-vf",
                          f"freezedetect=n=0.003:d={vas.QA_STILL_REPORT_SECONDS}", "-an", "-f", "null", "-"],
                         capture_output=True, text=True)
    spans = [float(x) for x in re.findall(r"freeze_duration: ([0-9.]+)", res.stderr)]
    return spans or ([4.0] if "freeze_start" in res.stderr else [])


def test_a_still_clip_is_found_and_pushed_in(tmp_path):
    still, moving, out = str(tmp_path / "still.mp4"), str(tmp_path / "moving.mp4"), str(tmp_path / "out.mp4")
    _make(still, False)
    _make(moving, True)
    assert asyncio.run(vas._still_seconds(still)) >= vas.STILL_CLIP_SECONDS
    assert asyncio.run(vas._still_seconds(moving)) == 0
    assert _frozen_spans(still)  # the gate would refuse it as it is
    subprocess.run([vas._ffmpeg_bin(), "-v", "error", "-y", "-i", still, "-vf", f"{vas._FRAME_16_9},{vas._PUSH_IN}",
                    "-t", "4", "-an", "-c:v", "libx264", "-crf", "20", out], check=True)
    assert not [s for s in _frozen_spans(out) if s >= vas.QA_FREEZE_SECONDS]
