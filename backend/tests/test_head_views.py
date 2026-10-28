"""More sides of a face: the extra photos reach the sheet, and the face from three sides rides
next to the sheet as one reference for the shot pictures."""
import asyncio
import io
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from PIL import Image  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from models import CharacterPayload, ChildPayload  # noqa: E402
from services import head_views, house_style, privacy_service  # noqa: E402
from services import shot_pipeline as sp  # noqa: E402


def _png(size, color="white", mode="RGB"):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, "PNG")
    return out.getvalue()


def test_the_order_takes_up_to_two_more_sides_of_each_face():
    child = ChildPayload(name="Lina", age=5, gender="female", image_url="/f/1", extra_image_urls=["/f/2", "/f/3"])
    assert child.extra_image_urls == ["/f/2", "/f/3"]
    assert ChildPayload(name="Lina", age=5, gender="female", image_url="/f/1").extra_image_urls == []
    assert CharacterPayload(type="father", role="visible", image_url="/f/4", extra_image_urls=["/f/5"]).extra_image_urls
    with pytest.raises(ValidationError):
        ChildPayload(name="Lina", age=5, gender="female", image_url="/f/1", extra_image_urls=["/a", "/b", "/c"])


def test_every_side_is_the_parents_photo_and_is_deleted_with_the_others():
    data = {"child": {"image_url": "/api/uploads/file/c1", "extra_image_urls": ["/api/uploads/file/c2"]},
            "characters": [{"image_url": "/api/uploads/file/f1", "extra_image_urls": ["/api/uploads/file/f2",
                                                                                     "/api/uploads/file/f3"]},
                           {"image_url": None}],
            "personalization": {"toy_image_url": "/api/uploads/file/t1"}}
    assert privacy_service.photo_urls(data) == ["/api/uploads/file/c1", "/api/uploads/file/c2", "/api/uploads/file/f1",
                                                "/api/uploads/file/f2", "/api/uploads/file/f3", "/api/uploads/file/t1"]
    assert privacy_service.order_photo_ids({"data": data}) == ["c1", "c2", "f1", "f2", "f3", "t1"]


def test_the_sheet_prompt_names_the_photos_of_every_side():
    one = house_style.character_sheet_prompt("Omar, the child's father")
    assert "The first reference image is the photo (use it ONLY for identity)." in one
    three = house_style.character_sheet_prompt("Omar, the child's father", photos=3)
    assert "The first 3 reference images are photos of the same person from different sides" in three
    assert "The first reference image is the photo" not in three and house_style.STYLE_REF_NOTE in three


def test_the_card_is_the_sheet_and_the_three_heads_side_by_side():
    sheet = _png((1024, 1536), (200, 120, 90))
    heads = _png((1536, 864), (90, 120, 200, 0), "RGBA")  # a transparent background becomes white
    card = Image.open(io.BytesIO(head_views.card(sheet, heads)))
    assert card.height == head_views.CARD_HEIGHT and card.width == 683 + 1820
    assert card.getpixel((10, 10)) == (200, 120, 90) and card.getpixel((683 + 10, 10)) == (255, 255, 255)


def test_without_a_sheet_or_in_rehearsal_there_are_no_heads(monkeypatch):
    assert asyncio.run(head_views.draw(b"")) is None
    monkeypatch.setenv("GHERAS_FAKE_PROVIDERS", "1")
    assert asyncio.run(head_views.draw(b"sheet")) is None


def test_the_heads_are_drawn_from_the_cartoon_sheet_alone(monkeypatch):
    # drawn from the real photos too, they came out as painted portraits and the father
    # stood out as a realistic man among cartoon children
    from services.ai import image_client

    seen = {}

    async def comfy(**k):
        seen.update(k)
        return b"png", "image/png", {"gpu_seconds": 12.0}

    monkeypatch.delenv("GHERAS_FAKE_PROVIDERS", raising=False)
    monkeypatch.setattr(image_client, "comfy_image", comfy)
    assert asyncio.run(head_views.draw(b"sheet")) == (b"png", 12.0)
    assert seen["references"] == [b"sheet"] and "photo" not in seen["prompt"]


def test_several_photos_keep_the_cartoon_of_the_style_reference():
    three = house_style.character_sheet_prompt("Omar, the child's father", photos=3, adult=True)
    assert house_style.CARTOON_LOCK in three
    assert house_style.CARTOON_LOCK not in house_style.character_sheet_prompt("Omar, the child's father", adult=True)


def test_a_card_reference_says_it_is_one_person_from_three_sides():
    sheets = {"father": {"url": "/u/2", "label": "Omar (the child's father)", "from_photo": True,
                         "head_views_url": "/u/9"},
              "child": {"url": "/u/1", "label": "Lina", "from_photo": True}}
    text = sp.comfy_identity([{"kind": "sheet", "type": "child"}, {"kind": "sheet", "type": "father"}], {}, sheets)
    assert f"<image1> is Lina ({sp.FROM_PHOTO_FACE})" in text
    assert f"<image2> is Omar (the child's father) ({head_views.CARD_NOTE}; {sp.FROM_PHOTO_FACE})" in text
