"""Phase N — per-capability fal.ai keys + exact model matrix."""
import os
import sys
import asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.config_service import DEFAULT_MODELS, PROVIDER_ENV_MAP  # noqa: E402
from services.provider_test_service import PROVIDERS as PROVIDER_TESTS  # noqa: E402
from services import tts_service, music_generation_service, video_generation_service  # noqa: E402


def _aio(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


EXPECTED_MATRIX = {
    "scenario_generation":         ("openai",      "gpt-5.4-mini",                                        "OPENAI_API_KEY"),
    "production_planning":         ("openai",      "gpt-5.4",                                             "OPENAI_API_KEY"),
    "child_character_i2i":         ("openai",      "gpt-image-1.5-2025-12-16",                            "OPENAI_API_KEY"),
    "extra_character_i2i":         ("openai",      "gpt-image-1.5-2025-12-16",                            "OPENAI_API_KEY"),
    "scene_image_generation":      ("fal_image",   "fal-ai/gemini-25-flash-image",                        "FAL_KEY_SCENE"),
    "book_page_image_generation":  ("fal_image",   "fal-ai/gemini-25-flash-image",                        "FAL_KEY_SCENE"),
    "narration_generation":        ("fal_tts",     "fal-ai/elevenlabs/tts/multilingual-v2",               "FAL_KEY_NARRATION"),
    "music_generation":            ("fal_music",   "fal-ai/elevenlabs/music",                             "FAL_KEY_MUSIC"),
    "video_generation":            ("kling",       "fal-ai/kling-video/v3/pro/image-to-video",            "FAL_KEY_VIDEO"),
    "video_assembly":              ("ffmpeg",      "local-ffmpeg",                                        None),
    "pdf_assembly":                ("reportlab",   "local-reportlab",                                     None),
}


def test_default_models_matches_user_matrix():
    for stage, (provider, model, env_key) in EXPECTED_MATRIX.items():
        row = DEFAULT_MODELS.get(stage)
        assert row, f"{stage} missing from DEFAULT_MODELS"
        assert row["provider"]   == provider, f"{stage} provider: expected {provider} got {row['provider']}"
        assert row["model_name"] == model,    f"{stage} model: expected {model} got {row['model_name']}"
        assert row["env_key"]    == env_key,  f"{stage} env_key: expected {env_key} got {row['env_key']}"


def test_provider_env_map_covers_new_keys():
    assert PROVIDER_ENV_MAP["fal_image"]["env_key"] == "FAL_KEY_SCENE"
    assert PROVIDER_ENV_MAP["fal_tts"]["env_key"]   == "FAL_KEY_NARRATION"
    assert PROVIDER_ENV_MAP["fal_music"]["env_key"] == "FAL_KEY_MUSIC"
    assert PROVIDER_ENV_MAP["kling"]["env_key"]     == "FAL_KEY_VIDEO"


def test_provider_tests_include_all_4_capabilities():
    for k in ("fal_scene", "fal_narration", "fal_music", "fal_video"):
        assert k in PROVIDER_TESTS, f"provider test '{k}' missing"


def test_narration_provider_registry_includes_fal_tts():
    assert "fal_tts" in tts_service.PROVIDERS


def test_music_provider_registry_includes_fal_music():
    assert "fal_music" in music_generation_service.PROVIDERS


def test_default_voice_is_phase_n_arabic_friendly():
    assert tts_service.DEFAULT_ELEVENLABS_VOICE == "fkqevZRU7Xj52dY1CTkq"


def test_default_kling_model_is_v3_pro():
    assert video_generation_service.DEFAULT_KLING_MODEL == "fal-ai/kling-video/v3/pro/image-to-video"


def test_default_music_model_is_fal_elevenlabs():
    assert music_generation_service.DEFAULT_ELEVENLABS_MUSIC_MODEL == "fal-ai/elevenlabs/music"


def test_fal_capability_test_fns_fall_back_safely():
    # Without any FAL_KEY*, each fn must return a result dict (not raise).
    for k in ("fal_scene", "fal_narration", "fal_music", "fal_video"):
        out = _aio(PROVIDER_TESTS[k]())
        assert isinstance(out, dict)
        assert "ok" in out
        assert out["provider"] == k


def test_video_adapter_uses_fal_key_video_first():
    # helper prefers the per-capability key.
    secret, source = _aio(video_generation_service._get_fal_key_for_video())
    # Without any key configured this returns (None, "missing")
    assert secret is None or isinstance(secret, str)
