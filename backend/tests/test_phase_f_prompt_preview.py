"""Phase F — Effective Prompt Preview tests."""
import os, sys, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services import stage_lab_service as sls  # noqa: E402
from services.stage_lab_service import (  # noqa: E402
    SUPPORTED_STAGES, REAL_CALL_STAGES, _detect_unresolved,
)


def _aiorun(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _stub_resolvers(monkeypatch, *,
                    template=None,           # admin template doc or None
                    rendered=None,            # tuple (text, source, reason)
                    model=("anthropic", "claude-x", "fallback"),
                    transport="emergent"):
    async def _resolve_prompt(stage_key, ctx, required_vars=None):
        if rendered is not None:
            return rendered
        return None, "default", "no_active_template"

    async def _resolve_model(stage_key, p, m):
        return model

    async def _resolve_transport(stage_key):
        return transport

    async def _find_one(query, projection=None):
        if query.get("stage_key") and template:
            return template
        return None

    async def _orders_find_one(query, projection=None):
        return None

    monkeypatch.setattr(sls, "resolve_prompt", _resolve_prompt)
    monkeypatch.setattr(sls, "resolve_model", _resolve_model)
    monkeypatch.setattr(sls, "resolve_transport", _resolve_transport)

    class _C:
        def __init__(self, *_a, **_k): pass
        async def find_one(self, *a, **k):
            if a and isinstance(a[0], dict) and a[0].get("stage_key"):
                return template
            return None

    class _DB:
        prompt_templates = _C()
        orders = _C()
        production_plans = _C()
        scene_plans = _C()
    monkeypatch.setattr(sls, "db", _DB())


# --- _detect_unresolved -----------------------------------------------------
def test_detect_unresolved_finds_dollar_var():
    placeholders = _detect_unresolved("Hello ${name}, age is $age years.")
    assert "name" in placeholders and "age" in placeholders


def test_detect_unresolved_empty():
    assert _detect_unresolved("") == []
    assert _detect_unresolved(None) == []


def test_detect_unresolved_no_vars():
    assert _detect_unresolved("Plain text only.") == []


# --- SUPPORTED_STAGES sanity ------------------------------------------------
def test_required_stages_supported():
    required = {
        "scenario_generation", "production_planning", "scene_image_generation",
        "child_character_i2i", "narration_generation", "video_generation",
        "music_generation",
    }
    assert required.issubset(set(SUPPORTED_STAGES))


def test_real_call_stages_subset():
    assert REAL_CALL_STAGES.issubset(set(SUPPORTED_STAGES))


# --- build_effective_prompt_preview structure ------------------------------
def test_preview_returns_required_debug_fields(monkeypatch):
    _stub_resolvers(monkeypatch,
        template={"id": "t1", "version": 3, "template_text": "Hello $child_name",
                  "variables": ["child_name"]},
        rendered=("Hello ليلى", "admin", "template_id=t1 version=3"),
    )
    out = _aiorun(sls.build_effective_prompt_preview(
        "scenario_generation", {"child_name": "ليلى", "child_age": 5},
    ))
    for key in ("stage_key", "provider", "model_name", "model_source",
                "transport", "env_key", "prompt_source", "template_id",
                "template_version", "render_note", "fallback_would_happen",
                "effective_prompt", "prompt_hash", "unresolved_placeholders",
                "warnings", "context_source", "context_used",
                "estimated_cost", "currency"):
        assert key in out, f"missing key: {key}"
    assert out["prompt_source"] == "admin"
    assert out["fallback_would_happen"] is False
    assert out["template_id"] == "t1"
    assert out["template_version"] == 3
    assert out["prompt_hash"].startswith("sha256:")


def test_preview_marks_fallback_when_no_admin_template(monkeypatch):
    _stub_resolvers(monkeypatch, template=None,
                    rendered=(None, "default", "no_active_template"))
    out = _aiorun(sls.build_effective_prompt_preview(
        "music_generation", {"child_name": "Sami"},
    ))
    assert out["prompt_source"] == "default"
    assert out["fallback_would_happen"] is True
    assert out["template_id"] is None
    assert any("لا يوجد قالب admin" in w for w in out["warnings"])


def test_preview_surfaces_template_present_but_unused(monkeypatch):
    _stub_resolvers(monkeypatch,
        template={"id": "t9", "version": 1, "template_text": "Hello $missing_var"},
        rendered=(None, "default", "missing_variable:missing_var"),
    )
    out = _aiorun(sls.build_effective_prompt_preview(
        "production_planning", {"child_name": "X", "child_age": "5"},
    ))
    assert out["fallback_would_happen"] is True
    # Effective prompt should fall through to safe_substitute on the raw template,
    # leaving `$missing_var` literal in the output.
    assert "$missing_var" in out["effective_prompt"]
    assert "missing_var" in out["unresolved_placeholders"]
    assert any("لم يُستخدم" in w for w in out["warnings"])


def test_preview_unsupported_stage_raises(monkeypatch):
    _stub_resolvers(monkeypatch)
    try:
        _aiorun(sls.build_effective_prompt_preview("garbage", {}))
    except ValueError:
        return
    raise AssertionError("expected ValueError")


def test_preview_estimated_cost_returned(monkeypatch):
    _stub_resolvers(monkeypatch, template=None,
                    rendered=(None, "default", "no_active_template"))
    async def _ec(_):
        return 1.23
    monkeypatch.setattr(sls, "_estimated_cost_for", _ec)
    out = _aiorun(sls.build_effective_prompt_preview("scene_image_generation", {}))
    assert out["estimated_cost"] == 1.23
    assert out["currency"] == "SAR"
