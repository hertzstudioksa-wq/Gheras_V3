"""Recurring story objects (a fixed look, one reference picture), gaze and hands:
from the second real story, where the block tower changed shape every shot, the
"bigger" rebuilt tower came out shorter and the parents stared into the camera."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from services import production_service as ps, shot_pipeline as sp  # noqa: E402

KITE = {"key": "kite", "name_en": "the red kite", "look": "a red diamond kite with a yellow cross frame and a blue tail.",
        "sheet_view": "flat on the ground with its tail curled beside it"}
BUNBUN = {"key": "rabbit", "name_en": "Bunbun the rabbit", "look": "a blue knitted rabbit plush with long floppy ears"}
TOY = {"url": "/u/toy", "name": "Bunbun", "description": "A blue knitted rabbit plush with long floppy ears."}
PLAN = {"id": "p", "story_objects": [KITE, BUNBUN, {"key": "x", "name_en": "", "look": "nameless"}]}
SHEETS = {"child": {"url": "/u/1", "label": "Lina", "from_photo": True},
          "father": {"url": "/u/2", "label": "Omar (the child's father)", "from_photo": True}}
PROFILES = {"child": {"type": "child", "name_en": "Lina"}, "father": {"type": "father", "name_en": "Omar"}}
SCENE = {"scene_index": 1, "background_setting": "a windy hill"}


def shot(chars, objects, prompt="Lina holds the red kite up, its top reaching her father's chin."):
    return {"shot_index": 1, "characters": chars, "objects": objects, "keyframe_prompt": prompt, "shot_type": "wide"}


# ---------------------------------------------------------------- the plan
def test_the_plan_keeps_its_objects_and_each_shot_names_only_known_ones():
    payload = {"production_plan": {"title": "t"}, "characters": [{"type": "child", "name_en": "Lina"}],
               "story_objects": [{"key": "Red Kite", "name_en": "the red kite", "look": "red diamond kite"},
                                 {"key": "red kite", "name_en": "dup", "look": "dup"},
                                 {"key": "cake", "name_en": "", "look": "no name"}],
               "scenes": [{"scene_index": 1, "shots": [
                   {"narration_line": "a", "characters": ["child"], "objects": ["Red Kite", "moon"]},
                   {"narration_line": "b", "characters": ["child"]}]}]}
    docs = ps.build_docs({"id": "o", "data": {}}, payload, "run", "ai")
    assert docs["plan"]["story_objects"] == [{"key": "red_kite", "name_en": "the red kite", "look": "red diamond kite",
                                              "sheet_view": ""}]
    assert [sh["objects"] for sh in docs["scenes"][0]["shots"]] == [["red_kite"], []]


def test_the_plan_rules_ask_for_looks_body_sizes_gaze_and_still_hands():
    for words in ("story_objects", "sheet_view", "الأحجام بالجسم", "لا أحد ينظر إلى الكاميرا", "الأيدي",
                  "never at the camera", "measured against a character's body", "a hand touching an object stays on it"):
        assert words in ps.SYSTEM_MSG, words


# ---------------------------------------------------------------- the shot prompt
def test_story_objects_skip_the_toy_and_incomplete_entries():
    assert list(sp.story_objects(PLAN)) == ["kite", "rabbit"]
    assert list(sp.story_objects(PLAN, TOY)) == ["kite"]  # the toy's photo is its reference
    objects = sp.story_objects(PLAN)
    assert [o["key"] for o in sp.shot_objects(shot([], ["rabbit", "kite", "rabbit", "moon"]), objects)] == \
        ["rabbit", "kite"]


def test_comfy_keyframe_gets_the_object_reference_its_fixed_look_and_a_gaze():
    objects = sp.shot_objects(shot([], ["kite"]), sp.story_objects(PLAN))
    sh = shot(["child", "father"], ["kite"])
    refs = sp.comfy_references(sh, SCENE, SHEETS, None, "shot", objects)
    assert [r["kind"] for r in refs] == ["sheet", "sheet", "object"]
    prompt = sp.keyframe_prompt_comfy(SCENE, sh, PROFILES, SHEETS, "Lina", refs, objects)
    assert "<image3> shows only the red kite: copy its material, shape and colors exactly, not its arrangement" in prompt
    assert ("OBJECTS (they look exactly the same in every picture of this story): the red kite: a red diamond kite "
            "with a yellow cross frame and a blue tail — not its arrangement: how many pieces, how big") in prompt
    assert sp.GAZE in prompt
    assert sp.describe_refs(refs, SHEETS)[2] == "<image3> the red kite's reference"


def test_no_gaze_line_without_people_and_no_objects_line_without_objects():
    sh = shot([], [], "The empty hill at dusk.")
    prompt = sp.keyframe_prompt_comfy(SCENE, sh, PROFILES, SHEETS, "Lina", sp.comfy_references(sh, SCENE, SHEETS, None, None))
    assert sp.GAZE not in prompt and "OBJECTS" not in prompt


def test_gpt_keyframe_gets_the_look_and_the_gaze_too():
    objects = sp.shot_objects(shot([], ["kite"]), sp.story_objects(PLAN))
    from services import engine_config

    text = sp.keyframe_prompt(SCENE, shot(["child"], ["kite"]), PROFILES, SHEETS, "Lina", [],
                              engine_config.DEFAULT_STYLE, objects)
    assert sp.GAZE in text and "the red kite: a red diamond kite" in text


def test_the_object_reference_is_the_object_alone():
    prompt = sp.object_sheet_prompt(sp.story_objects(PLAN)["kite"])
    # the reference view comes alone: the name pulled a finished tower over "loose cubes"
    assert ("SUBJECT, as a clear reference picture: flat on the ground with its tail curled beside it. Look: a red "
            "diamond kite") in prompt and "the red kite" not in prompt
    assert "SUBJECT: the red kite alone" in sp.object_sheet_prompt({**sp.story_objects(PLAN)["kite"], "sheet_view": ""})
    assert "No people, no hands" in prompt and "<image1> shows the art style only" in prompt and sp.NO_TEXT in prompt


def test_clips_keep_everyone_off_the_camera():
    assert "nobody turns to look at the camera" in sp.wan_motion_prompt("Omar claps.", 2)
    from services import engine_config

    assert "Nobody turns to look at the camera." in sp.motion_prompt("Omar claps.", [], engine_config.DEFAULT_STYLE,
                                                                    ["Omar"])


def test_a_favourite_toy_without_a_photo_is_not_called_uploaded():
    # "uploaded as a photo" made the plan leave a Sonic plush seen in every shot out of story_objects
    order = {"data": {"child": {"name": "يمان"}, "goal": {}, "characters": [],
                      "personalization": {"favorites": {"toy": {"selected": True, "name": "دبدوب سونيك"}},
                                          "toy_image_url": ""}}, "duration": {"seconds": 45}}
    text = ps._build_user_prompt(order, {}, 4)
    assert "(بدون صورة)" in text and "مرفوع كصورة" not in text and "story_objects" in text
    order["data"]["personalization"]["toy_image_url"] = "/api/uploads/file/x"
    assert "مرفوع كصورة" in ps._build_user_prompt(order, {}, 4)
