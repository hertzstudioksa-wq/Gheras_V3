"""Phase D.3 — Customer inputs propagation tests.

Tests scenario + production + scene_image context builders directly on
synthetic order shapes, proving that inputs surface where they should.
Avoids live LLM calls where possible.
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")
sys.path.insert(0, "/app/backend")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _order_fixture(*, with_extra_chars=False, with_toy=False, with_toy_desc=False,
                   hijab=False, appearance_notes=None, mentioned_only=False,
                   extra_without_image=False):
    """Synthetic order — child only by default, add extras per flags."""
    chars = []
    if with_extra_chars:
        chars.append({
            "type": "mother", "name": "سعاد", "role": "visible",
            "image_url": "/api/uploads/file/fake-mother",
            "visual_description_auto": "A kind mother with a warm green scarf and brown eyes"
                                        if not extra_without_image else None,
        })
    if mentioned_only:
        chars.append({"type": "friend", "name": "عمر", "role": "mentioned"})
    if extra_without_image:
        chars[-1]["image_url"] = None
        chars[-1]["visual_description_auto"] = None
    pers = {
        "favorites": {"toy": {"selected": True, "name": "دبدوب أزرق"}},
        "custom_notes": "يحب القصص الهادئة قبل النوم",
    }
    if with_toy:
        pers["toy_image_url"] = "/api/uploads/file/fake-toy"
    if with_toy_desc:
        pers["toy_description_auto"] = "A soft blue teddy bear with a red ribbon and button eyes"
    order = {
        "id": "test-order",
        "user_id": "test-user",
        "data": {
            "child": {
                "name": "محمود", "age": 5, "gender": "male",
                "image_url": "/api/uploads/file/fake-child",
                "hijab": hijab,
                "appearance_notes": appearance_notes or "شعر أسود مجعد",
            },
            "goal": {
                "context": "فقد لعبته المفضلة وحزن كثيراً",
                "custom_subcategory": None,
            },
            "personalization": pers,
            "characters": chars,
            "audio_background": {"mode": "music"},
        },
        "enriched": {
            "category_name": "التعامل مع المشاعر",
            "subcategory_name": "التعامل مع الفقد",
            "type_name": "مغامرة عاطفية",
            "tone_name": "دافئ",
            "setting_name": "البيت",
            "language_name": "عربية فصحى مبسطة",
            "voice_name": "راوٍ لطيف",
        },
        "duration": {"label": "دقيقتان", "seconds": 120, "scene_target": 5},
    }
    return order


def test_1_child_only():
    """TEST 1 — Child only. Baseline: no regression."""
    from services.scenario_service import _build_scenario_context
    from prompt_engine import build_prompt as build_scenarios_prompt
    o = _order_fixture()
    ctx = _build_scenario_context(o)
    assert ctx["child_appearance_notes"] == "شعر أسود مجعد"
    assert ctx["child_hijab"] == "لا"
    # No toy image/desc → toy_summary has only the name from favorites
    assert "دبدوب" in ctx["toy_summary"]
    assert "teddy bear" not in ctx["toy_summary"]
    assert "لا يوجد" in ctx["characters_summary"]
    prompt = build_scenarios_prompt(o["data"], o["enriched"])
    assert "شعر أسود مجعد" in prompt
    assert "teddy bear" not in prompt  # no toy desc injected without image
    print("[TEST 1] child-only — ctx + prompt OK ✓")


def test_2_visible_extra_character():
    from services.scenario_service import _build_scenario_context
    from prompt_engine import build_prompt as build_scenarios_prompt
    o = _order_fixture(with_extra_chars=True)
    ctx = _build_scenario_context(o)
    assert "سعاد" in ctx["characters_summary"]
    assert "warm green scarf" in ctx["characters_summary"]  # vision visuals surfaced
    prompt = build_scenarios_prompt(o["data"], o["enriched"])
    assert "warm green scarf" in prompt
    print("[TEST 2] visible+image+desc — surfaced in scenario ctx + prompt ✓")


def test_3_mentioned_only():
    from services.scenario_service import _build_scenario_context
    from prompt_engine import build_prompt as build_scenarios_prompt
    o = _order_fixture(mentioned_only=True, extra_without_image=True)
    ctx = _build_scenario_context(o)
    assert "عمر" in ctx["characters_summary"]
    prompt = build_scenarios_prompt(o["data"], o["enriched"])
    assert "عمر" in prompt
    assert "mentioned" in ctx["characters_summary"] or "role=" in ctx["characters_summary"]
    # No invented visual description
    assert "visual_description" not in ctx["characters_summary"]
    print("[TEST 3] mentioned-only (no image) — text-only, no invented visuals ✓")


def test_4_toy_propagation():
    from services.scenario_service import _build_scenario_context
    from services.production_service import _build_user_prompt as _build_production_prompt
    from prompt_engine import build_prompt as build_scenarios_prompt
    o = _order_fixture(with_toy=True, with_toy_desc=True)

    # scenario ctx
    ctx = _build_scenario_context(o)
    assert "دبدوب أزرق" in ctx["toy_summary"]
    assert "teddy bear" in ctx["toy_summary"]

    # default scenario prompt
    prompt = build_scenarios_prompt(o["data"], o["enriched"])
    assert "teddy bear" in prompt
    assert "يجب أن تظهر هذه اللعبة" in prompt

    # production prompt
    fake_scenario = {"title": "t", "short_summary": "s", "emotional_angle": "a",
                     "learning_goal": "g", "visual_style_hint": "h"}
    pprompt = _build_production_prompt(o, fake_scenario, target_scenes=5)
    assert "teddy bear" in pprompt
    assert "key_objects" in pprompt
    print("[TEST 4] toy image → scenario + production prompts ✓")


def test_5_combined():
    """TEST 5 — child + 2 visible chars with images + 1 toy image + notes."""
    from services.scenario_service import _build_scenario_context
    from services.production_service import _build_user_prompt as _build_production_prompt
    o = _order_fixture(with_extra_chars=True, with_toy=True, with_toy_desc=True,
                       hijab=False, appearance_notes="عينان خضراوان")
    # Add a second visible character
    o["data"]["characters"].append({
        "type": "sibling", "name": "لمى", "role": "visible",
        "image_url": "/api/uploads/file/fake-sister",
        "visual_description_auto": "A younger sister with curly hair and a yellow dress",
    })
    ctx = _build_scenario_context(o)
    # Scenario context
    assert "سعاد" in ctx["characters_summary"]
    assert "لمى" in ctx["characters_summary"]
    assert "green scarf" in ctx["characters_summary"]
    assert "yellow dress" in ctx["characters_summary"]
    assert "teddy bear" in ctx["toy_summary"]
    assert "عينان خضراوان" in ctx["child_appearance_notes"]
    # Production prompt
    fake_scenario = {"title": "t", "short_summary": "s", "emotional_angle": "a",
                     "learning_goal": "g", "visual_style_hint": "h"}
    pprompt = _build_production_prompt(o, fake_scenario, target_scenes=5)
    assert "سعاد" in pprompt
    assert "لمى" in pprompt
    assert "auto_visual_description" in pprompt
    assert "green scarf" in pprompt
    assert "yellow dress" in pprompt
    assert "teddy bear" in pprompt
    assert "عينان خضراوان" in pprompt
    print("[TEST 5] combined — all inputs surface in scenario + production ✓")


def test_6_scene_image_context():
    """Scene image builder also exposes the new fields."""
    from services.generation_orchestrator import _build_scene_image_context
    o = _order_fixture(with_extra_chars=True, with_toy=True, with_toy_desc=True,
                       appearance_notes="شعر طويل")
    plan = {"title": "pln", "style_guide": {"art_direction": "storybook"}}
    scene = {"scene_index": 1, "title": "s1", "visual_description": "vd",
             "key_objects": ["tree"], "image_prompt": {"prompt_text": "p"}}
    ctx = _build_scene_image_context(o, plan, scene)
    assert ctx["child_appearance_notes"] == "شعر طويل"
    assert ctx["child_hijab"] in ("نعم", "لا")
    assert "teddy bear" in ctx["toy_summary"]
    assert "warm green scarf" in ctx["extra_characters_visuals"]
    print("[TEST 6] scene_image context — appearance+hijab+toy+extras surfaced ✓")


async def test_7_extra_characters_service_no_regression():
    """When order has no visible characters with image, service returns skipped."""
    from services.extra_characters_service import safe_run
    o = _order_fixture()  # no extra chars
    r = await safe_run(o)
    assert r.get("skipped") is True, r
    assert r.get("reason") == "no_visible_characters_with_image", r
    print("[TEST 7] extra_characters_service — legacy order unaffected ✓")


if __name__ == "__main__":
    test_1_child_only()
    test_2_visible_extra_character()
    test_3_mentioned_only()
    test_4_toy_propagation()
    test_5_combined()
    test_6_scene_image_context()
    run(test_7_extra_characters_service_no_regression())
    print()
    print("=== ALL TESTS PASS ✓ ===")
