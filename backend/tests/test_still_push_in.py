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


def test_the_logo_is_a_sticker_with_a_white_edge_and_a_shadow(tmp_path):
    from PIL import Image

    w, h = vas._logo_badge(str(tmp_path / "logo.png"))
    img = Image.open(tmp_path / "logo.png").convert("RGBA")
    assert img.size == (w, h) and h < 180  # small, in a corner of the 720p frame
    alpha = img.getchannel("A")
    assert alpha.getpixel((0, 0)) == 0 and alpha.getextrema()[1] == 255  # transparent around, solid logo
    # the outermost solid ring is white (the sticker's edge), not a milky glow
    ring = [img.getpixel((x, h // 2)) for x in range(w // 2) if img.getpixel((x, h // 2))[3] == 255][:2]
    assert ring and all(min(px[:3]) > 235 for px in ring)


def test_the_logo_loop_is_seamless_and_sharp(tmp_path):
    from PIL import Image

    vas._logo_badge(str(tmp_path / "logo.png"))
    w, h = vas._logo_loop(str(tmp_path / "logo.png"), str(tmp_path / "loop.mov"))
    frames = sorted(tmp_path.glob("logo_*.png"))
    assert len(frames) == vas.LOGO_LOOP_SECONDS * vas.LOGO_FPS and (tmp_path / "loop.mov").stat().st_size > 0
    first, last = (Image.open(f).convert("RGBA") for f in (frames[0], frames[-1]))
    assert first.size == (w, h)
    diff = sum(abs(a - b) for a, b in zip(first.tobytes(), last.tobytes())) / len(first.tobytes())
    assert diff < 3  # the last frame leads back into the first: no jump when it loops


def test_the_logo_slides_into_the_top_left_and_leaves_with_the_ending():
    f = vas.logo_filter(60.0)
    assert "fade=t=in:st=0.3:d=0.8:alpha=1" in f and "fade=t=out:st=59.400:d=0.6:alpha=1" in f
    assert "overlay=x=20:y='16-14*max(0,min(1,(1.1-t)/0.8))'" in f and "shortest=1" in f  # top-left
    assert "rotate" not in f  # ffmpeg's rotate blurred the small logo


def test_a_failing_logo_never_blocks_the_story(tmp_path):
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"not a video")
    assert asyncio.run(vas._with_logo(str(tmp_path), str(src), 5.0)) == str(src)
