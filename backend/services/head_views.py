"""A person's face from more sides, next to their sheet (owner, 2026-10-28).

The sheet is drawn from a front photo and shows the face from the front, while the
scenes show people turned three-quarters or in profile: Qwen and GPT both invented
those sides as a stock handsome face, and a father who looked like himself on his
sheet looked like nobody in the video. The heads go to the shot pictures as a reference
of their own, right after the person's sheet, laid out 2×2 on a square (`grid`): next to
the body in one wide picture they reached Qwen a few dozen pixels high and the scene's
father was a stock face again; as their own square his hairline, thinning curls, grey in
the beard and face width came through. Only grown-ups get it in the shots: with the
child's own square too, Qwen drew the child twice and gave the copy the father's beard.
The book's portraits, the sheet's look and the video keep the plain sheet.

The heads come from:
- the parent's extra photos (three-quarter, side), when there are any: each one drawn on
  its own with the sheet's own prompt, the head kept at the photo's angle, at medium
  quality (`from_photos`). All the photos in one sheet call came out as a semi-realistic
  painted portrait; one photo per drawing is the owner's pick, and it gave the closest
  features of all the tries;
- otherwise the sheet alone: Qwen draws the head three times in the sheet's style, about
  a cent on Comfy (`draw`).
"""
from __future__ import annotations

import asyncio
import io
import logging

logger = logging.getLogger("head_views")

MODEL = "comfy/keyframe_qwen21"
ANGLE_QUALITY = "medium"
CARD_HEIGHT = 1024
GRID_SIDE = 1536

PROMPT = ("<image1> is a cartoon character sheet of a person. Draw this same cartoon person's head and shoulders three "
          "times side by side on a plain white background, in exactly the 2D cartoon style of <image1>: the same "
          "clean outlines, flat colors and soft simple shading, no realistic skin, hair or lighting. Facing front on "
          "the left, turned three-quarters to the left in the middle, and in side profile facing left on the right. "
          "Keep their exact face in every view: the same face width and shape, cheeks, eyes and eyelids, eyebrows, "
          "nose width and shape, mouth, hairline, hair, and any beard's exact shape, fullness and how far up the "
          "cheeks it grows. Neutral relaxed expression, the same top as <image1>. Three heads only, the same size, "
          "evenly spaced, no body below the shoulders, no text.")
ANGLE_LINE = "The head stays turned exactly as in the photo (the same angle), with a calm, friendly expression."
HEAD_ONLY = ("COMPOSITION: head and shoulders only, centered on a plain pure white background (opaque white), the head "
             "turned exactly as in the photo; no full body, no props, no text.")


def _balance(e: Exception) -> bool:
    from services import engine_health

    return engine_health.is_balance_message(e)


async def draw(sheet: bytes) -> tuple[bytes, float | None] | None:
    """(PNG of the three heads, GPU seconds), or None when it can't be drawn (the sheet
    alone stays the reference: this never blocks a story)."""
    from services.ai import fake_providers
    from services.ai.image_client import comfy_image

    if fake_providers.enabled() or not sheet:
        return None
    try:
        data, _mime, meta = await comfy_image(stage="head_views", model=MODEL, prompt=PROMPT, references=[sheet])
        return data, meta.get("gpu_seconds")
    except Exception as e:  # noqa: BLE001
        if _balance(e):
            raise
        logger.warning(f"[head_views] skipped: {type(e).__name__}: {str(e)[:200]}")
        return None


def angle_prompt(sheet_prompt: str) -> str:
    """The sheet's own prompt for one more side of the face: the head kept at the photo's
    angle, head and shoulders only."""
    from services import house_style

    text = sheet_prompt.replace(house_style.FACE_FORWARD, "")
    cut = text.find("COMPOSITION:")
    return (text[:cut] if cut >= 0 else f"{text}\n\n") + f"{ANGLE_LINE} {HEAD_ONLY}"


def _trimmed_img(img):
    box = img.convert("L").point(lambda v: 255 if v < 238 else 0).getbbox()
    return img.crop(box) if box else img


def _trimmed(data: bytes):
    """The drawing without its white margin."""
    from PIL import Image

    return _trimmed_img(Image.open(io.BytesIO(data)).convert("RGB"))


