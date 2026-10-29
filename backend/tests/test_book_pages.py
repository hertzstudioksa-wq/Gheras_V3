"""The book: hero portraits keep the whole head, and the text isn't vowelled unless the admin asks."""
import asyncio
import io
import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from PIL import Image, ImageDraw  # noqa: E402

from services import book_renderer as br  # noqa: E402


def _sheet() -> bytes:
    """A slim child under a big helmet on a white sheet (the friend whose portrait was cut at the chin)."""
    img = Image.new("RGB", (1024, 1536), "white")
    d = ImageDraw.Draw(img)
    d.ellipse((392, 160, 632, 330), fill=(60, 160, 60))      # helmet, wider than the body
    d.ellipse((430, 250, 594, 430), fill=(230, 180, 140))    # face
    d.rectangle((452, 430, 572, 900), fill=(70, 110, 200))   # slim body
    d.rectangle((462, 900, 562, 1380), fill=(40, 40, 60))    # legs
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def test_a_portrait_keeps_the_whole_head_with_a_white_margin(tmp_path):
    name = br._portrait(_sheet(), "friend", tmp_path / "p.jpg")
    img = Image.open(tmp_path / name).convert("L")
    w, h = img.size
    drawn = img.point(lambda v: 255 if v < 238 else 0).getbbox()
    # the helmet and face never touch the frame's sides or top (they used to be cut)
    assert drawn[0] > w * .02 and drawn[2] < w * .98 and drawn[1] > 0
    assert drawn[3] == h  # head and shoulders: the body goes on below the frame


def test_a_second_friend_is_a_person_with_their_own_role():
    from services import house_style

    assert house_style.base_type("friend_2") == "friend" and "friend" in br.PEOPLE
    assert br.ROLE_AR[house_style.base_type("friend_2")] == "الصديق"


def test_the_book_text_is_not_vowelled_unless_turned_on(monkeypatch):
    class Settings:
        def __init__(self, value):
            self.value = value

        async def find_one(self, *a, **k):
            return None if self.value is None else {"value": self.value}

    class DB:
        settings = None

    for value, on in ((None, False), (False, False), (True, True)):
        fake = DB()
        fake.settings = Settings(value)
        monkeypatch.setattr(br, "db", fake)
        assert asyncio.run(br.tashkeel_on()) is on
    source = Path(br.__file__).read_text(encoding="utf-8")
    assert "if await tashkeel_on():" in source  # the vowelling call sits behind the switch
