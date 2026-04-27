"""Phase L — fal.ai Kling video adapter + Stage Control extensions."""
import os
import sys
import asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services import video_generation_service as vgs  # noqa: E402
from services import pricing_service  # noqa: E402
from services.stage_lab_service import EXECUTOR_STATUS, REAL_CALL_STAGES  # noqa: E402
from services.config_service import DEFAULT_MODELS, PROVIDER_ENV_MAP  # noqa: E402
from routes.admin_stage_control_routes import PROVIDER_CHOICES_BY_STAGE  # noqa: E402
from services.provider_test_service import PROVIDERS as PROVIDER_TESTS  # noqa: E402


def _aiorun(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------- adapter contract -----------------------------------------------
def test_default_kling_model_is_v21_standard_i2v():
    assert vgs.DEFAULT_KLING_MODEL == "fal-ai/kling-video/v2.1/standard/image-to-video"


def test_i2v_to_t2v_swap():
    assert vgs._i2v_to_t2v(
        "fal-ai/kling-video/v2.1/standard/image-to-video"
    ) == "fal-ai/kling-video/v2.1/standard/text-to-video"
    # Non-i2v slug returns None.
    assert vgs._i2v_to_t2v("fal-ai/some-other/text-to-video") is None


def test_build_payload_picks_image_when_present():
    p = vgs._build_payload({"prompt": "a cat", "image_url": "https://x/y.png", "duration": 5}, has_image=True)
    assert "image_url" in p
    assert p["prompt"] == "a cat"
    assert p["duration"] == "5"
    assert p["aspect_ratio"] == "16:9"


def test_build_payload_t2v_drops_image():
    p = vgs._build_payload({"prompt": "warm", "image_url": "https://x/y.png"}, has_image=False)
    assert "image_url" not in p


def test_video_real_call_available_no_raise():
    val = _aiorun(vgs.video_real_call_available())
    assert isinstance(val, bool)


def test_submit_clip_without_key_returns_honest_meta():
    # No FAL_KEY in this pod → we expect (None, meta_with_secret_source=missing).
    req_id, meta = _aiorun(vgs.submit_clip({"prompt": "hi"}))
    # Either no key (most likely) or a real call. Assert contract.
    assert "provider" in meta
    if req_id is None:
        assert meta.get("fallback_to_mock") is True
        assert meta.get("real_call") is False
    else:
        assert meta.get("real_call") is True


def test_mock_video_provider_meta():
    audio, mime, meta = _aiorun(vgs._video_via_mock({"duration": 5}))
    assert audio is None and mime == "video/mp4"
    assert meta["provider"] == "mock"
    assert meta["real_call"] is False


def test_sora_and_luma_stubs_are_safe():
    for fn in (vgs._video_via_sora, vgs._video_via_luma):
        a, m, meta = _aiorun(fn({"duration": 5}))
        assert a is None and m == "video/mp4"
        assert meta["fallback_to_mock"] is True
        assert "not_yet_wired" in (meta.get("error") or "")


# ---------- registry / pricing / status ------------------------------------
def test_default_models_video_generation_is_kling():
    row = DEFAULT_MODELS["video_generation"]
    assert row["provider"] == "kling"
    assert row["model_name"].startswith("fal-ai/kling-video/")
    assert row["env_key"] == "FAL_KEY"


def test_provider_env_map_kling_uses_fal_key():
    assert PROVIDER_ENV_MAP["kling"]["env_key"] == "FAL_KEY"


def test_video_executor_status_promoted():
    assert EXECUTOR_STATUS["video_generation"] == "real-call-when-keyed"


def test_video_in_real_call_stages():
    assert "video_generation" in REAL_CALL_STAGES


def test_pricing_includes_video_generation():
    cfg = _aiorun(pricing_service.get_pricing_config())
    costs = cfg["per_stage_costs"]
    assert costs["video_generation"] >= 0.50
    # Per-model overrides
    overrides = cfg.get("video_generation_per_model") or {}
    assert "fal-ai/kling-video/v2.1/standard/image-to-video" in overrides
    # Master is more expensive than standard.
    assert overrides["fal-ai/kling-video/v2.1/master/image-to-video"] > \
           overrides["fal-ai/kling-video/v2.1/standard/image-to-video"]


# ---------- stage control --------------------------------------------------
def test_stage_control_video_provider_choices():
    choices = PROVIDER_CHOICES_BY_STAGE["video_generation"]
    assert "kling" in choices
    assert "sora" in choices
    assert "luma" in choices


# ---------- provider tests -------------------------------------------------
def test_provider_test_registry_includes_fal():
    assert "fal" in PROVIDER_TESTS


def test_fal_test_returns_meta_when_key_missing():
    # Without FAL_KEY this must NOT raise.
    out = _aiorun(PROVIDER_TESTS["fal"]())
    assert "ok" in out
    assert "provider" in out
    assert out["provider"] == "fal"
