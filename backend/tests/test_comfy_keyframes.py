"""Comfy keyframes (phase B): which references go in what order, and the
README prompt template filled only from the plan, profiles and sheets."""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from services import shot_pipeline as sp  # noqa: E402
from services.model_catalog import fits_stage  # noqa: E402

SHEETS = {
    "child": {"url": "/u/1", "label": "Lina", "from_photo": True},
    "father": {"url": "/u/2", "label": "Omar (the child's father)", "from_photo": True},
    "grandmother": {"url": "/u/3", "label": "the child's grandmother"},
    "dog": {"url": "/u/4", "label": "the child's dog"},
}
PROFILES = {
    "child": {"type": "child", "name_en": "Lina", "key_features": "two short braids"},
    "father": {"type": "father", "name_en": "Omar", "key_features": ""},
    "grandmother": {"type": "grandmother", "visual_description": "a kind old woman", "key_features": "round glasses"},
    "dog": {"type": "dog", "visual_description": "a small brown dog", "key_features": ["red collar", "floppy ears"]},
    "uncle": {"type": "uncle", "visual_description": "a tall man with a mustache", "clothing_style": "a green coat"},
}
SCENE = {"scene_index": 2, "background_setting": "a small garden behind the house",
         "visual_description": "the family in the garden", "key_objects": ["blue knitted rabbit", "watering can"]}
TOY = {"url": "/u/toy", "name": "Bunbun", "description": "A blue knitted rabbit plush with long floppy ears."}


def shot(chars, prompt="Lina waters the flowers while her father watches.", shot_type="medium", index=1):
    return {"shot_index": index, "characters": chars, "keyframe_prompt": prompt, "shot_type": shot_type}


def numbering(prompt):
    """The <imageN> numbers the IDENTITY line assigns, in order."""
    identity = next(line for line in prompt.splitlines() if line.startswith("IDENTITY"))
    return [int(n) for n in re.findall(r"<image(\d+)> (?:is|shows)", identity)]


# ---------------------------------------------------------------- references
def test_sheets_family_first_then_toy_and_no_previous_frame_with_people():
    # Qwen copied the people of a previous frame: the child came out twice.
    sh = shot(["grandmother", "father", "child"], "Lina hugs her blue knitted rabbit.")
    refs = sp.comfy_references(sh, SCENE, SHEETS, TOY, "shot")
    assert [r["kind"] for r in refs] == ["sheet", "sheet", "sheet", "toy"]
    assert [r.get("type") for r in refs[:3]] == ["child", "father", "grandmother"]
    assert refs[3]["name"] == "Bunbun"


def test_at_most_five_sheets_and_previous_scene():
    sh = shot(["child", "father", "grandmother", "dog", "uncle"])
    refs = sp.comfy_references(sh, SCENE, {**SHEETS, "uncle": {"url": "/u/5", "label": "the child's uncle"},
                                           "aunt": {"url": "/u/6", "label": "the child's aunt"}}, None, "scene")
    assert len([r for r in refs if r["kind"] == "sheet"]) == 5 and not any(r["kind"].startswith("prev") for r in refs)


@pytest.mark.parametrize("prompt,expected", [
    ("Lina hugs her blue knitted rabbit on the bench.", True),      # the plan's key_objects wording
    ("Lina holds Bunbun up to the sky.", True),                    # the parent's name for it
    ("Lina sets her toy on the grass.", True),                     # a toy word
    ("Lina waters the flowers.", False),                            # not in this shot
    ("Lina waves at a passing toyota.", False),                     # whole words only
])
def test_toy_only_when_the_shot_shows_it(prompt, expected):
    refs = sp.comfy_references(shot(["child"], prompt), SCENE, SHEETS, TOY, None)
    assert any(r["kind"] == "toy" for r in refs) is expected


def test_toy_name_in_arabic_and_without_a_name():
    ar = {"url": "/u/toy", "name": "أرنوبة"}
    assert sp.toy_named_in("Lina hugs أرنوبة tightly.", ar)
    refs = sp.comfy_references(shot(["child"], "Lina hugs her blue knitted rabbit."), SCENE, SHEETS,
                               {**TOY, "name": ""}, None)
    assert refs[-1] == {"kind": "toy", "name": "blue knitted rabbit"}  # how the plan names it


def test_no_toy_without_the_parents_photo():
    refs = sp.comfy_references(shot(["child"], "Lina hugs her toy."), SCENE, SHEETS, None, None)
    assert [r["kind"] for r in refs] == ["sheet"]