def head_of(sheet: bytes) -> bytes:
    """The head and shoulders of a full-body sheet (figure on white), as a PNG."""
    from PIL import Image

    img = Image.open(io.BytesIO(sheet)).convert("RGB")
    shape = img.convert("L").point(lambda v: 255 if v < 238 else 0)
    left, top, right, bottom = shape.getbbox() or (0, 0, img.width, img.height)
    h = bottom - top
    band = shape.crop((left, top, right, top + max(1, int(h * .12)))).getbbox()
    cx = left + ((band[0] + band[2]) / 2 if band else (right - left) / 2)
    side = h * 0.24
    crop = img.crop((int(cx - side / 2), max(0, int(top - side * .05)), int(cx + side / 2), int(top + side * .95)))
    out = io.BytesIO()
    crop.save(out, "PNG")
    return out.getvalue()


def row(heads: list[bytes], height: int = CARD_HEIGHT) -> bytes:
    """Head drawings side by side at one height on white, as a PNG."""
    from PIL import Image

    tiles = [_trimmed(h) for h in heads]
    tall = round(height * 0.8)
    tiles = [t.resize((round(t.width * tall / t.height), tall), Image.LANCZOS) for t in tiles]
    gap = 40
    out = Image.new("RGB", (sum(t.width for t in tiles) + gap * (len(tiles) + 1), height), "white")
    x = gap
    for t in tiles:
        out.paste(t, (x, (height - t.height) // 2))
        x += t.width + gap
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


async def from_photos(sheet: bytes, sheet_prompt: str, photos: list[bytes], provider: str, model: str,
                      style_ref: bytes | None) -> tuple[bytes, int] | None:
    """(the sheet's head + each extra photo drawn on its own, side by side; how many were
    drawn), or None when none could be drawn."""
    from services.ai import fake_providers
    from services.child_character_service import _generate_character

    if fake_providers.enabled() or not photos:
        return None
    prompt = angle_prompt(sheet_prompt)

    async def one(photo: bytes) -> bytes | None:
        try:
            res = await _generate_character(photo, prompt, provider, model, style_ref, quality=ANGLE_QUALITY)
            return res["image_bytes"]
        except Exception as e:  # noqa: BLE001 — that side is left out
            if _balance(e):
                raise
            logger.warning(f"[head_views] angle skipped: {type(e).__name__}: {str(e)[:200]}")
            return None

    drawn = [d for d in await asyncio.gather(*(one(p) for p in photos)) if d]
    if not drawn:
        return None
    return row([head_of(sheet), *drawn]), len(drawn)


def grid(heads: bytes, side: int = GRID_SIDE) -> bytes:
    """The heads (drawings side by side on white) laid out 2×2 on a white square, each
    as big as it fits, as a PNG; the picture as it is when it can't be split."""
    from PIL import Image

    img = Image.open(io.BytesIO(heads)).convert("RGB")
    gray = img.convert("L")
    ink = [gray.crop((x, 0, x + 1, img.height)).getextrema()[0] < 238 for x in range(img.width)]
    spans, start = [], None
    for x, on in enumerate([*ink, False]):
        if on and start is None:
            start = x
        elif not on and start is not None:
            if x - start > img.width // 20:
                spans.append((start, x))
            start = None
    if len(spans) < 2:
        return heads
    cell = side // 2
    out = Image.new("RGB", (side, side), "white")
    for i, (a, b) in enumerate(spans[:4]):
        tile = _trimmed_img(img.crop((a, 0, b, img.height)))
        tile.thumbnail((cell - 24, cell - 24), Image.LANCZOS)
        out.paste(tile, ((i % 2) * cell + (cell - tile.width) // 2, (i // 2) * cell + (cell - tile.height) // 2))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


async def for_asset(sheet_png: bytes, save, *, photos: list[bytes] | None = None, sheet_prompt: str = "",
                    provider: str = "", model: str = "", style_ref: bytes | None = None) -> dict:
    """The heads for a sheet just made from a photo (from the parent's extra `photos` when
    there are any, else from the sheet); `save` stores a PNG and returns its URL. The fields
    to keep on the character's asset."""
    # Every field each time: a redrawn sheet's asset keeps no count from the drawing before.
    fields = {"head_views_url": None, "head_views_gpu_seconds": None, "head_views_angles": 0,
              "head_views_model": None, "head_views_quality": None}
    if photos:
        made = await from_photos(sheet_png, sheet_prompt, photos, provider, model, style_ref)
        if made:
            heads, n = made
            return {**fields, "head_views_url": await save(heads), "head_views_angles": n, "head_views_model": model,
                    "head_views_quality": ANGLE_QUALITY}
    drawn = await draw(sheet_png)
    if not drawn:
        return fields
    data, gpu = drawn
    return {**fields, "head_views_url": await save(data), "head_views_gpu_seconds": gpu}
