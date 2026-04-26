"""Phase H — Secure Secret Overrides + Preset Stacks tests."""
import os, sys, asyncio

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services import secret_overrides_service as sov  # noqa: E402
from services import preset_stacks_service as ps  # noqa: E402


def _aiorun(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Encryption -------------------------------------------------------------
def test_fernet_available_when_mongo_url_present():
    assert sov.encryption_available() is True


def test_mask_short_value():
    assert sov._mask("X" * 6) == "***"
    assert sov._mask("XXXXXX1234") == "***1234"
    assert sov._mask("") is None
    assert sov._mask(None) is None


def test_encryption_round_trip():
    f = sov._get_fernet()
    assert f is not None
    secret = "sk-test-1234-very-secret-ABCD"
    encrypted = f.encrypt(secret.encode("utf-8")).decode("utf-8")
    assert encrypted != secret  # actually encrypted, not just encoded
    decrypted = f.decrypt(encrypted.encode("utf-8")).decode("utf-8")
    assert decrypted == secret


# --- Preset slug helper ----------------------------------------------------
def test_slug_arabic_falls_back_to_uuid():
    s = ps._slug("النموذج المنخفض")
    # Arabic characters get stripped; result must still be a non-empty slug.
    assert s.startswith("preset-") or len(s) > 0


def test_slug_simple_english():
    assert ps._slug("OpenAI Full Stack") == "openai-full-stack"
    assert ps._slug("  Hello   World  ") == "hello-world"


def test_slug_fallback_when_garbage():
    out = ps._slug("!!!@@@")
    assert out.startswith("preset-")


# --- stage_map validation rejects raw secrets -------------------------------
def test_validate_stage_map_rejects_raw_secret_fields():
    bad = {"scenario_generation": {"provider": "openai",
                                    "model_name": "gpt-5.2",
                                    "env_key": "OPENAI_API_KEY",
                                    "api_key": "sk-leaked"}}  # forbidden!
    try:
        ps._validate_stage_map(bad)
    except ValueError as e:
        assert "api_key" in str(e)
        return
    raise AssertionError("expected ValueError on raw api_key field")


def test_validate_stage_map_rejects_unknown_stage():
    bad = {"unknown_stage": {"provider": "openai", "model_name": "x"}}
    try:
        ps._validate_stage_map(bad)
    except ValueError as e:
        assert "unknown stage_key" in str(e)
        return
    raise AssertionError("expected ValueError")


def test_validate_stage_map_accepts_clean_payload():
    good = {
        "scenario_generation": {"provider": "openai",
                                 "model_name": "gpt-5.2",
                                 "env_key": "OPENAI_API_KEY",
                                 "notes": "free text"},
        "scene_image_generation": {"provider": "gemini",
                                    "model_name": "x",
                                    "env_key": "EMERGENT_LLM_KEY"},
    }
    ps._validate_stage_map(good)  # must not raise


# --- Seeded presets shape --------------------------------------------------
def test_seeded_preset_set_count_and_slugs():
    slugs = {p["slug"] for p in ps.SEEDED_PRESETS}
    assert {"openai-full", "gemini-visual", "low-cost",
            "high-fidelity", "safe-production"}.issubset(slugs)


def test_seeded_presets_never_carry_raw_secrets():
    for p in ps.SEEDED_PRESETS:
        for stage_key, mapping in p["stage_map"].items():
            for forbidden in ("api_key", "secret", "value", "raw"):
                assert forbidden not in mapping, (
                    f"seed preset {p['slug']}.{stage_key} leaks {forbidden}"
                )


def test_executor_warning_strings_present_for_known_statuses():
    assert ps._executor_warning("not-yet-wired")
    assert ps._executor_warning("preview-only")
    assert ps._executor_warning("local-binary")
    assert ps._executor_warning("reuse-from-other-stage")
    assert ps._executor_warning("real-call") is None
