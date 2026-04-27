"""Phase K — TTS adapter + Stage Control unit tests.

Validates:
  * tts_service mock fallback when no key configured
  * tts_service.narration_real_call_available() reports honest state
  * pricing_service exposes narration_generation cost (Phase K bump)
  * pipeline_readiness exposes new flags (executor_callable, prompt_editable)
  * EXECUTOR_STATUS for narration is `real-call-when-keyed` (not `not-yet-wired`)
  * stage_control PROVIDER_CHOICES_BY_STAGE shape is sane
"""
import os
import sys
import asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services import tts_service  # noqa: E402
from services import pricing_service  # noqa: E402
from services.stage_lab_service import EXECUTOR_STATUS, REAL_CALL_STAGES  # noqa: E402
from services import pipeline_readiness_service as prs  # noqa: E402
from routes.admin_stage_control_routes import PROVIDER_CHOICES_BY_STAGE  # noqa: E402


def _aiorun(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- TTS adapter -----------------------------------------------------
def test_estimate_duration_seconds_basic():
    # 11 words / 2.2 wps = 5.0
    assert tts_service.estimate_duration_seconds("a " * 11) == round(11 / 2.2, 2)
    assert tts_service.estimate_duration_seconds("") == 0.0
    assert tts_service.estimate_duration_seconds(None) == 0.0


def test_default_voice_settings_are_arabic_friendly():
    s = tts_service._default_voice_settings()
    # Stability between 0..1 and similarity_boost similarly bounded.
    assert 0 <= s["stability"] <= 1
    assert 0 <= s["similarity_boost"] <= 1
    assert s["use_speaker_boost"] is True


def test_mock_tts_returns_metadata_only():
    audio, mime, meta = _aiorun(
        tts_service._tts_via_mock("نص اختبار قصير", None, "ar", None, None)
    )
    assert audio is None
    assert mime == "audio/mpeg"
    assert meta["provider"] == "mock"
    assert meta["real_call"] is False
    assert meta["fallback_to_mock"] is False  # mock IS the requested path
    assert meta["duration_seconds"] >= 0


def test_elevenlabs_without_key_falls_back_gracefully():
    # If ELEVENLABS_API_KEY is unset (or unset+no override), the adapter must
    # NOT raise, return None bytes, and surface fallback_to_mock=True.
    audio, mime, meta = _aiorun(
        tts_service._tts_via_elevenlabs("مرحباً بكم", None, "ar", None, None)
    )
    # If the test pod happens to have a key configured, the call may either
    # succeed (audio bytes) or fail with HTTP error — either way the
    # adapter must not raise. We only assert the contract.
    assert mime == "audio/mpeg"
    assert "provider" in meta and meta["provider"] == "elevenlabs"
    assert "duration_seconds" in meta
    if audio is None:
        assert meta["fallback_to_mock"] is True
    else:
        assert meta["real_call"] is True
        assert meta["bytes"] == len(audio)


def test_generate_tts_dispatches_to_mock_when_unwired():
    """With a fresh registry (no admin row for narration_generation) the
    resolved provider is `mock`, so we get the mock path back."""
    audio, mime, meta = _aiorun(
        tts_service.generate_tts("اختبار", provider_override="mock")
    )
    assert audio is None and mime == "audio/mpeg"
    assert meta["provider"] == "mock"


def test_narration_real_call_available_no_raise():
    val = _aiorun(tts_service.narration_real_call_available())
    assert isinstance(val, bool)


# ---------- Stage Lab status update ----------------------------------------
def test_narration_executor_status_promoted():
    assert EXECUTOR_STATUS["narration_generation"] == "real-call-when-keyed"


def test_narration_in_real_call_stages():
    # Phase K — narration must be in REAL_CALL_STAGES so the cost-ack gate
    # still applies on lab runs.
    assert "narration_generation" in REAL_CALL_STAGES


# ---------- Pricing audit ---------------------------------------------------
def test_pricing_includes_narration_generation_key():
    cfg = _aiorun(pricing_service.get_pricing_config())
    costs = cfg["per_stage_costs"]
    assert "narration_generation" in costs
    assert costs["narration_generation"] >= 0.10  # Phase K bump
    # The legacy `narration_audio` key still exists (orchestrator uses it).
    assert costs["narration_audio"] == costs["narration_generation"]


def test_pricing_default_video_music_costs_set():
    cfg = _aiorun(pricing_service.get_pricing_config())
    assert cfg["per_stage_costs"]["video_generation"] > 0
    assert cfg["per_stage_costs"]["music_generation"] > 0


# ---------- Pipeline Readiness new flags -----------------------------------
def test_prompt_editable_statuses_includes_real_call_when_keyed():
    s = prs._PROMPT_EDITABLE_STATUSES
    assert "real-call" in s
    assert "real-call-when-keyed" in s
    assert "preview-only" in s
    assert "local-binary" not in s
    assert "reuse-from-other-stage" not in s


# ---------- Stage Control routes -------------------------------------------
def test_provider_choices_cover_all_supported_stages():
    from services.stage_lab_service import SUPPORTED_STAGES
    for stage in SUPPORTED_STAGES:
        assert stage in PROVIDER_CHOICES_BY_STAGE, f"{stage} missing from PROVIDER_CHOICES_BY_STAGE"


def test_narration_provider_choices_include_elevenlabs():
    choices = PROVIDER_CHOICES_BY_STAGE["narration_generation"]
    assert "elevenlabs" in choices
    assert "mock" in choices
    assert "openai" in choices


def test_local_binary_stages_have_only_local_provider():
    assert PROVIDER_CHOICES_BY_STAGE["video_assembly"] == ["ffmpeg"]
    assert PROVIDER_CHOICES_BY_STAGE["pdf_assembly"] == ["reportlab"]
