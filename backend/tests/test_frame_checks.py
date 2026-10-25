"""Checks that need no model: coloured static, and an empty balance pausing the review and the tashkeel."""
import asyncio
import io
import os
import random
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from PIL import Image, ImageDraw  # noqa: E402

from services import clip_review, shot_pipeline as sp, tashkeel_service  # noqa: E402
from services.ai import AIConfigError, AIError  # noqa: E402

LOCKED = "fal call failed (upload): HTTP 403: User is locked. Reason: Exhausted balance. Top up your balance"


def _png(img: Image.Image) -> bytes:
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def static_picture() -> bytes:
    """What Qwen returned: a pale canvas broken into small blobs of every colour."""
    rnd = random.Random(7)
    img = Image.new("RGB", (1536, 864), (245, 245, 245))
    d = ImageDraw.Draw(img)
    for _ in range(4500):  # about a third of the blocks coloured, like the real ones
        x, y, s = rnd.randrange(1536), rnd.randrange(864), rnd.randrange(3, 14)
        d.rectangle((x, y, x + s, y + s), fill=tuple(rnd.randrange(256) for _ in range(3)))
    return _png(img)


def cartoon_picture() -> bytes:
    """A real frame: flat coloured areas, a gradient sky, characters with outlines."""
    img = Image.new("RGB", (1536, 864))
    d = ImageDraw.Draw(img)
    for y in range(864):
        d.line((0, y, 1536, y), fill=(255, 150 + y // 10, 60 + y // 8))
    d.rectangle((0, 600, 1536, 864), fill=(60, 140, 50))
    for x in (400, 900):
        d.ellipse((x, 250, x + 200, 450), fill=(240, 190, 150), outline=(40, 20, 10), width=6)
        d.rectangle((x + 20, 450, x + 180, 700), fill=(40, 90, 200), outline=(20, 20, 40), width=6)
    return _png(img)


def jungle_picture() -> bytes:
    """Busy and colourful (leaves everywhere) but each leaf one colour."""
    rnd = random.Random(3)
    img = Image.new("RGB", (1536, 864), (30, 110, 40))
    d = ImageDraw.Draw(img)
    for _ in range(1500):
        x, y = rnd.randrange(1536), rnd.randrange(864)
        g = rnd.choice([(40, 160, 50), (90, 190, 60), (20, 90, 30), (230, 60, 40), (250, 200, 40)])
        d.ellipse((x, y, x + rnd.randrange(30, 90), y + rnd.randrange(14, 40)), fill=g)
    return _png(img)


def pale_sheet_picture() -> bytes:
    """A character on white (the sheets, a snowy or pale room)."""
    img = Image.new("RGB", (1536, 864), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.ellipse((680, 120, 860, 300), fill=(230, 180, 140), outline=(30, 20, 10), width=5)
    d.rectangle((690, 300, 850, 640), fill=(245, 240, 225), outline=(30, 20, 10), width=5)
    d.rectangle((700, 640, 840, 800), fill=(40, 50, 80))
    return _png(img)


def cubes_reference_picture() -> bytes:
    """A story object's reference: bright cubes stacked and loose on a plain cream page."""
    img = Image.new("RGB", (1536, 864), (252, 244, 226))
    d = ImageDraw.Draw(img)
    colors = [(220, 30, 20), (30, 90, 210), (40, 160, 40), (250, 200, 20)]
    for i in range(8):  # a stack: a colour change every 70 px
        d.rectangle((700, 120 + i * 70, 830, 190 + i * 70), fill=colors[i % 4])
    for i, x in enumerate((450, 560, 930, 1040)):
        d.rectangle((x, 640, x + 90, 730), fill=colors[(i + 1) % 4])
    return _png(img)


def test_static_is_caught_and_real_pictures_pass():
    assert clip_review.static_verdict([static_picture()])["problems"] == ["noise"]
    for clean in (cartoon_picture(), jungle_picture(), pale_sheet_picture(), cubes_reference_picture()):
        assert clip_review.static_verdict([clean]) is None
    # one static frame among a clip's frames is enough; unreadable bytes are not static
    assert clip_review.static_verdict([cartoon_picture(), static_picture()])
    assert clip_review.static_verdict([b"not an image"]) is None


def test_static_keyframe_is_flagged_without_asking_a_model(monkeypatch):
    async def never(*a, **k):
        raise AssertionError("the model must not be asked about static")

    monkeypatch.setattr(clip_review, "_ask", never)
    verdict = asyncio.run(clip_review.review_keyframe("1_1", static_picture(), "image/png", ["Lina"], "Lina waves."))
    assert verdict["ok"] is False and verdict["problems"] == ["noise"]


def test_static_is_the_worst_flaw():
    assert sp.flaw({"problems": ["noise"]}) > sp.flaw({"problems": ["deformed", "duplicate", "text", "melting"]})


def _review_failing_with(monkeypatch, error: Exception):
    async def on():
        return True

    async def upload(**k):
        raise error

    from services.ai import fal

    monkeypatch.setattr(clip_review, "enabled", on)
    monkeypatch.setattr(fal, "upload", upload)
    return clip_review._ask("keyframe_review", "1_1", [(cartoon_picture(), "image/png")], ["Lina"], "Lina waves.")


def test_review_pauses_on_an_empty_balance(monkeypatch):
    with pytest.raises(AIConfigError):
        asyncio.run(_review_failing_with(monkeypatch, AIConfigError(LOCKED)))


def test_review_still_skips_a_passing_fault(monkeypatch):
    verdict = asyncio.run(_review_failing_with(monkeypatch, AIError("fal call failed (upload): HTTP 502")))
    assert verdict["ok"] and verdict["skipped"] == "unavailable"


def test_tashkeel_never_stops_the_book(monkeypatch):
    # The owner: vowels are optional, the book goes plain rather than pausing the order.
    pages = [{"id": "p1", "page_text": "يمان يبني برجًا"}]

    async def locked(texts):
        raise AIConfigError(f"fal call failed (book_tashkeel): {LOCKED}")

    async def broken(texts):
        raise AIError("timeout")

    for failing in (locked, broken):
        monkeypatch.setattr(tashkeel_service, "diacritize", failing)
        assert asyncio.run(tashkeel_service.vowelled_pages(pages)) == {}
