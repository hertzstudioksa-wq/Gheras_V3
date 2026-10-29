"""The narrator gets the lines with only the misreadable words marked; the parent sees them plain."""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "gheras_comfy_unit")

from services import house_style, pronunciation  # noqa: E402
from services.ai import text_client  # noqa: E402

LINES = ["البنت نزلت من العربية وطلعت السلم.", "ماما قالت: «يلا بينا!»"]
MARKED = ["البنت نِزْلِت من العربية وطِلْعِت السلم.", "ماما قالت: «يلا بينا!»"]
LOCKED = "fal call failed (upload): HTTP 403: User is locked. Reason: Exhausted balance. Top up your balance"


def test_a_marked_line_is_kept_only_with_the_same_letters_and_few_marks():
    assert pronunciation.checked(LINES, MARKED) == MARKED
    # a changed letter, a fully vowelled (formal) line, or the wrong count: the line as written
    assert pronunciation.checked(LINES, ["البنت نزلوا من العربية وطلعت السلم.", LINES[1]]) == LINES
    full = "البِنْتُ نَزَلَتْ مِنَ العَرَبِيَّةِ وَطَلَعَتِ السُّلَّمَ."
    assert pronunciation.checked(LINES, [full, LINES[1]])[0] == LINES[0]
    assert pronunciation.checked(LINES, [MARKED[0]]) == LINES


def test_the_voice_gets_the_marked_lines(monkeypatch):
    monkeypatch.delenv("GHERAS_FAKE_PROVIDERS", raising=False)
    seen = {}

    async def answer(**k):
        seen.update(k)
        return '{"lines": %s}' % str(MARKED).replace("'", '"')

    monkeypatch.setattr(text_client, "generate_text", answer)
    assert asyncio.run(pronunciation.spoken(LINES, "مصري")) == MARKED
    assert "(اللهجة: مصري)" in seen["system"] and seen["model"] == pronunciation.MODEL


def test_a_failed_check_never_stops_the_voice_but_an_empty_balance_pauses(monkeypatch):
    monkeypatch.delenv("GHERAS_FAKE_PROVIDERS", raising=False)

    async def broken(**k):
        raise RuntimeError("timeout")

    async def locked(**k):
        raise RuntimeError(LOCKED)

    monkeypatch.setattr(text_client, "generate_text", broken)
    assert asyncio.run(pronunciation.spoken(LINES, "مصري")) == LINES
    monkeypatch.setattr(text_client, "generate_text", locked)
    try:
        asyncio.run(pronunciation.spoken(LINES, "مصري"))
        raise AssertionError("an empty balance must pause the order")
    except RuntimeError as e:
        assert "Exhausted balance" in str(e)


def test_off_in_the_rehearsal_and_the_planner_marks_a_missing_shadda_too(monkeypatch):
    monkeypatch.setenv("GHERAS_FAKE_PROVIDERS", "1")
    assert asyncio.run(pronunciation.spoken(LINES, "مصري")) == LINES
    assert "والسكون على كلمة قد تُقرأ بشدّة ليست فيها" in house_style.DIALECTS["egyptian"]["writing"]


def test_a_line_with_more_than_two_marked_words_is_voiced_as_written():
    # a line came back with three marked words, two with one natural reading and an MSA vowel
    line = "ميكي الكبير قاعد في آخر الممر ومستني مين يوصله!"
    three = "ميكي الكبير قاعد في آخر الْمَمَرّ ومُسْتَنِّي مين يِوصَلُه!"
    assert pronunciation.checked([line], [three]) == [line]
    two = "ميكي الكبير قاعد في آخر الممر ومِسْتَنّي مين يِوْصَله!"
    assert pronunciation.checked([line], [two]) == [two]


def test_the_scene_mood_goes_to_the_voice_through_fal():
    from services import shot_pipeline as sp

    base = "Read aloud in a warm storyteller voice:"
    assert sp.scene_direction(base, None) == base
    out = sp.scene_direction(base, "Bright and playful, slightly quick. A lively lift on the shout.")
    assert out == "Read aloud in a warm storyteller voice. In this scene: Bright and playful, slightly quick. " \
                  "A lively lift on the shout."
    long = "Calm. " * 80
    assert len(sp.scene_direction(base, long)) < len(base) + sp.SCENE_DIRECTION_CHARS + 20
