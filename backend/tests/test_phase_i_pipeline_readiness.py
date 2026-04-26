"""Phase I — Pipeline-readiness consistency tests."""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.config_service import DEFAULT_PIPELINE  # noqa: E402
from services.stage_lab_service import SUPPORTED_STAGES, EXECUTOR_STATUS  # noqa: E402
from services.pipeline_readiness_service import _flags  # noqa: E402


def test_default_pipeline_covers_all_supported_stages():
    pipeline_keys = set(DEFAULT_PIPELINE["stages"].keys())
    supported = set(SUPPORTED_STAGES)
    missing = supported - pipeline_keys
    extra = pipeline_keys - supported
    assert not missing, f"missing in DEFAULT_PIPELINE: {missing}"
    assert not extra, f"unknown in DEFAULT_PIPELINE: {extra}"


def test_default_pipeline_order_matches_stage_set():
    order = DEFAULT_PIPELINE["order"]
    assert set(order) == set(DEFAULT_PIPELINE["stages"].keys())
    assert len(order) == len(set(order)), "order has duplicates"


def test_no_legacy_final_assembly():
    assert "final_assembly" not in DEFAULT_PIPELINE["stages"]
    assert "final_assembly" not in DEFAULT_PIPELINE["order"]


def test_video_assembly_and_pdf_assembly_present():
    for s in ("video_assembly", "pdf_assembly", "book_page_image_generation",
              "music_generation", "video_generation"):
        assert s in DEFAULT_PIPELINE["stages"], f"{s} missing"


def test_local_binary_stages_have_local_binary_flag():
    for s in ("video_assembly", "pdf_assembly"):
        assert DEFAULT_PIPELINE["stages"][s].get("local_binary") is True
        assert EXECUTOR_STATUS[s] == "local-binary"


def test_audio_aware_stages_flagged():
    for s in ("narration_generation", "music_generation"):
        assert DEFAULT_PIPELINE["stages"][s].get("audio_aware") is True


def test_reference_aware_flag_on_scene_image():
    assert DEFAULT_PIPELINE["stages"]["scene_image_generation"].get("reference_aware") is True


def test_output_type_gating_on_pdf_chain():
    pdf_chain = ("book_page_image_generation", "pdf_assembly")
    for s in pdf_chain:
        gates = DEFAULT_PIPELINE["stages"][s].get("gated_by_output_type") or []
        assert "pdf" in gates and "both" in gates


def test_output_type_gating_on_video_chain():
    video_chain = ("narration_generation", "music_generation",
                   "video_generation", "video_assembly")
    for s in video_chain:
        gates = DEFAULT_PIPELINE["stages"][s].get("gated_by_output_type") or []
        assert "video" in gates and "both" in gates, f"{s} missing video gating"


def test_flags_helper_identifies_local_binary_and_audio():
    f = _flags("narration_generation",
                DEFAULT_PIPELINE["stages"]["narration_generation"])
    assert "audio_aware" in f
    assert any(x.startswith("gated:") for x in f)

    f2 = _flags("video_assembly",
                 DEFAULT_PIPELINE["stages"]["video_assembly"])
    assert "local_binary" in f2


def test_flags_helper_for_book_page_reuse():
    f = _flags("book_page_image_generation",
                DEFAULT_PIPELINE["stages"]["book_page_image_generation"])
    assert "reuse_from_scene_image" in f
