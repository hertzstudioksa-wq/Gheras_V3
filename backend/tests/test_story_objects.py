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
                                              "sheet_view": "", "toy": False}]
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
    assert "No people, no hands" in prompt and "<image1>, which is an empty page" in prompt and sp.NO_TEXT in prompt


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


def test_story_objects_stay_lifeless_in_clips():
    # the Sonic plush raised its arms and opened its mouth when the boys cheered
    text = sp.wan_motion_prompt("The boys cheer.", 2, objects=["the big blue Sonic plush"])
    assert "The big blue Sonic plush is a lifeless object: never moving, waving, blinking or opening a mouth by " \
           "itself" in text
    assert "are lifeless objects" in sp.lifeless(["the kite", "the cake"]) and sp.lifeless([]) == ""
    from services import engine_config

    assert "lifeless" in sp.motion_prompt("The boys cheer.", [], engine_config.DEFAULT_STYLE, ["Lina"], ["the kite"])


def test_an_object_reference_keeps_its_colours_to_itself():
    objects = sp.shot_objects(shot([], ["kite"]), sp.story_objects(PLAN))
    refs = sp.comfy_references(shot(["child"], ["kite"]), SCENE, SHEETS, None, None, objects)
    assert "people keep their own clothes and shoes" in sp.comfy_identity(refs, PROFILES, SHEETS)


def test_a_likeness_only_flag_is_soft():
    assert sp.passes({"ok": False, "problems": ["wrong_look"]}) and sp.passes(None) and sp.passes({"ok": True})
    assert not sp.passes({"ok": False, "problems": ["wrong_look", "duplicate"]})
    assert not sp.passes({"ok": False, "problems": ["noise"]})


def test_sheets_keep_the_clothes_and_colours_but_not_the_print():
    # a word printed on a shirt came out scrambled in every frame of the clips
    from services import house_style

    for outfit in ("", "same as in the photo", "same as in the photo, plus a blue police cap", "pajamas with stars"):
        rule = house_style.outfit_rule(outfit)
        assert house_style.NO_PRINT in rule
    assert "same colors" in house_style.NO_PRINT and "logos" in house_style.NO_PRINT
    assert house_style.NO_PRINT in house_style.character_sheet_prompt("the person in the photo")


TEDDY = {"key": "teddy", "name_en": "the brown teddy", "look": "a brown plush bear with a red bow", "toy": True}


def test_a_toy_with_a_face_is_drawn_and_animated_as_a_toy():
    # a plush shaped like a famous cartoon came out as the character: standing, glossy eyes, blinking
    payload = {"production_plan": {}, "characters": [{"type": "child"}],
               "story_objects": [{"key": "teddy", "name_en": "the teddy", "look": "brown plush", "toy": "true"},
                                 {"key": "kite", "name_en": "the kite", "look": "red kite", "toy": False}],
               "scenes": [{"scene_index": 1, "shots": [{"narration_line": "a", "objects": ["teddy", "kite"]}]}]}
    assert [o["toy"] for o in ps.build_docs({"id": "o", "data": {}}, payload, "r", "ai")["plan"]["story_objects"]] == \
        [True, False]
    objects = sp.story_objects({"story_objects": [TEDDY, KITE]})
    assert objects["teddy"]["toy"] and not objects["kite"]["toy"]
    assert sp.TOY_NOTE in sp.objects_line([objects["teddy"]]) and sp.TOY_NOTE not in sp.objects_line([objects["kite"]])
    assert sp.TOY_NOTE in sp.object_sheet_prompt(objects["teddy"]) and sp.TOY_NOTE not in sp.object_sheet_prompt(objects["kite"])
    refs = sp.comfy_references(shot(["child"], ["teddy"]), SCENE, SHEETS, None, None, [objects["teddy"]])
    assert sp.TOY_POSE in sp.comfy_identity(refs, PROFILES, SHEETS)
    text = sp.wan_motion_prompt("Lina cheers.", 1, objects=["the brown teddy"], toys=["the brown teddy"])
    assert "The brown teddy is a toy frozen like a statue: its eyes stay wide open and fixed" in text
    # the owner: a famous character's doll keeps its famous design; a hero moves and talks
    assert "famous design exactly" in sp.TOY_NOTE and "official plush" in sp.TOY_NOTE
    for words in ("toy = true", "بشكلها المشهور", "تتحرك وتتكلم عادي، وليست من story_objects", "لا تقف ولا تمشي وحدها"):
        assert words in ps.SYSTEM_MSG


