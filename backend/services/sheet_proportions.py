"""Real body proportions on a drawn character sheet.

GPT Image keeps the photo's face size: a father drawn from a selfie came out five heads
tall, and the scenes copied his big head (owner: "the head is big and looks silly").
Numbers in the GPT prompt, a reworded intro and the style picture's proportions all left
him at five heads; stretching the body below the neck gave a long thin body (owner: no).
A Qwen edit of the drawn sheet, the same person with a smaller head, is the one the owner
approved: the face, clothes and build stay as drawn. A failed edit keeps the GPT sheet.
Asking it for "a longer torso and longer legs" on a sheet GPT had already drawn right
gave a lanky boy and a thin, very tall father (owner: "why are they so tall?"): the
head is measured first (Florence's head box against the figure) and only a big one is
edited, with the build kept.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("sheet_proportions")

MODEL = "comfy/sheet_qwen21"   # the keyframe workflow at the sheet's portrait 1024x1536
DETECT_MODEL = "fal-ai/florence-2-large/open-vocabulary-detection"
ADULT = "a grown-up about seven heads tall"
CHILD = ((2, "four"), (4, "four and a half"), (6, "five"), (9, "five and a half"), (12, "six"), (15, "six and a half"))
# Heads tall (top of the hair to the chin) at or above which a sheet is left as drawn: the
# sheets behind the pictures the owner liked measured 7.35 (father) and 4.6 (a four-year-old).
ADULT_FITS = 6.3
CHILD_FITS = ((2, 3.6), (4, 4.1), (6, 4.4), (9, 4.9), (12, 5.4), (15, 5.8))
# "the same face, hair, beard" gave the four-year-old a beard: facial hair is said per person.
PROMPT = ("Redraw <image1> as the same full-body character sheet: exactly the same person with the same face, "
          "hair, skin, clothes, shoes, colors, pose, build and art style ({face}). The only change: the head is "
          "drawn a little smaller against the body, so that they are {build}. The body keeps its own build: the "
          "same shoulder width, chest and arm and leg thickness, never slimmer and never longer-legged. One "
          "figure, head to toe, centered on a plain white background. No text.")
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


def fits_from(age, adult: bool) -> float:
    """Heads tall from which the sheet needs no edit."""
    if adult:
        return ADULT_FITS
    try:
        years = float(age)
    except (TypeError, ValueError):
        return CHILD_FITS[2][1]
    return next((h for upto, h in CHILD_FITS if years <= upto), ADULT_FITS)


async def heads_tall(sheet: bytes) -> float | None:
    """The figure's height in heads (top of the hair to the chin), or None if no head is found."""
    import io

    import numpy as np
    from PIL import Image

    from services.ai import fal

    url = await fal.upload(env_key="FAL_KEY_TEXT", data=sheet, content_type="image/png", file_name="sheet.png")
    found = await fal.run(stage="sheet_proportions", env_key="FAL_KEY_TEXT", model=DETECT_MODEL,
                          arguments={"image_url": url, "text_input": "head"}, timeout=180)
    boxes = (found.get("results") or {}).get("bboxes") or []
    if not boxes:
        return None
    b = min(boxes, key=lambda b: b["y"])
    a = np.asarray(Image.open(io.BytesIO(sheet)).convert("RGB")).astype(int)
    rows = np.where(((255 * 3 - a.sum(axis=2)) > 60).any(axis=1))[0]
    if len(rows) < 50:
        return None
    top, bottom = int(rows[0]), int(rows[-1])
    chin = b["y"] + b["h"]
    return round((bottom - top) / (chin - top), 2) if chin > top else None


def prompt_for(age, adult: bool) -> str:
    grown = adult or build(age, adult) == ADULT
    return PROMPT.format(build=build(age, adult), face=ADULT_FACE if grown else CHILD_FACE)


async def real_proportions(sheet: bytes, *, age=None, adult: bool) -> tuple[bytes, dict]:
    """(the sheet with a head of the right size for the age, what was done). Never blocks
    a sheet: an edit that fails keeps the GPT drawing, unless the balance ran out."""
    from services import engine_health
    from services.ai.image_client import comfy_image

    from services.ai import fake_providers

    try:
        heads = None if fake_providers.enabled() else await heads_tall(sheet)
        if heads is not None and heads >= fits_from(age, adult):
            return sheet, {"applied": False, "reason": "fits", "heads": heads}
        data, _mime, meta = await comfy_image(stage="sheet_proportions", model=MODEL, prompt=prompt_for(age, adult),
                                              references=[sheet])
        return data, {"applied": True, "heads_before": heads, "gpu_seconds": float(meta.get("gpu_seconds") or 0)}
    except Exception as e:  # noqa: BLE001
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[sheet_proportions] kept the sheet as drawn: {type(e).__name__}: {str(e)[:160]}")
        return sheet, {"applied": False, "reason": type(e).__name__}
