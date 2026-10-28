"""A person's face from three sides, next to their sheet (owner, 2026-10-28).

The sheet is drawn from a front photo and shows the face from the front, while the
scenes show people turned three-quarters or in profile: Qwen and GPT both invented
those sides as a stock handsome face, and a father who looked like himself on his
sheet looked like nobody in the video. The parent may now upload the face from more
sides; from the sheet and the photos Qwen draws the head three times (front,
three-quarter, side) in the sheet's style, about a cent on Comfy. `card()` puts the
sheet and the three heads side by side, and that one picture is the person's
reference for the shot pictures: the same number of references, every side of the face.
The book's portraits, the sheet's look and the video keep the plain sheet.
"""
from __future__ import annotations

import io
import logging

logger = logging.getLogger("head_views")

MODEL = "comfy/keyframe_qwen21"
CARD_HEIGHT = 1024
CARD_NOTE = "their full figure and their face from the front, three-quarter and side, one person drawn once"

PROMPT = ("<image1> is a cartoon character sheet of a person; the other images are real photos of the same person, for "
          "their true face shape from each side only. Draw this same cartoon person's head and shoulders three times "
          "side by side on a plain white background, in exactly the art style, line quality, colors and shading of "
          "<image1> (a 2D storybook cartoon, never a photo): facing front on the left, turned three-quarters to the "
          "left in the middle, and in side profile facing left on the right. Keep their exact face in every view: the "
          "same face width and shape, cheeks, eyes and eyelids, eyebrows, nose width and shape, mouth, hairline, hair "
          "texture, and any beard's exact shape, fullness and how far up the cheeks it grows. Neutral relaxed "
          "expression, the same top as <image1>. Three heads only, the same size, evenly spaced, no body below the "
          "shoulders, no text.")


async def draw(sheet: bytes, photos: list[bytes]) -> tuple[bytes, float | None] | None:
    """(PNG of the three heads, GPU seconds), or None when it can't be drawn (the sheet
    alone stays the reference: this never blocks a story)."""
    from services.ai import fake_providers
    from services.ai.image_client import comfy_image

    if fake_providers.enabled() or not photos:
        return None
    try:
        data, _mime, meta = await comfy_image(stage="head_views", model=MODEL, prompt=PROMPT,
                                              references=[sheet, *photos[:3]])
        return data, meta.get("gpu_seconds")
    except Exception as e:  # noqa: BLE001
        from services import engine_health

        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[head_views] skipped: {type(e).__name__}: {str(e)[:200]}")
        return None


def card(sheet: bytes, heads: bytes) -> bytes:
    """The sheet and the three heads side by side at one height, on white, as a PNG."""
    from PIL import Image

    def fit(data: bytes) -> Image.Image:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        flat = Image.new("RGB", img.size, "white")
        flat.paste(img, mask=img.getchannel("A"))
        return flat.resize((round(img.width * CARD_HEIGHT / img.height), CARD_HEIGHT), Image.LANCZOS)

    body, faces = fit(sheet), fit(heads)
    out = Image.new("RGB", (body.width + faces.width, CARD_HEIGHT), "white")
    out.paste(body, (0, 0))
    out.paste(faces, (body.width, 0))
    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


async def for_asset(order: dict, sheet_png: bytes, photo_urls: list[str], save) -> dict:
    """Draw the three heads for a sheet just made from `photo_urls` (front first); `save`
    stores a PNG and returns its URL. The fields to keep on the character's asset."""
    from services.child_character_service import _fetch_source_bytes

    photos = []
    for url in photo_urls:
        got = await _fetch_source_bytes(url, owner_id=order.get("user_id"))
        if got:
            photos.append(got[0])
    drawn = await draw(sheet_png, photos)
    if not drawn:
        return {"head_views_url": None}
    data, gpu = drawn
    return {"head_views_url": await save(data), "head_views_gpu_seconds": gpu}
