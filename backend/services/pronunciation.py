"""The narrator says each word the way the story means it (owner, 2026-10-26).

The voice model guesses the vowels of plain Arabic, and letters with two readings
come out wrong: a dialect line meaning "who reaches him" was spoken as "who takes
him there" (a shadda the word doesn't have). Before a scene is voiced, one short
call marks only the words that could be read the wrong way, with just the marks
that settle them; everything else stays plain, since full vowels would push the
voice toward formal Arabic. The marked lines go to the voice only: the parent and
the book see the text as written. The answer must keep every letter, otherwise
that line is voiced as written. It never stops a story.
"""
from __future__ import annotations

import json
import logging
import re

from services import engine_health
from services.tashkeel_service import strip_marks

logger = logging.getLogger("pronunciation")

MODEL = "anthropic/claude-sonnet-5.5"
# A line with marks on most of its words was vowelled in full (formal endings): voiced as written.
MAX_MARKED_SHARE = 0.5
_MARKED = re.compile(r"[ً-ْ]")

SYSTEM = """أنت مدقّق نطق لراوٍ صوتي آلي يقرأ قصص أطفال (اللهجة: {dialect}). موديل الصوت يخمّن الحركات من
الحروف، فيخطئ في الكلمات التي لحروفها أكثر من نطق: شدّة ليست في الكلمة (يِنْزِل تُقرأ يِنَزِّل، يِطْلَع تُقرأ
يِطَلَّع)، أو شدّة ناقصة، أو حركة تغيّر المعنى أو الصيغة.
في كل سطر: شكّل فقط الكلمات التي يمكن أن تُقرأ بنطق غير المقصود في سياق الجملة، وضع عليها الحركات التي تحسم
نطقها الصحيح بهذه اللهجة (سكون أو فتحة أو كسرة أو ضمة أو شدّة). باقي الكلمات تبقى بلا أي تشكيل. لا تضع تنويناً ولا
حركات إعراب الفصحى. لا تغيّر أي حرف ولا كلمة ولا ترتيباً ولا علامة ترقيم، ولا تضف ولا تحذف شيئاً.
السطر الذي لا يحتاج شيئاً يعود كما هو.
أعد JSON فقط: {{"lines": ["السطر الأول", "السطر الثاني", ...]}} بنفس عدد الأسطر وترتيبها."""


def _same_letters(original: str, marked: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", strip_marks(s)).strip()  # noqa: E731
    return norm(original) == norm(marked)


def _too_marked(line: str) -> bool:
    words = line.split()
    return bool(words) and sum(1 for w in words if _MARKED.search(w)) > max(2, MAX_MARKED_SHARE * len(words))


def checked(lines: list[str], answer: list) -> list[str]:
    """Each marked line that kept its letters and wasn't vowelled in full, else the line as written."""
    out = []
    for original, marked in zip(lines, answer if isinstance(answer, list) and len(answer) == len(lines) else []):
        if isinstance(marked, str) and _same_letters(original, marked) and not _too_marked(marked):
            out.append(marked.strip())
        else:
            out.append(original)
            if original:
                logger.warning(f"[pronunciation] kept as written: {original[:60]!r}")
    return out or list(lines)


async def spoken(lines: list[str], dialect_name: str) -> list[str]:
    """The lines as the voice should read them."""
    from services.ai import fake_providers
    from services.ai.text_client import generate_text

    if fake_providers.enabled() or not any((l or "").strip() for l in lines):
        return list(lines)
    try:
        answer = await generate_text(
            stage="narration_pronunciation", provider="fal_llm", model=MODEL,
            system=SYSTEM.format(dialect=dialect_name), user=json.dumps({"lines": lines}, ensure_ascii=False),
            json_schema={"type": "object", "properties": {"lines": {"type": "array", "items": {"type": "string"}}},
                         "required": ["lines"]},
            effort="low", max_tokens=2000, timeout=90.0)
        m = re.search(r"\{.*\}", answer or "", re.S)
        result = checked(lines, (json.loads(m.group(0)) if m else {}).get("lines"))
    except Exception as e:  # noqa: BLE001 — the lines as written...
        if engine_health.is_balance_message(e):
            raise  # ...unless the balance ran out: the order pauses for the top-up like the voice would
        logger.warning(f"[pronunciation] skipped: {type(e).__name__}: {str(e)[:160]}")
        return list(lines)
    changed = [(a, b) for a, b in zip(lines, result) if a != b]
    if changed:
        logger.info(f"[pronunciation] marked {len(changed)}/{len(lines)} lines: " + " | ".join(b for _, b in changed)[:300])
    return result