def test_empty_shot_gets_a_style_only_reference():
    refs = sp.comfy_references(shot([], "Wide view of the empty garden at dawn."), SCENE, SHEETS, None, None)
    assert refs == [{"kind": "style", "type": "child"}]
    assert sp.comfy_references(shot([], "x"), SCENE, SHEETS, None, "shot") == [{"kind": "prev_shot"}]


def test_favourite_toy_from_the_order():
    order = {"data": {"personalization": {"toy_image_url": "/api/uploads/file/t1", "toy_description_auto": "d",
                                          "favorites": {"toy": {"name": " Bunbun ", "selected": True}}}}}
    assert sp.favourite_toy(order) == {"url": "/api/uploads/file/t1", "name": "Bunbun", "description": "d"}
    assert sp.favourite_toy({"data": {"personalization": {"favorites": {"toy": {"name": "x"}}}}}) is None


# ---------------------------------------------------------------- prompt
def build(chars, prompt="Lina waters the flowers while her father watches.", toy=TOY, previous="shot",
          shot_type="medium"):
    sh = shot(chars, prompt, shot_type)
    refs = sp.comfy_references(sh, SCENE, SHEETS, toy, previous)
    return sp.keyframe_prompt_comfy(SCENE, sh, PROFILES, SHEETS, "Lina", refs), refs


def test_template_order_and_numbering():
    text, refs = build(["child", "father", "dog"], "Lina hugs Bunbun while her father and the dog watch.")
    lines = text.split("\n")
    assert lines[0] == sp.COMFY_INTRO
    assert lines[1].startswith("IDENTITY (most important): <image1> is Lina (keep two short braids exactly")
    assert "<image2> is Omar (the child's father)," in lines[1]  # no empty "keep" for no key features
    assert "<image3> is the child's dog (keep red collar, floppy ears exactly as in the reference)" in lines[1]
    assert "<image4> shows only the child's Bunbun" in lines[1]
    assert "previous shot" not in lines[1]
    assert numbering(text) == list(range(1, len(refs) + 1)) == [1, 2, 3, 4]
    assert lines[2] == sp.COMFY_COPY
    assert lines[3].startswith("The picture shows exactly 3 characters (Lina, Omar and the child's dog): each appears "
                               "exactly once and nobody else is in it")
    assert lines[4].startswith("SCENE: a medium shot, with the characters large in the frame. Lina (<image1>) hugs Bunbun")
    assert "Setting: a small garden behind the house." in lines[4]
    assert lines[-3:] == [sp.COMFY_STYLE, sp.COMFY_FRAME, sp.NO_TEXT]


def test_scene_names_point_at_their_reference():
    # One character apart from the others got a new, fourth child: the tag ties them to their sheet.
    text, _ = build(["child", "father"], "Omar's hat is on the bench. Lina plays with the ball while Omar stands "
                                         "alone by the gate, and Lina laughs.", toy=None, previous=None)
    scene = next(line for line in text.splitlines() if line.startswith("SCENE"))
    assert "Omar's hat" in scene and "Omar (<image2>) stands alone" in scene  # the owner's 's stays as written
    assert "Lina (<image1>) plays" in scene and scene.count("<image1>") == 1  # first mention only
    assert "exactly 2 characters (Lina and Omar)" in text
    solo, _ = build(["dog"], "The dog sleeps.", toy=None, previous=None)
    assert "exactly one character (the child's dog)" in solo and "(<image" not in solo.split("SCENE")[1]


def test_cast_without_a_sheet_is_described():
    text, _ = build(["child", "uncle"], "Lina shows her uncle the flowers.", toy=None, previous=None)
    assert "Also in the picture, without a reference image: the child's uncle, a tall man with a mustache, " \
           "wearing a green coat." in text
    assert numbering(text) == [1]


def test_nobody_in_the_shot():
    text, refs = build([], "Wide view of the empty garden at dawn.", toy=None, previous=None)
    assert sp.COMFY_NOBODY in text and "exactly" not in text.split("SCENE")[0] and sp.COMFY_COPY not in text
    assert "with the main subject large in the frame" in text
    assert "<image1> shows the art style only" in text


def test_no_style_preset_or_face_words():
    text, _ = build(["child", "father"])
    lowered = text.lower()
    for words in ("big eyes", "expressive eyes", "small nose", "simplified nose", "storybook_soft", "art style:"):
        assert words not in lowered
    assert "style reference image" not in lowered


# Words from earlier test stories must never be baked into the code.
STORY_WORDS = ("horse", "saddle", "bridle", "sonic", "hedgehog", "police", "policeman", "yaman", "amr", "israa",
               "costa rica", "beach", "sunset", "yazan", "esraa", "york")  # Lina and Bunbun are this file's own test data
