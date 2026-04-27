"""Phase G — closing /admin/lab control gaps.

Tests:
  * 4 new stages (extra_character_i2i, book_page_image_generation,
    video_assembly, pdf_assembly) now in SUPPORTED_STAGES
  * EXECUTOR_STATUS classifies all 11 stages
  * STAGE_NOTES_AR has Arabic notes for all 11 stages
  * extra_character_i2i is real-call (it actually fires the OpenAI exec)
  * video_assembly / pdf_assembly are local-binary (no LLM)
  * book_page_image_generation is reuse-from-other-stage today
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.stage_lab_service import (  # noqa: E402
    SUPPORTED_STAGES, REAL_CALL_STAGES, EXECUTOR_STATUS, STAGE_NOTES_AR,
)


# ---------------------------------------------------------------------------
def test_phase_g_new_stages_added():
    for s in ("extra_character_i2i", "book_page_image_generation",
              "video_assembly", "pdf_assembly"):
        assert s in SUPPORTED_STAGES, f"{s} missing from SUPPORTED_STAGES"


def test_phase_g_total_supported_stages_is_eleven():
    assert len(SUPPORTED_STAGES) == 11


def test_executor_status_covers_all_stages():
    missing = [s for s in SUPPORTED_STAGES if s not in EXECUTOR_STATUS]
    assert missing == [], f"missing executor_status: {missing}"


def test_executor_status_values_are_known():
    allowed = {"real-call", "real-call-when-keyed", "preview-only", "not-yet-wired",
               "local-binary", "reuse-from-other-stage"}
    bad = [(s, EXECUTOR_STATUS[s]) for s in SUPPORTED_STAGES
           if EXECUTOR_STATUS[s] not in allowed]
    assert bad == [], f"unknown executor_status: {bad}"


def test_extra_character_i2i_is_real_call():
    assert "extra_character_i2i" in REAL_CALL_STAGES
    assert EXECUTOR_STATUS["extra_character_i2i"] == "real-call"


def test_video_and_pdf_assembly_are_local_binary():
    assert EXECUTOR_STATUS["video_assembly"] == "local-binary"
    assert EXECUTOR_STATUS["pdf_assembly"] == "local-binary"
    # Local binaries are NEVER real-call.
    assert "video_assembly" not in REAL_CALL_STAGES
    assert "pdf_assembly" not in REAL_CALL_STAGES


def test_book_page_image_generation_is_reuse():
    assert EXECUTOR_STATUS["book_page_image_generation"] == "reuse-from-other-stage"


def test_not_yet_wired_stages():
    # Phase K: narration moved out. Phase L: video_generation moved out
    # (fal.ai Kling executor wired). Music remains the only not-yet-wired stage.
    expected = {"music_generation"}
    actual = {s for s, st in EXECUTOR_STATUS.items() if st == "not-yet-wired"}
    assert actual == expected, f"not-yet-wired mismatch: {actual} vs {expected}"


def test_real_call_when_keyed_stages():
    # Phase L expanded this bucket to include video_generation alongside narration.
    expected = {"narration_generation", "video_generation"}
    actual = {s for s, st in EXECUTOR_STATUS.items() if st == "real-call-when-keyed"}
    assert actual == expected, f"real-call-when-keyed mismatch: {actual} vs {expected}"


def test_arabic_notes_present_for_all_stages():
    missing = [s for s in SUPPORTED_STAGES if not STAGE_NOTES_AR.get(s)]
    assert missing == [], f"missing notes_ar: {missing}"
