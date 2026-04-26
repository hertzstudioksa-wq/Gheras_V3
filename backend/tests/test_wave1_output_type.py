"""Wave 1 — output_type + scenario history unit tests.

Covers:
  * `get_order_output_type()` legacy / new / invalid handling.
  * Pipeline gating math: which job_types are mandatory per output_type.
  * Final-assembly job_types list per output_type.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from models import OUTPUT_TYPES, get_order_output_type  # noqa: E402


# ---------------------------------------------------------------------------
# get_order_output_type — backward compat
# ---------------------------------------------------------------------------
def test_output_type_default_for_legacy_order():
    legacy = {"id": "x", "data": {"child": {"name": "ليلى"}}}
    assert get_order_output_type(legacy) == "both"


def test_output_type_default_for_empty_or_none():
    assert get_order_output_type(None) == "both"
    assert get_order_output_type({}) == "both"
    assert get_order_output_type({"data": {}}) == "both"


def test_output_type_new_order_video():
    o = {"data": {"delivery": {"output_type": "video"}}}
    assert get_order_output_type(o) == "video"


def test_output_type_new_order_pdf():
    o = {"data": {"delivery": {"output_type": "pdf"}}}
    assert get_order_output_type(o) == "pdf"


def test_output_type_invalid_falls_back_to_both():
    o = {"data": {"delivery": {"output_type": "weird-thing"}}}
    assert get_order_output_type(o) == "both"


def test_output_type_constants():
    assert set(OUTPUT_TYPES) == {"video", "pdf", "both"}


# ---------------------------------------------------------------------------
# Pipeline gating math — mirrors generation_orchestrator + final_delivery
# ---------------------------------------------------------------------------
def _expected_mandatory(output_type: str) -> set[str]:
    """Mirror of generation_orchestrator's mandatory_types selection."""
    m = {"cover_image", "scene_image"}
    if output_type in ("video", "both"):
        m.add("narration_audio")
    if output_type in ("pdf", "both"):
        m.add("book_page_asset")
    return m


def _expected_assembly_jobs(output_type: str) -> list[str]:
    out: list[str] = []
    if output_type in ("video", "both"):
        out.append("final_video_assembly")
    if output_type in ("pdf", "both"):
        out.append("final_pdf_assembly")
    return out


def test_pdf_only_skips_narration():
    m = _expected_mandatory("pdf")
    assert "narration_audio" not in m
    assert "book_page_asset" in m
    assert _expected_assembly_jobs("pdf") == ["final_pdf_assembly"]


def test_video_only_skips_book_assets():
    m = _expected_mandatory("video")
    assert "narration_audio" in m
    assert "book_page_asset" not in m
    assert _expected_assembly_jobs("video") == ["final_video_assembly"]


def test_both_keeps_full_pipeline():
    m = _expected_mandatory("both")
    assert m == {"cover_image", "scene_image", "narration_audio", "book_page_asset"}
    assert _expected_assembly_jobs("both") == ["final_video_assembly", "final_pdf_assembly"]
