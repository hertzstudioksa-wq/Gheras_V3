"""Real body proportions on a drawn character sheet.

GPT Image keeps the photo's face size: a father drawn from a selfie came out five heads
tall, and the scenes copied his big head (owner: "the head is big and looks silly").
Numbers in the GPT prompt, a reworded intro and the style picture's proportions all left
him at five heads; stretching the body below the neck gave a long thin body (owner: no).
A Qwen edit of the drawn sheet, the same person with a smaller head, is the one the owner
approved: the face, clothes and build stay as drawn. A failed edit keeps the GPT sheet.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("sheet_proportions")

MODEL = "comfy/sheet_qwen21"   # the keyframe workflow at the sheet's portrait 1024x1536
ADULT = "a grown-up about seven and a half heads tall"
CHILD = ((2, "four"), (4, "four and a half"), (6, "five"), (9, "five and a half"), (12, "six"), (15, "six and a half"))
# "the same face, hair, beard" gave the four-year-old a beard: facial hair is said per person.
PROMPT = ("Redraw <image1> as the same full-body character sheet with real body proportions for their age: exactly "
          "the same person with the same face, hair, skin, clothes, shoes, colors, pose and art style ({face}), but "
          "the head drawn smaller against the body, so that they are {build}, with a longer torso and longer legs. "
          "One figure, head to toe, centered on a plain white background. No text.")
ADULT_FACE = "facial hair exactly as on <image1>, none where it has none"
CHILD_FACE = "a child's smooth face with no beard or moustache"


def build(age, adult: bool) -> str:
    """How tall in heads, in words: a grown-up, or a child of that age (five heads when unknown)."""
    if adult:
        return ADULT
    try:
        years = float(age)
    except (TypeError, ValueError):
        return "a young child about five heads tall"
    heads = next((h for upto, h in CHILD if years <= upto), None)
    return f"a {years:g}-year-old child about {heads} heads tall" if heads else ADULT


def prompt_for(age, adult: bool) -> str:
    grown = adult or build(age, adult) == ADULT
    return PROMPT.format(build=build(age, adult), face=ADULT_FACE if grown else CHILD_FACE)


async def real_proportions(sheet: bytes, *, age=None, adult: bool) -> tuple[bytes, dict]:
    """(the sheet with a head of the right size for the age, what was done). Never blocks
    a sheet: an edit that fails keeps the GPT drawing, unless the balance ran out."""
    from services import engine_health
    from services.ai.image_client import comfy_image

    try:
        data, _mime, meta = await comfy_image(stage="sheet_proportions", model=MODEL, prompt=prompt_for(age, adult),
                                              references=[sheet])
        return data, {"applied": True, "gpu_seconds": float(meta.get("gpu_seconds") or 0)}
    except Exception as e:  # noqa: BLE001
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[sheet_proportions] kept the sheet as drawn: {type(e).__name__}: {str(e)[:160]}")
        return sheet, {"applied": False, "reason": type(e).__name__}
