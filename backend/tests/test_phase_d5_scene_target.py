"""Phase D.5 — duration → scene_target bucket tests (unit, no HTTP needed).

Verifies:
  * duration_meta() returns the correct bucket range for every snap point.
  * Old orders (duration dict without the bucket fields) are unaffected
    — duration_scene_range returns None for them.
  * scenario_service._clamp_scene_count honours the bucket range when passed.
  * production_service._generate_via_claude validation would accept any
    count inside the range and reject outside (tested via helper only).
  * _enforce_final_scene_quality pads a short last-scene narration/book
    without touching earlier scenes.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from models import duration_meta, duration_scene_range  # noqa: E402
from services.scenario_service import _clamp_scene_count  # noqa: E402
from services.production_service import _enforce_final_scene_quality  # noqa: E402


# ---------------------------------------------------------------------------
# duration_meta — bucket mapping
# ---------------------------------------------------------------------------
def test_duration_meta_short_bucket():
    for sec, picked in [(30, 3), (45, 4)]:
        m = duration_meta(sec)
        assert m["scene_target"] == picked
        assert m["scene_target_min"] == 3
        assert m["scene_target_max"] == 4
        assert m["scene_target_bucket"] == "short"
        assert m["cost_tier"] == "low"


def test_duration_meta_medium_bucket():
    for sec, picked in [(60, 5), (90, 6)]:
        m = duration_meta(sec)
        assert m["scene_target"] == picked
        assert m["scene_target_min"] == 5
        assert m["scene_target_max"] == 6
        assert m["scene_target_bucket"] == "medium"
        assert m["cost_tier"] == "medium"


def test_duration_meta_long_bucket():
    for sec, picked in [(120, 7), (150, 8), (180, 9)]:
        m = duration_meta(sec)
        assert m["scene_target"] == picked
        assert m["scene_target_min"] == 7
        assert m["scene_target_max"] == 9
        assert m["scene_target_bucket"] == "long"
        assert m["cost_tier"] == "high"


def test_duration_meta_snaps_nearest():
    # 100 → nearest snap is 90
    assert duration_meta(100)["seconds"] == 90
    # 140 → nearest snap is 150
    assert duration_meta(140)["seconds"] == 150


# ---------------------------------------------------------------------------
# duration_scene_range — backward compatibility
# ---------------------------------------------------------------------------
def test_duration_range_none_for_legacy_order():
    legacy = {"seconds": 90, "label": "دقيقة ونصف", "scene_target": 6, "cost_tier": "medium"}
    assert duration_scene_range(legacy) is None


def test_duration_range_for_new_order():
    m = duration_meta(90)
    assert duration_scene_range(m) == (5, 6)


def test_duration_range_none_when_missing():
    assert duration_scene_range(None) is None
    assert duration_scene_range({}) is None


# ---------------------------------------------------------------------------
# _clamp_scene_count — bucket-aware clamping
# ---------------------------------------------------------------------------
def test_clamp_within_bucket_accepts_in_range():
    assert _clamp_scene_count(5, 6, (5, 6)) == 5
    assert _clamp_scene_count(6, 6, (5, 6)) == 6


def test_clamp_within_bucket_clips_too_low():
    assert _clamp_scene_count(2, 6, (5, 6)) == 5


def test_clamp_within_bucket_clips_too_high():
    assert _clamp_scene_count(99, 6, (5, 6)) == 6


def test_clamp_legacy_behaviour_unchanged():
    # No range → legacy target ±1 bounded to [3, 10]
    assert _clamp_scene_count(6, 6) == 6
    assert _clamp_scene_count(2, 6) == 5
    assert _clamp_scene_count(20, 6) == 7


# ---------------------------------------------------------------------------
# Final-scene quality guard
# ---------------------------------------------------------------------------
def _mini_scene(idx, narr, book):
    return {
        "scene_index": idx,
        "narration_text": narr,
        "book_text": book,
        "word_count": len([w for w in narr.split() if w]),
    }


def test_final_scene_guard_pads_short_narration():
    scenes = [
        _mini_scene(1, "هذه بداية جميلة لقصة يوسف يكتشف فيها عالماً رائعاً حوله.", "بدأت القصة."),
        _mini_scene(2, "انتهت.", "النهاية."),
    ]
    _enforce_final_scene_quality(scenes, child_name="يوسف")
    last = scenes[-1]
    assert len(last["narration_text"].split()) >= 12
    assert "يوسف" in last["narration_text"]
    # First scene is untouched
    assert scenes[0]["narration_text"].startswith("هذه بداية جميلة")


def test_final_scene_guard_pads_short_book_text():
    scenes = [
        _mini_scene(1, "افتتاحية دافئة متدفقة تلامس القلب.", "سطر مقدمة."),
        _mini_scene(2, "خاتمة متدفقة طويلة بما يكفي لاعتبارها سرداً جيداً بالفعل هنا.",
                    "قصير."),
    ]
    _enforce_final_scene_quality(scenes, child_name="ليلى")
    assert len(scenes[-1]["book_text"].split()) >= 8


def test_final_scene_guard_noop_when_already_good():
    long_narr = ("وفي النهاية ابتسمت ليلى وهي تشعر بالفخر والسعادة "
                 "بعد أن تعلمت درساً جميلاً سيبقى معها دائماً.")
    long_book = "ابتسمت ليلى بفرح وعرفت أن اللطف يفتح كل القلوب."
    scenes = [
        _mini_scene(1, "بداية طبيعية.", "بداية."),
        _mini_scene(2, long_narr, long_book),
    ]
    _enforce_final_scene_quality(scenes, child_name="ليلى")
    assert scenes[-1]["narration_text"] == long_narr
    assert scenes[-1]["book_text"] == long_book