# Names from the test families and stories, in either language.
STORY_NAMES = ("sonic", "سونيك", "yaman", "يمان", "yazan", "يزن", "israa", "esraa", "إسراء", "york", "lina", "لينا",
               "bunbun", "بونبون", "costa", "كوستاريكا")


def test_no_story_names_in_the_planning_rules_or_the_new_modules():
    from services import clip_review, production_service, tashkeel_service, toy_freeze

    texts = {"planning rules": production_service.SYSTEM_MSG, "review": clip_review.SYSTEM,
             "tashkeel": tashkeel_service.SYSTEM, "toy_freeze": Path(toy_freeze.__file__).read_text(encoding="utf-8")}
    for where, text in texts.items():
        for w in STORY_NAMES:
            assert not re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text.lower()), (where, w)
    # the format examples of story_objects aren't the test story's tower
    assert "tower" not in production_service.SYSTEM_MSG.split('"story_objects": [')[1].split("]")[0].lower()


def test_no_story_words_in_the_comfy_code_or_prompts():
    source = Path(sp.__file__).read_text(encoding="utf-8")
    start = source.index("# Comfy keyframes (Qwen Image 2.1 Edit)")
    block = source[start:source.index("# Kling invented a second father")].lower()
    for w in STORY_WORDS:
        assert not re.search(rf"\b{w}\b", block), w
    text, _ = build(["child", "father", "grandmother", "dog"])
    for w in STORY_WORDS:
        assert not re.search(rf"\b{w}\b", text.lower()), w


def test_redraw_note_and_cover():
    refs = [{"kind": "sheet", "type": "child"}, {"kind": "sheet", "type": "father"}, {"kind": "toy", "name": "Bunbun"}]
    cover = sp.cover_prompt_comfy({"cover_prompt": "The family under a big tree.", "title": "x"}, PROFILES, SHEETS, refs)
    assert numbering(cover) == [1, 2, 3]
    assert "SCENE: a storybook cover, with the characters large in the frame. The family under a big tree." in cover
    assert sp.COVER_TITLE_SPACE in cover and cover.endswith(sp.NO_TEXT)


def test_describe_refs_for_the_admin():
    refs = [{"kind": "sheet", "type": "child"}, {"kind": "toy", "name": "Bunbun"}, {"kind": "prev_scene"},
            {"kind": "style", "type": "father"}]
    assert sp.describe_refs(refs, SHEETS) == [
        "<image1> Lina's sheet", "<image2> the child's toy", "<image3> the previous scene's last shot",
        "<image4> Omar (the child's father)'s sheet (style only)"]


# ---------------------------------------------------------------- catalog
def test_comfy_fits_only_its_stages():
    assert fits_stage("comfy_image", "scene_image_generation")
    assert not fits_stage("comfy_image", "child_character_i2i")
    assert not fits_stage("comfy_image", "extra_character_i2i")
    assert fits_stage("fal_image", "child_character_i2i")
    assert fits_stage("comfy_video", "video_generation")


@pytest.mark.parametrize("shot_type,phrase", [("insert", "SCENE: an insert shot"), ("over-the-shoulder", "SCENE: an over-the-shoulder shot"),
                                              ("wide", "SCENE: a wide shot"), (None, "SCENE: a medium shot")])
def test_scene_line_article(shot_type, phrase):
    text, _ = build(["child"], shot_type=shot_type)
    assert phrase in text


def test_identity_copies_the_face_not_the_expression():
    assert "smile" not in sp.COMFY_COPY.lower()
    assert "expressions" in sp.COMFY_COPY.lower() and "follow the scene" in sp.COMFY_COPY.lower()


@pytest.mark.parametrize("raw,kept", [
    ("Tightly curled dark brown hair, broad closed-mouth smile, round cheeks", "Tightly curled dark brown hair, round cheeks"),
    (["red collar", "happy wagging tail", "floppy ears"], "red collar, floppy ears"),
    ("Big laughing eyes; freckles", "freckles"),
    ("", ""),
])
def test_permanent_features_drop_feelings(raw, kept):
    assert sp._features({"key_features": raw}) == kept


def test_plan_rules_film_around_physics_and_keep_the_camera_still():
    from services.production_service import SYSTEM_MSG

    assert "الكاميرا ثابتة دائماً" in SYSTEM_MSG and "اللحظة بعده مباشرة" in SYSTEM_MSG
    assert "ممنوع تعبيرات أو مشاعر" in SYSTEM_MSG
