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


def test_each_extra_side_is_drawn_on_its_own_with_the_sheets_prompt_at_the_photos_angle():
    sheet_prompt = house_style.character_sheet_prompt("Omar, the child's father", adult=True)
    assert house_style.FACE_FORWARD in sheet_prompt and "full-body" in sheet_prompt
    angle = head_views.angle_prompt(sheet_prompt)
    assert house_style.FACE_FORWARD not in angle and head_views.ANGLE_LINE in angle
    assert angle.endswith(head_views.HEAD_ONLY) and "full-body standing view" not in angle
    assert "The first reference image is the photo (use it ONLY for identity)." in angle  # one photo per drawing


def test_the_heads_are_laid_out_on_a_square_so_each_face_is_big():
    # next to the body in one wide picture, the faces reached Qwen a few dozen pixels high
    img = Image.new("RGB", (1536, 600), "white")
    for i, color in enumerate(((200, 120, 90), (90, 120, 200), (90, 200, 120))):
        Image.Image.paste(img, color, (60 + i * 500, 100, 400 + i * 500, 520))
    out = io.BytesIO(); img.save(out, "PNG")
    square = Image.open(io.BytesIO(head_views.grid(out.getvalue())))
    assert square.size == (head_views.GRID_SIDE, head_views.GRID_SIDE)
    cell = head_views.GRID_SIDE // 2
    assert square.getpixel((cell // 2, cell // 2)) == (200, 120, 90)          # front, top left
    assert square.getpixel((cell + cell // 2, cell // 2)) == (90, 120, 200)   # three-quarter, top right
    assert square.getpixel((cell // 2, cell + cell // 2)) == (90, 200, 120)   # side, bottom left
    plain = _png((800, 600), (90, 90, 90))
    assert head_views.grid(plain) == plain  # one drawing: left as it is


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


def test_the_parents_extra_photos_become_heads_one_drawing_each_at_medium_quality(monkeypatch):
    # all the photos in one sheet call came out as a semi-realistic painted portrait
    from services import child_character_service

    calls = []

    async def gpt(source, prompt, provider, model, style_ref=None, quality="high"):
        calls.append((source, quality, head_views.ANGLE_LINE in prompt))
        return {"image_bytes": _png((800, 900), (120, 90, 60))}

    async def qwen(sheet):
        raise AssertionError("the sheet-only heads are for orders without extra photos")

    monkeypatch.delenv("GHERAS_FAKE_PROVIDERS", raising=False)
    monkeypatch.setattr(child_character_service, "_generate_character", gpt)
    monkeypatch.setattr(head_views, "draw", qwen)
    saved = []

    async def save(png):
        saved.append(png)
        return "/u/heads"

    sheet = _png((1024, 1536))
    img = Image.open(io.BytesIO(sheet)).convert("RGB")
    Image.Image.paste(img, (40, 40, 40), (400, 100, 620, 1400))  # a figure on white
    out = io.BytesIO(); img.save(out, "PNG")
    fields = asyncio.run(head_views.for_asset(out.getvalue(), save, photos=[b"3q", b"side"], sheet_prompt="a child sheet prompt",
                                              provider="fal_image", model="openai/gpt-image-2", style_ref=b"style"))
    assert sorted(c[0] for c in calls) == [b"3q", b"side"] and all(c[1] == "medium" and c[2] for c in calls)
    assert fields == {"head_views_url": "/u/heads", "head_views_angles": 2, "head_views_model": "openai/gpt-image-2",
                      "head_views_quality": "medium", "head_views_gpu_seconds": None}  # nothing left from before
    row = Image.open(io.BytesIO(saved[0]))
    assert row.height == head_views.CARD_HEIGHT and row.width > 3 * 300  # the sheet's head + the two sides


SHEETS = {"father": {"url": "/u/2", "label": "Omar (the child's father)", "from_photo": True, "head_views_url": "/u/9"},
          "child": {"url": "/u/1", "label": "Lina", "from_photo": True}}


def test_the_face_reference_follows_its_sheet_and_belongs_to_that_person_alone():
    sh = {"characters": ["child", "father"], "keyframe_prompt": "Lina hugs her father."}
    refs = sp.comfy_references(sh, {"scene_index": 1}, SHEETS, None, None)
    assert [r["kind"] for r in refs] == ["sheet", "sheet", "faces"] and refs[2]["type"] == "father"
    text = sp.comfy_identity(refs, {}, SHEETS)
    assert f"<image1> is Lina ({sp.FROM_PHOTO_FACE}; {sp.CHILD_FACE})" in text  # the father's beard stays his
    assert "<image2> is Omar (the child's father) (their full figure and clothes; their face is <image3>)" in text
    assert "<image3> is Omar (the child's father)'s face from the front, three-quarter and side" in text
    assert "nobody else takes anything from them" in text
    assert sp.describe_refs(refs, SHEETS)[2] == "<image3> Omar (the child's father)'s face from three sides"


def test_without_room_the_face_reference_is_left_out():
    sh = {"characters": ["child", "father"], "keyframe_prompt": "x"}
    objects = [{"key": f"o{i}", "name": f"thing {i}"} for i in range(sp.comfy.MAX_REFS - 2)]
    refs = sp.comfy_references(sh, {"scene_index": 1}, SHEETS, None, None, objects)
    assert len(refs) == sp.comfy.MAX_REFS and "faces" not in [r["kind"] for r in refs]


def test_a_gpt_picture_numbers_the_sheets_around_the_face_pictures():
    scene = {"scene_index": 1, "background_setting": "a garden"}
    sh = {"characters": ["father", "child"], "keyframe_prompt": "Omar watches Lina water the roses.",
          "shot_type": "medium"}
    profiles = {"father": {"type": "father", "name_en": "Omar"}, "child": {"type": "child", "name_en": "Lina"}}
    style = {"style_text": "s", "frame_rules": "f"}
    text = sp.keyframe_prompt(scene, sh, profiles, SHEETS, "Lina", ["n1", "n2", "n3"], style, None,
                              ["father", None, "child"])
    assert "Omar (reference image 1)" in text and "Lina (reference image 3)" in text
