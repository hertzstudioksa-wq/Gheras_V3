"""Phase M — ElevenLabs Music + storyboard clip visibility unit tests."""
import os
import sys
import asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services import music_generation_service as mgs  # noqa: E402
from services import pricing_service  # noqa: E402
from services.stage_lab_service import EXECUTOR_STATUS, REAL_CALL_STAGES  # noqa: E402
from services.config_service import DEFAULT_MODELS  # noqa: E402
from routes.admin_stage_control_routes import PROVIDER_CHOICES_BY_STAGE  # noqa: E402
from services.provider_test_service import PROVIDERS as PROVIDER_TESTS  # noqa: E402


def _aiorun(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- music adapter ---------------------------------------------------
def test_default_music_model_is_elevenlabs_v1():
    assert mgs.DEFAULT_ELEVENLABS_MUSIC_MODEL == "eleven_music_v1"


def test_clip_duration_is_bounded():
    assert mgs._clip_duration(None) == mgs.DEFAULT_DURATION_SEC
    assert mgs._clip_duration(5) == 10                      # min floor
    assert mgs._clip_duration(99999) == mgs.MAX_DURATION_SEC
    assert mgs._clip_duration(120) == 120


def test_build_prompt_music_mode_avoids_vocals():
    prompt, label = mgs.build_music_prompt("music", None, ["kindness"], "hopeful")
    assert "NO vocals" in prompt
    assert "Cinematic" in prompt or "instrumental" in prompt.lower()
    assert label == "native_music"
    assert "kindness" in prompt
    assert "hopeful" in prompt


def test_build_prompt_human_rhythm_is_prompt_biased():
    prompt, label = mgs.build_music_prompt("human_rhythm", None, [], None)
    assert label == "prompt_biased_no_native_support"
    assert "vocal" in prompt.lower()
    assert "no instruments" in prompt.lower() or "NO instruments" in prompt
    assert "claps" in prompt.lower() or "beatbox" in prompt.lower()


def test_generate_music_none_mode_returns_skip():
    audio, mime, meta = _aiorun(mgs.generate_music("none"))
    assert audio is None
    assert meta["skip_reason"] == "mode_none"
    assert meta["provider"] == "skipped"
    assert meta["mode_implementation"] == "skipped_by_request"


def test_generate_music_without_key_records_missing_key():
    # No ELEVENLABS_API_KEY in this pod → adapter must NOT raise.
    audio, mime, meta = _aiorun(mgs.generate_music("music", duration_seconds=20))
    assert mime == "audio/mpeg"
    if audio is None:
        assert meta["real_call"] is False
        assert meta.get("skip_reason") in ("missing_key", "plan_required",
                                            "auth_failed", "provider_unavailable")


def test_music_real_call_available_no_raise():
    val = _aiorun(mgs.music_real_call_available())
    assert isinstance(val, bool)


def test_mock_music_provider_meta():
    audio, mime, meta = _aiorun(mgs._music_via_mock("test", 30, None))
    assert audio is None and mime == "audio/mpeg"
    assert meta["provider"] == "mock"
    assert meta["skip_reason"] == "mock_provider"


def test_suno_stub_safe():
    audio, mime, meta = _aiorun(mgs._music_via_suno("x", 30, None))
    assert audio is None and mime == "audio/mpeg"
    assert "not_yet_wired" in (meta.get("error") or "")


# ---------- registry / pricing / status ------------------------------------
def test_default_models_music_generation_is_elevenlabs():
    row = DEFAULT_MODELS["music_generation"]
    assert row["provider"] == "elevenlabs"
    assert row["env_key"] == "ELEVENLABS_API_KEY"


def test_music_executor_status_promoted():
    assert EXECUTOR_STATUS["music_generation"] == "real-call-when-keyed"


def test_music_in_real_call_stages():
    assert "music_generation" in REAL_CALL_STAGES


def test_pricing_includes_music_generation():
    cfg = _aiorun(pricing_service.get_pricing_config())
    costs = cfg["per_stage_costs"]
    assert costs["music_generation"] >= 0.50


def test_stage_control_music_provider_choices():
    choices = PROVIDER_CHOICES_BY_STAGE["music_generation"]
    assert "elevenlabs" in choices
    assert "suno" in choices
    assert "mock" in choices


# ---------- provider tests -------------------------------------------------
def test_provider_test_registry_includes_elevenlabs_music():
    assert "elevenlabs_music" in PROVIDER_TESTS


def test_elevenlabs_music_test_returns_meta_when_key_missing():
    out = _aiorun(PROVIDER_TESTS["elevenlabs_music"]())
    assert out["provider"] == "elevenlabs_music"
    assert "ok" in out
    if not out["ok"]:
        assert out["secret_source"] in ("missing", "env", "override")
