"""Wave 2 — pricing + stage-lab + secrets unit tests.

Pure pricing math is unit-tested locally (no DB roundtrip needed for the
core logic). DB-touching paths are smoke-tested via the live API.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.pricing_service import (  # noqa: E402
    DEFAULT_PRICING_CONFIG, _apply_markup, _round_to,
)
from services.stage_lab_service import (  # noqa: E402
    SUPPORTED_STAGES, REAL_CALL_STAGES, _hash, _sanitize_input,
)


# ---------------------------------------------------------------------------
# Pricing — markup / rounding / minimum
# ---------------------------------------------------------------------------
def test_apply_markup_uses_minimum_when_internal_low():
    cfg = {"markup_percent": 35.0, "minimum_price": 49.0, "rounding": 1.0}
    sell, margin = _apply_markup(internal_cost=5.0, cfg=cfg)
    assert sell == 49.0
    assert margin == 44.0


def test_apply_markup_above_minimum():
    cfg = {"markup_percent": 50.0, "minimum_price": 10.0, "rounding": 1.0}
    sell, margin = _apply_markup(internal_cost=100.0, cfg=cfg)
    assert sell == 150.0
    assert margin == 50.0


def test_round_to_step():
    assert _round_to(149.4, 1.0) == 149.0
    assert _round_to(149.6, 1.0) == 150.0
    assert _round_to(149.51, 0.5) == 149.5
    assert _round_to(0.0, 0) == 0.0  # zero step → fallback round(.., 2)


def test_default_config_keys():
    expected_top_keys = {
        "currency", "markup_percent", "minimum_price",
        "per_stage_costs", "per_output_modifier", "per_cost_tier_modifier",
        "retry_attempt_cost_fraction",
    }
    assert expected_top_keys.issubset(set(DEFAULT_PRICING_CONFIG.keys()))
    assert DEFAULT_PRICING_CONFIG["currency"] == "SAR"
    # Per-stage covers every stage the cost calculator looks at.
    expected_stage_keys = {
        "scenario_generation", "production_planning",
        "child_character_i2i", "extra_character_i2i",
        "scene_image_generation", "cover_image",
        "narration_audio", "book_page_asset", "vision_describe",
        "video_assembly", "pdf_assembly",
    }
    assert expected_stage_keys.issubset(set(DEFAULT_PRICING_CONFIG["per_stage_costs"].keys()))
    # Output modifiers cover every output_type.
    assert set(DEFAULT_PRICING_CONFIG["per_output_modifier"].keys()) >= {"video", "pdf", "both"}


def test_pdf_only_is_cheaper_than_both():
    om = DEFAULT_PRICING_CONFIG["per_output_modifier"]
    assert om["pdf"] < om["both"]


# ---------------------------------------------------------------------------
# Stage Lab — supported stages + helpers
# ---------------------------------------------------------------------------
def test_stage_lab_supported_stages():
    expected = {
        "scenario_generation", "production_planning",
        "child_character_i2i", "scene_image_generation",
        "narration_generation", "video_generation", "music_generation",
    }
    assert set(SUPPORTED_STAGES) == expected


def test_real_call_stages_subset():
    assert REAL_CALL_STAGES.issubset(set(SUPPORTED_STAGES))
    # Preview-only stages are explicitly NOT in REAL_CALL_STAGES.
    for k in ("narration_generation", "video_generation", "music_generation", "scene_image_generation"):
        assert k not in REAL_CALL_STAGES


def test_hash_format():
    h = _hash("hello world")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 16


def test_sanitize_input_truncates_long_strings():
    long_text = "x" * 5000
    out = _sanitize_input({"foo": long_text, "n": 7, "lst": list(range(20)), "obj": {"k": "y" * 5000}})
    assert len(out["foo"]) == 500
    assert out["n"] == 7
    assert len(out["lst"]) == 10
    assert len(out["obj"]["k"]) == 200


# ---------------------------------------------------------------------------
# Secrets — provider→env mapping
# ---------------------------------------------------------------------------
def test_known_env_keys_curated():
    from routes.admin_secrets_routes import KNOWN_ENV_KEYS  # noqa: PLC0415
    keys = {k["key"] for k in KNOWN_ENV_KEYS}
    assert "OPENAI_API_KEY" in keys
    assert "EMERGENT_LLM_KEY" in keys
    # Each item has the required fields.
    for spec in KNOWN_ENV_KEYS:
        assert "label" in spec and spec["label"]
        assert "rotation_instructions" in spec and len(spec["rotation_instructions"]) > 20


def test_secrets_mask_helper():
    from routes.admin_secrets_routes import _mask
    assert _mask(None) is None
    assert _mask("") is None
    assert _mask("short") == "***"
    assert _mask("sk-abcdef1234").endswith("1234")
    assert _mask("sk-abcdef1234").startswith("***")
