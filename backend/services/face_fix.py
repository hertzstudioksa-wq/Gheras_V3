"""A grown-up drawn from a parent's photo keeps the parent's face in every shot picture.

Qwen invents a stock face for any angle its references don't show: the father in
profile or looking down came out slim, sharp-jawed and with a full hairline whatever
face reference he had, and ignored a rule asking for his head up. This step redraws
only that person's head inside the finished picture from the face embedding of the
parent's own photo (SDXL + IPAdapter FaceID Plus V2 + InsightFace, workflow face_id),
at the picture's angle, light and style; the head is found by Florence and edited
through an oval mask, so the rest of the picture never changes. The owner picked it
after the kitchen and swing tests (2026-10-29): strength 0.5 kept the angle and the
expression, 0.65 turned the face to the camera. About a cent a face. Whatever goes
wrong (no photo any more, no head found, two grown-ups who could be confused, a failed
job), the picture stays as drawn.
"""
from __future__ import annotations

import io
import logging

from db import db
from services import house_style

logger = logging.getLogger("face_fix")

MODEL = "comfy/face_id"
WORKFLOW = "face_id"
DENOISE = 0.5
SETTING = "comfy.face_id"
DETECT_MODEL = "fal-ai/florence-2-large/open-vocabulary-detection"
MEN = {"father", "grandfather", "uncle"}
WOMEN = {"mother", "grandmother", "aunt"}
CHILDREN = {"child", "friend", "brother", "sister", "sibling", "cousin"}
PROMPT = ("a painted storybook illustration, an adult {who}'s face, soft painterly shading, clean outlines, "
          "children's book art")


def gender_of(kind: str) -> str | None:
    base = house_style.base_type(kind or "")
    return "man" if base in MEN else "woman" if base in WOMEN else None


def targets(shot: dict, sheets: dict) -> list[str]:
    """The grown-ups from a photo whose face this shot can fix: each must be the only
    grown-up of their gender in it. Anyone else in the shot who could be a grown-up of
    either gender (a teacher, someone the plan made up) makes the whole shot unsafe."""
    cast = list(dict.fromkeys(shot.get("characters") or []))
    unknown = [t for t in cast if not gender_of(t) and house_style.base_type(t) not in CHILDREN]
    if unknown:
        return []
    grown = [t for t in cast if gender_of(t)]
    return [t for t in grown if (sheets.get(t) or {}).get("from_photo") and (sheets.get(t) or {}).get("photo_url")
            and sum(gender_of(o) == gender_of(t) for o in grown) == 1]


async def on() -> bool:
    s = await db.settings.find_one({"key": SETTING}, {"_id": 0, "value": 1})
    return (s or {}).get("value", True) is not False


Box = tuple[int, int, int, int]  # x, y, w, h


async def _detect(picture: bytes, words: str) -> list[Box]:
    from services.ai import fal

    url = await fal.upload(env_key="FAL_KEY_TEXT", data=picture, content_type="image/png", file_name="shot.png")
    found = await fal.run(stage="face_fix", env_key="FAL_KEY_TEXT", model=DETECT_MODEL,
                          arguments={"image_url": url, "text_input": words}, timeout=180)
    return [(int(b["x"]), int(b["y"]), int(b["w"]), int(b["h"]))
            for b in (found.get("results") or {}).get("bboxes") or []]


def plausible(box: Box, size: tuple[int, int]) -> bool:
    """Shaped and sized like one face in the picture. Florence asked for "a man's head"
    boxed a window corner, a cutting board and a child's legs; "a man's face" found the
    face, and anything else is thrown out here."""
    x, y, w, h = box
    area = w * h / float(size[0] * size[1])
    return h > 0 and 0.55 <= w / h <= 1.7 and 0.002 <= area <= 0.12


def overlap(a: Box, b: Box) -> float:
    """How much of the smaller box the other covers."""
    w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h) / float(min(a[2] * a[3], b[2] * b[3]) or 1)


async def _face_box(picture: bytes, who: str, child_in_shot: bool) -> Box | None:
    """The grown-up's face, or None when it isn't found for sure."""
    from PIL import Image

    size = Image.open(io.BytesIO(picture)).size
    faces = [b for b in await _detect(picture, f"{who}'s face") if plausible(b, size)]
    if not faces:
        return None
    face = max(faces, key=lambda b: b[2] * b[3])
    if child_in_shot:
        kids = [b for b in await _detect(picture, "child's face") if plausible(b, size)]
        if any(overlap(face, k) > 0.3 for k in kids):
            return None  # it may be the child's face: never give a child the parent's face
    return face


def mask_png(size: tuple[int, int], box: Box) -> bytes:
    """White oval from the face box out to the hair above and the beard below, soft edge."""
    from PIL import Image, ImageDraw, ImageFilter

    x, y, w, h = box
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).ellipse((x - w * 0.18, y - h * 0.45, x + w * 1.18, y + h * 1.18), fill=255)
    m = m.filter(ImageFilter.GaussianBlur(6))
    buf = io.BytesIO()
    Image.merge("RGB", (m, m, m)).save(buf, "PNG")
    return buf.getvalue()


async def fix_faces(order: dict, shot: dict, picture: bytes, mime: str, sheets: dict,
                    queue_key: str = "") -> tuple[bytes, str, float, list[str]]:
    """(the picture with the grown-ups' real faces, its mime, GPU seconds, who was fixed)."""
    from PIL import Image

    from services import engine_health
    from services.ai import comfy, fake_providers
    from services.shot_pipeline import _fetch_source_bytes

    who = targets(shot, sheets)
    if not who or fake_providers.enabled() or not await on():
        return picture, mime, 0.0, []
    gpu, fixed = 0.0, []
    for t in who:
        try:
            photo = await _fetch_source_bytes(sheets[t]["photo_url"], owner_id=order.get("user_id"))
            if not photo:
                continue  # the photo was deleted (30 days after delivery): the picture stays as drawn
            box = await _face_box(picture, gender_of(t), any(house_style.base_type(c) in CHILDREN
                                                              for c in shot.get("characters") or []))
            if not box:
                continue
            size = Image.open(io.BytesIO(picture)).size
            names = {"scene_image": await comfy.upload(picture, "face-scene.png", stage="face_fix"),
                     "face_mask": await comfy.upload(mask_png(size, box), "face-mask.png", stage="face_fix"),
                     "ref_1": await comfy.upload(photo[0], "face-photo.png", stage="face_fix")}
            data, out_mime, job = await comfy.run(stage="face_fix", workflow=WORKFLOW, queue_key=queue_key, fills={
                **names, "scene_prompt": PROMPT.format(who=gender_of(t)), "seed": comfy.new_seed(),
                "denoise": DENOISE, "output_prefix": "gheras/face_fix"})
            gpu += float(comfy.gpu_seconds(job) or 0)
            if Image.open(io.BytesIO(data)).size != size:
                continue  # never a picture of another size in the story
            picture, mime = data, out_mime or mime
            fixed.append(t)
        except Exception as e:  # noqa: BLE001
            if engine_health.is_balance_message(e):
                raise
            logger.warning(f"[face_fix] {t} kept as drawn: {type(e).__name__}: {str(e)[:200]}")
    return picture, mime, gpu, fixed