def test_two_characters_of_the_same_type_get_their_own_keys():
    # two friends were both "friend": the second boy had no sheet and no place in the shots
    from services import house_style

    chars = [{"type": "friend", "name": "A"}, {"type": "friend", "name": "B"}, {"type": "father"},
             {"type": "mother", "role": "mentioned"}, {"type": "friend", "name": "C"}]
    assert house_style.cast_keys(chars) == ["friend", "friend_2", "father", "mother", "friend_3"]
    assert house_style.base_type("friend_2") == "friend" and house_style.base_type("grand_parent") == "grand_parent"
    assert sp._label({"type": "friend_2", "name_en": "Baraa"}, "Yaman") == "Baraa (the child's friend)"
    order = {"data": {"child": {"name": "x"}, "goal": {}, "personalization": {}, "characters": chars},
             "duration": {"seconds": 60}}
    text = ps._build_user_prompt(order, {}, 5)
    assert "- friend (A)" in text and "- friend_2 (B)" in text and "- friend_3 (C)" in text
    assert "friend_2" in ps.SYSTEM_MSG


def test_a_worn_thing_named_only_in_the_features_goes_on_the_sheet():
    # the plan put each boy's bike helmet in key_features: no sheet had it, the shots did
    assert ps.worn_in_outfit("same as in the photo", "light-brown hair; orange kids' bike helmet") == \
        "same as in the photo, plus orange kids' bike helmet"
    assert ps.worn_in_outfit("same as in the photo, plus a blue police cap", "curly hair; blue police cap") == \
        "same as in the photo, plus a blue police cap"
    assert ps.worn_in_outfit("same as in the photo", "short dark hair; full beard") == "same as in the photo"
    from services import house_style

    rule = house_style.outfit_rule(ps.worn_in_outfit("same as in the photo", ["yellow kids' bike helmet"]))
    assert "yellow kids' bike helmet" in rule


def test_shots_queue_in_story_order_and_references_start_from_a_blank_page():
    # scene 4's picture arrived before scene 1's; a cast sheet as the style sample put the child on the scooter
    keys = [sp.story_order({"scene_index": s}, {"shot_index": i}) for s, i in ((4, 1), (1, 2), (1, 1), (10, 1))]
    assert sorted(keys) == ["001.001", "001.002", "004.001", "010.001"]
    from PIL import Image
    import io as _io

    page = Image.open(_io.BytesIO(sp.blank_canvas()))
    assert page.size == (1536, 864) and len(set(page.getdata())) == 1
    assert "sheet" not in sp.object_sheet_prompt(sp.story_objects(PLAN)["kite"]).lower()


def test_a_toy_the_words_name_joins_the_shot_with_the_toy_rules():
    # the setting had the doll "visible in the distance" in a shot that didn't list it: it rode a scooter
    hero = {"key": "hero_doll", "name_en": "the big Captain Comet doll", "look": "a plush hero", "toy": True}
    bike = {"key": "bike", "name_en": "Lina's green bike", "look": "a green bike"}
    objects = sp.story_objects({"story_objects": [KITE, bike, hero]})
    far = {"scene_index": 3, "background_setting": "the park path, Comet visible far away on the bench"}
    keys = lambda sh, sc=None: [o["key"] for o in sp.shot_objects(sh, objects, sc)]  # noqa: E731
    assert keys(shot(["child"], ["kite"], "Lina runs."), far) == ["hero_doll", "kite"]  # the toy first
    assert keys(shot(["child"], ["kite", "bike"], "Lina looks at the captain's ship."), far) == ["hero_doll", "kite"]
    assert keys(shot(["child"], [], "Lina runs toward Captain Comet.")) == ["hero_doll"]
    # its owner's name, a word every toy shares, or a non-toy mentioned don't add anything
    assert keys(shot(["child"], [], "Lina hugs her big doll and rides her green bike."), SCENE) == []
    assert sp._toy_words(objects["hero_doll"]) == {"captain", "comet"}
    assert sp._toy_words({"key": "lina_teddy", "name": "Lina's teddy bear"}) == {"teddy", "bear"}


def test_a_toy_only_named_in_the_words_stays_small_and_gets_no_reference_picture():
    # with its reference picture in, Qwen drew the far-away doll big in front, wearing the child's helmet
    hero = {"key": "hero_doll", "name_en": "the big Captain Comet doll", "look": "a plush hero", "toy": True}
    objects = sp.story_objects({"story_objects": [KITE, hero]})
    far = {"scene_index": 3, "background_setting": "the park path, Comet visible far away on the bench"}
    got = sp.shot_objects(shot(["child"], ["kite"], "Lina runs."), objects, far)
    assert [(o["key"], bool(o.get("background"))) for o in got] == [("hero_doll", True), ("kite", False)]
    listed = sp.shot_objects(shot(["child"], ["hero_doll"], "Lina hugs Captain Comet."), objects, far)
    assert not listed[0].get("background")  # the plan put it in the shot: it gets its picture
    line = sp.objects_line(got)
    assert sp.BACKGROUND_NOTE in line and line.count(sp.BACKGROUND_NOTE) == 1
    refs = sp.comfy_references(shot(["child"], ["kite"]), far, SHEETS, None, None,
                               [o for o in got if not o.get("background")])
    assert [r.get("key") for r in refs if r["kind"] == "object"] == ["kite"]
