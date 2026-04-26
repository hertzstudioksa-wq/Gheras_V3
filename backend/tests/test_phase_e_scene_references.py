"""Phase E — scene_reference_service + image_generation_service unit tests.

These tests exercise the pure logic only — no DB, no real provider calls.
DB lookups inside scene_reference_service are stubbed via monkeypatching the
two `_load_*` helpers.
"""
import os, sys, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services import scene_reference_service as srs  # noqa: E402
from services.image_generation_service import _build_image_prompt  # noqa: E402


def _aiorun(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _stub_loaders(monkeypatch, child=None, extras=None, profiles=None):
    async def _ch(_):  return child
    async def _ex(_):  return extras or []
    async def _pr(*_): return profiles or {}
    monkeypatch.setattr(srs, "_load_child_asset", _ch)
    monkeypatch.setattr(srs, "_load_extra_assets", _ex)
    monkeypatch.setattr(srs, "_load_character_profiles", _pr)


# ---------------------------------------------------------------------------
def test_no_assets_yields_empty_package(monkeypatch):
    _stub_loaders(monkeypatch)
    order = {"id": "o1", "data": {}}
    plan = {"id": "p1"}
    scene = {"id": "s1", "characters_in_scene": [{"role_in_scene": "child"}]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert pkg["injected_count"] == 0
    assert pkg["child_ref"] is None
    assert pkg["available"]["child"] is False
    assert pkg["extra_char_refs"] == []


def test_child_injected_when_role_child_present(monkeypatch):
    _stub_loaders(monkeypatch, child={"generated_image_url": "/api/uploads/file/aaa"})
    order = {"id": "o1", "data": {"child": {"name": "ليلى"}}}
    plan = {"id": "p1"}
    scene = {"id": "s1", "characters_in_scene": [{"role_in_scene": "child"}]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert pkg["child_ref"] is not None
    assert pkg["child_ref"]["name"] == "ليلى"
    assert pkg["injected_count"] == 1


def test_child_skipped_when_not_relevant(monkeypatch):
    _stub_loaders(monkeypatch, child={"generated_image_url": "/api/uploads/file/aaa"})
    order = {"id": "o1", "data": {"child": {"name": "ليلى"}}}
    plan = {"id": "p1"}
    scene = {"id": "s1", "characters_in_scene": [{"role_in_scene": "mother"}]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert pkg["child_ref"] is None
    assert any(r["kind"] == "child" and r["reason"] == "scene_not_relevant"
               for r in pkg["skipped_reasons"])


def test_extra_character_matched_by_type(monkeypatch):
    extras = [{
        "character_index": 0,
        "character_type":  "mother",
        "character_name":  "أم سامي",
        "generated_image_url": "/api/uploads/file/mom",
    }]
    profiles = {"mp1": {"id": "mp1", "type": "mother"}}
    _stub_loaders(monkeypatch, extras=extras, profiles=profiles)
    order = {"id": "o1", "data": {"characters": [{"type": "mother", "name": "أم سامي"}]}}
    plan = {"id": "p1"}
    scene = {"id": "s1", "characters_in_scene": [
        {"role_in_scene": "child"}, {"role_in_scene": "mother"},
    ]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert len(pkg["extra_char_refs"]) == 1
    assert pkg["extra_char_refs"][0]["character_id"] == "mp1"
    assert pkg["extra_char_refs"][0]["character_index"] == 0


def test_extra_capped_at_two_with_trimmed_reason(monkeypatch):
    extras = [
        {"character_index": i,
         "character_type":  t,
         "character_name":  t,
         "generated_image_url": f"/api/uploads/file/{t}"}
        for i, t in enumerate(["mother", "father", "sister"])
    ]
    profiles = {f"id-{t}": {"id": f"id-{t}", "type": t}
                for t in ("mother", "father", "sister")}
    _stub_loaders(monkeypatch, extras=extras, profiles=profiles)
    order = {"id": "o1"}
    plan = {"id": "p1"}
    scene = {"id": "s1", "characters_in_scene": [
        {"role_in_scene": "mother"},
        {"role_in_scene": "father"},
        {"role_in_scene": "sister"},
    ]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert len(pkg["extra_char_refs"]) == srs.MAX_EXTRA_REFS == 2
    trimmed = [r for r in pkg["skipped_reasons"]
               if r["reason"] == "too_many_references_trimmed"]
    assert len(trimmed) == 1
    assert trimmed[0]["kind"] == "extra"


def test_extra_skipped_when_missing_asset(monkeypatch):
    extras = [{
        "character_index": 0,
        "character_type":  "mother",
        "character_name":  "ام",
        "generated_image_url": None,
    }]
    _stub_loaders(monkeypatch, extras=extras)
    order = {"id": "o1"}
    plan = {"id": "p1"}
    scene = {"id": "s1", "characters_in_scene": [{"role_in_scene": "mother"}]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    # Won't appear in extras (filter on generated_image_url=None at load time)
    # so the missing_asset path requires a row that did pass the loader.
    # We model that here by manually wiring an asset with empty URL via load_extras stub.
    # Either way, scene_not_relevant won't fire because mother is in scene.
    # The filtered query in real life excludes None URLs, so this test just
    # confirms no crash + nothing injected.
    assert pkg["extra_char_refs"] == []


def test_toy_injected_when_key_objects_match(monkeypatch):
    _stub_loaders(monkeypatch)
    order = {
        "id": "o1",
        "data": {"personalization": {
            "toy_image_url": "/api/uploads/file/toy",
            "toy_description_auto": "small red car",
            "favorites": {"toy": {"name": "سيارة"}},
        }},
    }
    plan = {"id": "p1"}
    scene = {"id": "s1", "key_objects": ["سيارة حمراء"]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert pkg["toy_ref"] is not None
    assert pkg["toy_ref"]["description"] == "small red car"
    assert pkg["available"]["toy"] is True


def test_toy_skipped_when_not_relevant(monkeypatch):
    _stub_loaders(monkeypatch)
    order = {
        "id": "o1",
        "data": {"personalization": {
            "toy_image_url": "/api/uploads/file/toy",
            "favorites": {"toy": {"name": "سيارة"}},
        }},
    }
    plan = {"id": "p1"}
    scene = {"id": "s1", "key_objects": ["كتاب"]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert pkg["toy_ref"] is None
    assert any(r["kind"] == "toy" and r["reason"] == "scene_not_relevant"
               for r in pkg["skipped_reasons"])


def test_caps_total_ceiling_4(monkeypatch):
    """child(1) + extras(≤2) + toy(1) → max 4 references per scene."""
    extras = [
        {"character_index": i, "character_type": t, "character_name": t,
         "generated_image_url": f"/x/{t}"}
        for i, t in enumerate(["mother", "father", "sister", "uncle"])
    ]
    _stub_loaders(monkeypatch,
        child={"generated_image_url": "/x/child"},
        extras=extras,
    )
    order = {
        "id": "o1",
        "data": {
            "child": {"name": "Sami"},
            "personalization": {"toy_image_url": "/x/toy",
                                "favorites": {"toy": {"name": "Ball"}}},
        },
    }
    plan = {"id": "p1"}
    scene = {"id": "s1",
             "characters_in_scene": [
                 {"role_in_scene": "child"},
                 {"role_in_scene": "mother"},
                 {"role_in_scene": "father"},
                 {"role_in_scene": "sister"},
                 {"role_in_scene": "uncle"},
             ],
             "key_objects": ["Ball"]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert pkg["injected_count"] == 4   # child + 2 extras + toy
    assert len(pkg["extra_char_refs"]) == 2
    assert pkg["child_ref"] and pkg["toy_ref"]


def test_prompt_augmentation_includes_attached_kinds(monkeypatch):
    _stub_loaders(monkeypatch,
        child={"generated_image_url": "/x/child"},
    )
    order = {"id": "o1", "data": {"child": {"name": "Sami"}}}
    plan = {"id": "p1"}
    scene = {"id": "s1", "characters_in_scene": [{"role_in_scene": "child"}]}
    pkg = _aiorun(srs.resolve_scene_references(order, plan, scene))
    assert "CHILD reference" in pkg["prompt_augmentation"]


# ---------------------------------------------------------------------------
def test_image_prompt_builder_includes_augmentation():
    p = _build_image_prompt(
        scene_prompt="A bedroom at night.",
        style_guide={"art_direction": "soft watercolor", "palette": "warm pastels"},
        character_note="Child in pajamas.",
        prompt_augmentation="CHILD reference attached.",
    )
    assert "soft watercolor" in p
    assert "CHILD reference attached" in p
    assert "Children's storybook illustration" in p


def test_image_prompt_builder_no_augmentation_back_compat():
    p = _build_image_prompt("A scene.", {}, "", "")
    assert "Children's storybook illustration" in p
    assert "CHILD reference" not in p
