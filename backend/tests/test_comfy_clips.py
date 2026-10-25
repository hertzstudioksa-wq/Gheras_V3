"""Comfy clips (phase C): Wan 2.2 clip length and motion prompt."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from services import engine_config, house_style  # noqa: E402
from services import shot_pipeline as sp  # noqa: E402
from services.model_catalog import EXECUTORS, fits_stage  # noqa: E402

WAN = "comfy/clip_wan22"


@pytest.mark.parametrize("narration,expected", [
    (0.0, 3), (2.0, 3), (2.6, 4), (4.5, 5), (4.6, 6), (6.4, 7), (6.6, 7), (12.0, 7),
])
def test_wan_length_is_the_line_in_whole_seconds(narration, expected):
    # need = line + gap (0.35) + 0.15, rounded up, kept within 3..7
    got = house_style.clip_seconds_for(WAN, narration, 0.35)
    assert got == expected and type(got) is int


def test_last_shot_tail_is_part_of_the_length():
    assert house_style.clip_seconds_for(WAN, 3.0 + 1.0, 0.35) == 5  # line + tail


def test_kling_lengths_unchanged():
    assert house_style.clip_seconds_for("fal-ai/kling-video/v3/pro/image-to-video", 4.6, 0.35) == 6
    assert house_style.clip_seconds_for("fal-ai/kling-video/v2.5-turbo/pro/image-to-video", 4.6, 0.35) == 5
    assert house_style.clip_seconds_for("fal-ai/kling-video/v2.5-turbo/pro/image-to-video", 6.0, 0.35) == 10


def test_wan_motion_prompt_keeps_the_guards_without_elements():
    style = engine_config.DEFAULT_STYLE
    text = sp.motion_prompt("Lina waters the flowers.", [], style, ["Lina", "Omar (the child's father)"])
    assert "@Element" not in text and "Characters:" not in text
    assert "Exactly 2 people in this shot" in text and sp.OUTFIT_LOCK in text
    assert sp.PHYSICS in text and text.endswith(sp.NO_TEXT)


def test_wan_is_a_video_executor_for_the_video_stage_only():
    assert "comfy_video" in EXECUTORS["video"]
    assert fits_stage("comfy_video", "video_generation") and not fits_stage("comfy_video", "scene_image_generation")
