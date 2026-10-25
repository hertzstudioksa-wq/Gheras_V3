"""Full diacritics (tashkeel) on the picture book's text.

Children learning to read need fully vowelled text, and the plan's book text is
always simplified MSA (production_service tells the model so). One call to the
planning model vowels every page of a book (~$0.03 on Opus). A wrong vowel is
worse than none, so the answer is checked: with the diacritics stripped it must
match the original letter for letter, otherwise that page keeps its plain text.
The result is cached on the book page so re-rendering the PDF costs nothing.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("tashkeel")

ENABLED = True
# Arabic diacritics (fathatan..sukun, superscript alef) and tatweel.
_MARKS = re.compile(r"[ً-ْٰـ]")

SYSTEM = """أنت مدقّق لغوي لكتب أطفال عربية. شكّل النصوص تشكيلاً كاملاً صحيحاً (حركات الإعراب والبنية والشدّة
والتنوين) كما في كتب الأطفال المدرسية. لا تغيّر أي حرف ولا كلمة ولا ترتيب ولا علامات الترقيم، ولا تضف ولا تحذف شيئاً:
أضف الحركات فقط. الأسماء الأجنبية (مثل سونيك) شكّلها بما يسهّل نطقها.
أعد JSON فقط بالشكل: {"pages": ["النص الأول مشكولاً", "النص الثاني مشكولاً", ...]} بنفس عدد النصوص وترتيبها."""


def strip_marks(text: str) -> str:
    return _MARKS.sub("", text or "")


def _same_letters(original: str, vowelled: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", strip_marks(s)).strip()  # noqa: E731
    return norm(original) == norm(vowelled)


async def diacritize(texts: list[str]) -> list[str | None]:
    """Vowelled text per page, or None for a page that failed the check."""
    from services.ai.text_client import generate_text
    from services.config_service import resolve_model

    todo = [t for t in texts if t and t.strip()]
    if not ENABLED or not todo:
        return [None] * len(texts)
    provider, model, _src = await resolve_model("production_planning", "", "")
    user = json.dumps({"pages": texts}, ensure_ascii=False)
    answer = await generate_text(stage="book_tashkeel", provider=provider, model=model, system=SYSTEM, user=user,
                                 json_schema={"type": "object", "properties": {"pages": {"type": "array", "items": {"type": "string"}}},
                                              "required": ["pages"]},
                                 effort="low", max_tokens=6000, timeout=120.0)
    m = re.search(r"\{.*\}", answer, re.S)
    pages = json.loads(m.group(0)).get("pages") if m else None
    if not isinstance(pages, list) or len(pages) != len(texts):
        logger.warning("[tashkeel] answer had the wrong shape; book stays plain")
        return [None] * len(texts)
    out = []
    for original, vowelled in zip(texts, pages):
        if isinstance(vowelled, str) and original and _same_letters(original, vowelled):
            out.append(vowelled.strip())
        else:
            out.append(None)
            if original:
                logger.warning("[tashkeel] a page changed letters; kept plain")
    return out


async def vowelled_pages(book_assets: list[dict]) -> dict[str, str]:
    """book_asset id → vowelled text, from cache or one model call. Raises only on
    an exhausted balance (a book went out plain once when fal's credit ran out)."""
    from db import db

    result: dict[str, str] = {}
    missing = []
    for ba in book_assets:
        text = (ba.get("page_text") or "").strip()
        cached = ba.get("page_text_tashkeel")
        if cached and _same_letters(text, cached):
            result[ba["id"]] = cached
        elif text:
            missing.append(ba)
    if not missing or not ENABLED:
        return result
    try:
        vowelled = await diacritize([(ba.get("page_text") or "").strip() for ba in missing])
    except Exception as e:  # noqa: BLE001 — the book is still fine without vowels...
        from services.engine_health import is_balance_message

        if is_balance_message(e):
            raise  # ...but not because the balance ran out: the order pauses for the top-up
        logger.warning(f"[tashkeel] skipped: {type(e).__name__}: {e}")
        return result
    for ba, text in zip(missing, vowelled):
        if text:
            result[ba["id"]] = text
            await db.book_assets.update_one({"id": ba["id"]}, {"$set": {"page_text_tashkeel": text}})
    return result
