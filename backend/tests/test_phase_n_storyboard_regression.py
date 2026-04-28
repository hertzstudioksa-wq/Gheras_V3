"""Regression — storyboard must not crash on schema drift in scene plans.

Bug: `scene_plans.video_prompt` is sometimes a STRING (current Claude prompt
schema), sometimes a DICT (legacy fallback). Storyboard route used
`(sp.get('video_prompt') or {}).get('prompt_text')[:300]` which crashes with
`AttributeError: 'str' object has no attribute 'get'` whenever the field is
a string — breaking ALL newer orders' storyboard view.

These tests pin the helpers so the bug can never silently come back.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from routes.admin_storyboard_routes import (  # noqa: E402
    _extract_video_prompt_text,
    _flatten_prompt_field,
    _safe_dict,
)
from services.generation_orchestrator import _safe_dict as orch_safe_dict, _safe_dict_or_str  # noqa: E402


# ---------------------------------------------------------------------------
def test_video_prompt_extracts_string_value():
    """New plans store video_prompt as a single string."""
    sp = {"video_prompt": "Wide cinematic shot of the child"}
    assert _extract_video_prompt_text(sp) == "Wide cinematic shot of the child"


def test_video_prompt_extracts_dict_value():
    """Legacy plans store video_prompt as {prompt_text, camera_motion_hint, ...}."""
    sp = {"video_prompt": {"prompt_text": "Slow push-in", "camera_motion_hint": "dolly"}}
    assert _extract_video_prompt_text(sp) == "Slow push-in"


def test_video_prompt_handles_empty_or_missing():
    assert _extract_video_prompt_text({}) is None
    assert _extract_video_prompt_text({"video_prompt": None}) is None
    assert _extract_video_prompt_text({"video_prompt": ""}) is None
    assert _extract_video_prompt_text({"video_prompt": "   "}) is None
    assert _extract_video_prompt_text({"video_prompt": {}}) is None


def test_video_prompt_truncates_long_strings():
    long_text = "x" * 1000
    out = _extract_video_prompt_text({"video_prompt": long_text})
    assert out is not None
    assert len(out) == 300


def test_flatten_prompt_field_handles_all_shapes():
    # string
    assert _flatten_prompt_field("hello") == "hello"
    # dict with prompt_text
    assert _flatten_prompt_field({"prompt_text": "hi"}) == "hi"
    # dict with text fallback
    assert _flatten_prompt_field({"text": "alt"}) == "alt"
    # dict with neither
    assert _flatten_prompt_field({"foo": "bar"}) is None
    # None / empty
    assert _flatten_prompt_field(None) is None
    assert _flatten_prompt_field("") is None
    assert _flatten_prompt_field({}) is None
    # accidental list (must not crash)
    assert _flatten_prompt_field(["a", "b"]) is None
    # custom max_len
    assert _flatten_prompt_field("a" * 500, 100) == "a" * 100


def test_safe_dict_storyboard_helper():
    assert _safe_dict({"a": 1}) == {"a": 1}
    assert _safe_dict("string-not-dict") == {}
    assert _safe_dict(None) == {}
    assert _safe_dict([]) == {}
    assert _safe_dict(42) == {}


def test_orchestrator_safe_dict_helper_matches():
    """Same contract in the orchestrator helper used by _execute_scene_image."""
    assert orch_safe_dict({"a": 1}) == {"a": 1}
    assert orch_safe_dict("legacy-string") == {}
    assert orch_safe_dict(None) == {}


def test_orchestrator_safe_dict_or_str_preserves_string():
    """Used by video_generation submit loop — must keep string for fallback."""
    assert _safe_dict_or_str("a string prompt") == "a string prompt"
    out = _safe_dict_or_str({"prompt_text": "x"})
    assert isinstance(out, dict)
    assert out["prompt_text"] == "x"
    assert _safe_dict_or_str(None) == ""
    assert _safe_dict_or_str("") == ""
    assert _safe_dict_or_str("   ") == ""
