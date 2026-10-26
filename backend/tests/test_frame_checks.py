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


def test_the_review_is_told_the_story_objects(monkeypatch):
    # a character plush was counted as a fifth person
    import json

    from services.ai import fal, text_client

    seen = {}

    async def on():
        return True

    async def upload(**k):
        return "https://x/u.png"

    async def vision(**k):
        if k["system"] == clip_review.PEOPLE_SYSTEM:  # the head count runs beside the review
            return '{"people": ["a girl waving"]}'
        seen.update(k)
        return '{"ok": true, "problems": []}'

    monkeypatch.setattr(clip_review, "enabled", on)
    monkeypatch.setattr(fal, "upload", upload)
    monkeypatch.setattr(text_client, "generate_vision", vision)
    verdict = asyncio.run(clip_review.review_keyframe("1_1", cartoon_picture(), "image/png", ["Lina"], "Lina waves.",
                                                      None, ["the red kite"]))
    assert verdict["ok"] and json.loads(seen["user"])["story_objects"] == ["the red kite"]
    assert "never people" in seen["system"] and "object_alive" in seen["system"]
    assert clip_review._problem("toy moving by itself (alive)") == "object_alive"


def test_a_verdict_reads_the_first_json_object_only():
    two = '{"ok": false, "problems": ["duplicate"], "note": "twice"}\n\n{"ok": true, "problems": []}'
    assert clip_review._verdict(two)["problems"] == ["duplicate"]
    assert clip_review._verdict('Sure: {"ok": true, "problems": [], "note": "a {brace} inside"}')["ok"]


def test_a_thin_object_on_a_blank_page_is_not_static():
    # a scooter reference: a few thin colourful parts on a cream page
    img = Image.new("RGB", (1536, 864), (250, 243, 228))
    d = ImageDraw.Draw(img)
    d.rectangle((700, 150, 712, 650), fill=(240, 240, 240))
    d.rectangle((640, 140, 780, 160), fill=(220, 40, 40))
    d.rectangle((560, 640, 900, 660), fill=(70, 160, 230))
    for x in (580, 620, 860):
        d.ellipse((x - 20, 660, x + 20, 700), fill=(30, 30, 30))
    assert clip_review.static_verdict([_png(img)]) is None


def test_a_keyframe_is_never_flagged_for_a_toy_moving(monkeypatch):
    # a still picture can't show anything moving by itself; the flag cost three takes per shot
    async def ask(*a, **k):
        return {"ok": False, "problems": ["object_alive"], "note": "x"}

    async def count(image):
        return ["a girl with braids"]

    monkeypatch.setattr(clip_review, "_ask", ask)
    monkeypatch.setattr(clip_review, "people_in", count)
    verdict = asyncio.run(clip_review.review_keyframe("1_1", cartoon_picture(), "image/png", ["Lina"], "x"))
    assert verdict["ok"] and verdict["problems"] == []


def test_a_head_count_over_the_cast_holds_the_picture(monkeypatch):
    # the full review said four people on a frame with five: the shot was animated
    async def ask(*a, **k):
        return {"ok": False, "problems": ["wrong_look"], "people_seen": 2, "note": "the hair differs"}

    async def five(image):
        return ["girl, braids", "man, beard", "boy, green cap", "boy, green cap, red shirt", "old woman"]

    monkeypatch.setattr(clip_review, "_ask", ask)
    monkeypatch.setattr(clip_review, "people_in", five)
    cast = ["Lina", "Omar (the child's father)", "the child's friend", "the child's grandmother"]
    verdict = asyncio.run(clip_review.review_keyframe("5_1", cartoon_picture(), "image/png", cast, "x"))
    assert not verdict["ok"] and verdict["problems"] == ["wrong_look", "extra_person"]
    assert verdict["people_seen"] == 5 and verdict["note"].startswith("head count: 5 people for 4 — girl, braids")
    assert "the hair differs" in verdict["note"]
    assert sp.held_problems(verdict) == ["extra_person"]


def test_a_head_count_at_or_under_the_cast_changes_nothing():
    passed = {"ok": True, "problems": [], "people_seen": 2}
    assert clip_review.counted_extra(passed, ["a", "b"], ["Lina", "Omar"]) is passed
    assert clip_review.counted_extra(passed, ["a"], ["Lina", "the child's dog"]) is passed  # animals aren't listed
    assert clip_review.counted_extra(passed, None, ["Lina"]) is passed  # the count couldn't run
    assert clip_review.counted_extra(passed, ["a", "b"], ["Lina"])["problems"] == ["extra_person"]


def test_a_take_with_a_held_problem_loses_to_soft_ones():
    assert sp.flaw({"problems": ["extra_person"]}) > sp.flaw({"problems": ["wrong_look", "action_missing", "mood_mismatch"]})


def test_the_head_count_is_off_in_the_rehearsal(monkeypatch):
    monkeypatch.setenv("GHERAS_FAKE_PROVIDERS", "1")
    assert asyncio.run(clip_review.people_in(cartoon_picture())) is None


def test_a_cast_member_in_another_ones_place_is_a_held_flaw():
    # GPT put the friend where the child should stand apart; the review called it a likeness flaw
    for words in ("role_swap", "Roles swapped", "wrong person in the main role", "switched places"):
        assert clip_review._problem(words) == "role_swap", words
    assert clip_review._problem("wrong look") == "wrong_look"
    assert "role_swap" in clip_review.SYSTEM and "role_swap" in sp.HOLD_PROBLEMS
    assert sp.held_problems({"ok": False, "problems": ["role_swap", "wrong_look"]}) == ["role_swap"]


def test_who_holds_a_toy_is_unknown_in_the_rehearsal(monkeypatch):
    monkeypatch.setenv("GHERAS_FAKE_PROVIDERS", "1")
    assert asyncio.run(clip_review.toys_held(cartoon_picture(), ["the teddy"])) is None


def test_who_holds_a_toy_reads_each_name(monkeypatch):
    from services.ai import fal, text_client

    monkeypatch.delenv("GHERAS_FAKE_PROVIDERS", raising=False)

    async def on():
        return True

    async def upload(**k):
        return "https://x/u.jpg"

    async def vision(**k):
        return 'Sure: {"held": {"The Teddy": false, "the kite": true, "ball": "maybe"}}'

    monkeypatch.setattr(clip_review, "enabled", on)
    monkeypatch.setattr(fal, "upload", upload)
    monkeypatch.setattr(text_client, "generate_vision", vision)
    held = asyncio.run(clip_review.toys_held(cartoon_picture(), ["the teddy", "the kite", "ball"]))
    assert held == {"the teddy": False, "the kite": True}  # an unclear answer stays unknown
