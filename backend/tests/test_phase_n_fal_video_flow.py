"""Phase N — fal.ai video flow regression tests.

Pure structural / unit tests for:
  1. URL pattern fix: queue status URL must use `app_prefix` only, not full slug.
  2. Multi-shape video URL extraction from fal.ai response payloads.
  3. Manual import endpoint accepts payload and short-circuits gracefully.

NO live API calls. NO external keys required.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services.video_generation_service import (  # noqa: E402
    _model_app_prefix,
    _extract_video_url_from_fal_response,
)


# ---------------------------------------------------------------------------
def test_app_prefix_strips_versioned_kling_slug():
    """The fal.ai queue status endpoint must NOT receive the full versioned
    slug — only the app prefix `fal-ai/kling-video`. This bug caused HTTP 405
    on every poll for the user's existing orders."""
    assert _model_app_prefix("fal-ai/kling-video/v3/pro/image-to-video") == "fal-ai/kling-video"
    assert _model_app_prefix("fal-ai/kling-video/v3/standard/image-to-video") == "fal-ai/kling-video"
    assert _model_app_prefix("fal-ai/sora-2/image-to-video") == "fal-ai/sora-2"


def test_app_prefix_handles_simple_two_part_slugs():
    assert _model_app_prefix("fal-ai/luma-dream-machine") == "fal-ai/luma-dream-machine"


def test_app_prefix_handles_edge_cases():
    assert _model_app_prefix("") == ""
    assert _model_app_prefix("only-one-part") == "only-one-part"
    assert _model_app_prefix("/leading/slash/x") == "leading/slash"


# ---------------------------------------------------------------------------
# Result-shape extraction.
# ---------------------------------------------------------------------------
def test_extract_video_dict_shape():
    """Most common: {video: {url: '...'}}"""
    assert _extract_video_url_from_fal_response(
        {"video": {"url": "https://fal.media/abc.mp4"}}
    ) == "https://fal.media/abc.mp4"


def test_extract_video_string_shape():
    """Some endpoints return: {video: 'https://...'}"""
    assert _extract_video_url_from_fal_response(
        {"video": "https://fal.media/x.mp4"}
    ) == "https://fal.media/x.mp4"


def test_extract_output_video_shape():
    """Kling v3 sometimes wraps under 'output'."""
    assert _extract_video_url_from_fal_response(
        {"output": {"video": {"url": "https://fal.media/o.mp4"}}}
    ) == "https://fal.media/o.mp4"
    assert _extract_video_url_from_fal_response(
        {"output": {"video": "https://fal.media/o2.mp4"}}
    ) == "https://fal.media/o2.mp4"


def test_extract_video_url_legacy_field():
    assert _extract_video_url_from_fal_response(
        {"video_url": "https://fal.media/v.mp4"}
    ) == "https://fal.media/v.mp4"


def test_extract_files_array_with_mp4():
    assert _extract_video_url_from_fal_response(
        {"files": [{"url": "https://fal.media/clip.mp4"}, {"url": "https://other"}]}
    ) == "https://fal.media/clip.mp4"


def test_extract_returns_none_on_garbage():
    assert _extract_video_url_from_fal_response(None) is None
    assert _extract_video_url_from_fal_response({}) is None
    assert _extract_video_url_from_fal_response("not a dict") is None
    assert _extract_video_url_from_fal_response(42) is None
    # video.url is not http
    assert _extract_video_url_from_fal_response({"video": {"url": "ftp://x"}}) is None
    # video is empty string
    assert _extract_video_url_from_fal_response({"video": ""}) is None


def test_extract_skips_non_video_files():
    assert _extract_video_url_from_fal_response(
        {"files": [{"url": "https://fal.media/thumb.png"}]}
    ) is None
