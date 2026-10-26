"""Automatic check of every shot before it's used (owner decision, 2026-10-25).

Kling sometimes clones a character (the father appeared twice when the camera
"revealed" the room) or walks a body through an object (the child through a
bridge railing), and image models write misspelled words. A small vision model
looks at the shot's start frame, and later at four frames of its clip, and
says whether that happened. A flagged keyframe is redrawn once, a flagged clip
is animated once more with calmer motion; the verdict stays on the shot so the
admin sees it. It never blocks delivery: when the reviewer can't be reached,
or the setting is off, the shot is used as is — except when the reviewer's
balance ran out: then the order pauses for the top-up like every other paid
step (a whole story once went out unchecked, with a frame of pure static).
Coloured static is caught without a model, so even then it never ships.
"""
from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

from db import db
from services import engine_health

logger = logging.getLogger("clip_review")

REVIEW_MODEL = "anthropic/claude-haiku-5.5"
CLIP_FRAMES = 4
PROBLEMS = ("duplicate", "extra_person", "clipping", "vanishing", "text", "deformed", "wrong_look", "outfit_change",
            "melting", "action_missing", "mood_mismatch", "noise", "object_alive")
# Other words models use for the same problems.
SYNONYMS = {"costume": "outfit_change", "clothing": "outfit_change", "clothes": "outfit_change",
            "accessor": "outfit_change", "hat": "outfit_change", "cap": "outfit_change",
            "identity": "wrong_look", "lookalike": "wrong_look", "look_alike": "wrong_look", "mismatch": "wrong_look",
            "clone": "duplicate", "twin": "duplicate",
            "melt": "melting", "stretch": "melting", "morph": "melting", "ooz": "melting", "warp": "melting",
            "not_happen": "action_missing", "no_action": "action_missing", "missing_action": "action_missing",
            "expression": "mood_mismatch", "emotion": "mood_mismatch", "mood": "mood_mismatch",
            "alive": "object_alive", "animated_toy": "object_alive", "toy_mov": "object_alive"}
REF_SIDE = 512  # reference sheets are shrunk: they only need faces, hair and colors
# Qwen sometimes returns coloured static instead of a picture (2 frames of the
# first 18: a figure on white broken into confetti). Inside small blocks its
# colours point every way, over a washed-out canvas. Measured on 96 real
# frames: static has a hue spread of 0.14-0.24 with under half of the blocks
# saturated; real pictures stay under 0.03 when that pale, and colourful ones
# (a jungle at sunset reached 0.12) are 75%+ saturated. A few bright objects on
# a plain background (a story object's reference, 0.12) are told apart by how
# the colour clumps: 30-37% of static's coloured blocks have coloured blocks all
# around them, 48%+ for real shapes (245 frames checked).
STATIC_SPREAD = 0.10
STATIC_SATURATED = 0.70
STATIC_CLUSTERED = 0.42
# Static fills the page with colour (29-46% of the blocks); a thin object on a
# blank reference page (a scooter: 4-5%) is not static, however scattered.
STATIC_MIN_SATURATED = 0.2

SYSTEM = (
    "You check frames of a 2D cartoon shot from a children's story before a family sees it. You get the people who "
    "should be in the shot and what they do. Report only clear, visible mistakes:\n"
    "- duplicate: the same character appears twice in one frame (two copies of the father)\n"
    "- extra_person: more people than expected (ignore tiny far-away background figures)\n"
    "- clipping: a body passes through a solid object (railing, rope, wall, furniture, another person) or a limb "
    "merges into something\n"
    "- vanishing: a character disappears or pops in between frames\n"
    "- text: written words or letters anywhere, except printing on someone's clothes that their reference sheet "
    "shows too (a shirt from the family's photo)\n"
    "- deformed: a badly broken face or body\n"
    "- wrong_look: someone is clearly a different person from their reference sheet (another hair color or length, "
    "skin tone, age, beard or glasses), or two different characters look like the same person (the same face and "
    "clothes twice); a cartoon redrawing, another expression or pose, or slightly different curls is fine\n"
    "- outfit_change: someone's clothes or accessories (hat, cap, glasses, bag, cape) differ from the shot's first "
    "frame or disappear during the clip\n"
    "- melting: an object or body melts, oozes, stretches, grows, shrinks or changes shape between frames (a tower "
    "getting taller, blocks flowing like dough)\n"
    "- action_missing: the main action described in `action` clearly does not happen (in a single picture: the "
    "picture doesn't show that moment)\n"
    "- mood_mismatch: a face clearly shows the opposite feeling of `action` (smiling while the action says crying, "
    "sad while it says laughing)\n"
    "- object_alive: one of `story_objects` moves, waves, blinks or talks by itself like a living character\n"
    "`story_objects` are things in the shot (toys, props), even when one looks like a cartoon character: they are "
    "never people, so they never count as an extra person or a duplicate.\n"
    "The images come in this order: one reference sheet per name in reference_sheets (when given), then the "
    "shot's first frame (when given), then the frames to check. Costumes and accessories are allowed to differ "
    "from a sheet; faces, hair and skin are not.\n"
    "A natural cartoon pose, motion blur, or someone partly out of frame is fine. A count that differs from the "
    "expected people is not a problem by itself: someone can be hidden in a hug, behind another person or at the "
    "edge (vanishing means a person visible in one frame is gone in the next). When unsure, it is fine.\n"
    'Answer with JSON only: {"ok": true or false, "people_seen": <most people in one frame>, '
    '"problems": [zero or more of: duplicate, extra_person, clipping, vanishing, text, deformed, wrong_look, '
    'outfit_change, melting, action_missing, mood_mismatch, object_alive], '
    '"note": "<one short English sentence>"}'
)


async def enabled() -> bool:
    s = await db.settings.find_one({"key": "clip_review.enabled"}, {"_id": 0, "value": 1})
    return (s or {}).get("value", True) is not False


def _problem(raw) -> str | None:
    """The known problem a model's wording names ("duplicate person", "Clipping through railing"...)."""
    text = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    return next((p for p in PROBLEMS if p in text or text.startswith(p.split("_")[0])), None) or \
        next((p for k, p in SYNONYMS.items() if k in text), None)


def _shrink(data: bytes, side: int = REF_SIDE) -> tuple[bytes, str]:
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((side, side))
    out = io.BytesIO()
    img.save(out, "JPEG", quality=85)
    return out.getvalue(), "image/jpeg"


def static_measure(data: bytes) -> tuple[float, float, float]:
    """(hue spread inside the saturated 8px blocks, share of saturated blocks, share
    of those with saturated blocks on all four sides) of a 384px copy."""
    import numpy as np
    from PIL import Image

    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((384, 384))
    hsv = np.asarray(img.convert("HSV"), dtype=np.float32)
    hue, sat = hsv[..., 0] / 255 * 2 * np.pi, hsv[..., 1] / 255
    h, w = hue.shape[0] // 8 * 8, hue.shape[1] // 8 * 8

    def blocks(a):
        return a[:h, :w].reshape(h // 8, 8, w // 8, 8).mean(axis=(1, 3))

    mean_sat = blocks(sat)
    # 1 - length of the mean colour vector: 0 = one hue per block, 1 = every hue
    spread = 1 - np.hypot(blocks(sat * np.cos(hue)), blocks(sat * np.sin(hue))) / (mean_sat + 1e-6)
    saturated = mean_sat > 0.2
    inner = saturated.copy()
    inner[1:, :] &= saturated[:-1, :]
    inner[:-1, :] &= saturated[1:, :]
    inner[:, 1:] &= saturated[:, :-1]
    inner[:, :-1] &= saturated[:, 1:]
    inner[0, :] = inner[-1, :] = inner[:, 0] = inner[:, -1] = False
    if not saturated.any():
        return 0.0, 0.0, 0.0
    return float(spread[saturated].mean()), float(saturated.mean()), float(inner.sum() / saturated.sum())


def static_verdict(images: list[bytes]) -> dict | None:
    """A flagged verdict when any image is coloured static, else None."""
    for data in images:
        try:
            spread, saturated, clustered = static_measure(data)
        except Exception:  # noqa: BLE001 — an unreadable image is the model check's business
            continue
        if spread > STATIC_SPREAD and STATIC_MIN_SATURATED <= saturated < STATIC_SATURATED and clustered < STATIC_CLUSTERED:
            logger.warning(f"[review] coloured static: spread {spread:.3f}, saturated {saturated:.2f}, "
                           f"clustered {clustered:.2f}")
            return {"ok": False, "problems": ["noise"], "people_seen": None,
                    "note": f"coloured static, not a picture (spread {spread:.2f})"}
    return None


def _verdict(answer: str) -> dict:
    # The first JSON object only: an answer once carried a second one after it, and
    # the greedy match made the whole review count as skipped.
    start = (answer or "").find("{")
    data = json.JSONDecoder().raw_decode(answer[start:])[0] if start >= 0 else {}
    problems = sorted({p for p in map(_problem, data.get("problems") or []) if p})
    return {"ok": not problems, "problems": problems, "people_seen": data.get("people_seen"),
            "note": str(data.get("note") or "")[:200]}


async def _ask(stage: str, shot_key: str, images: list[tuple[bytes, str]], expected: list[str], action: str,
               sheets: list[tuple[str, bytes, str]] | None = None, first: tuple[bytes, str] | None = None,
               objects: list[str] | None = None) -> dict:
    """{ok, problems, people_seen, note} — or ok with `skipped` when the check can't run.
    `sheets` (label, bytes, mime) let it tell who is who; `first` is the shot's
    start frame, for clothes that change during a clip; `objects` = the shot's
    story objects (a character plush was counted as a fifth person)."""
    if not await enabled():
        return {"ok": True, "skipped": "off"}
    from services.ai import fal
    from services.ai.text_client import generate_vision

    try:
        refs = [await asyncio.to_thread(_shrink, data) for _, data, _ in (sheets or [])]
        if first:
            refs.append(await asyncio.to_thread(_shrink, first[0], 768))
        urls = [await fal.upload(env_key="FAL_KEY_TEXT", data=data, content_type=mime,
                                 file_name=f"review-{shot_key}-{i}.{mime.split('/')[-1]}")
                for i, (data, mime) in enumerate([*refs, *images])]
        user = json.dumps({"shot": shot_key, "frames_to_check": len(images), "expected_people": expected or ["nobody"],
                           "expected_count": len(expected), "reference_sheets": [label for label, _, _ in sheets or []],
                           "first_frame_given": bool(first), "action": (action or "")[:400],
                           "story_objects": objects or []}, ensure_ascii=False)
        answer = await generate_vision(stage=stage, model=REVIEW_MODEL, system=SYSTEM, user=user, image_urls=urls,
                                       max_tokens=600)  # 300 cut a long note mid-string: no verdict
        verdict = _verdict(answer)
    except Exception as e:  # noqa: BLE001 — a review that can't run never blocks the story...
        if engine_health.is_balance_message(e):
            raise  # ...unless its balance ran out: the order pauses for the top-up
        logger.warning(f"[review] {stage} {shot_key} skipped: {type(e).__name__}: {str(e)[:160]}")
        return {"ok": True, "skipped": "unavailable", "error": f"{type(e).__name__}: {str(e)[:160]}"}
    if not verdict["ok"]:
        logger.warning(f"[review] {stage} {shot_key} flagged: {verdict['problems']} — {verdict['note']}")
    return verdict


# A story object's reference is drawn with a cast sheet as the style sample, and
# the scooter's reference came out with the child standing on it: in the shots that
# would have put him in twice. Asked before the reference is used.
PERSON_SYSTEM = ('You look at one picture. Answer with JSON only: {"person": true or false} — true when a human '
                 "(a child or an adult) is drawn anywhere in it; a toy, a doll or a cartoon animal is not a person.")


async def shows_person(image: bytes) -> bool | None:
    """Is a human drawn in the picture? None when the check can't run."""
    from services.ai import fake_providers, fal
    from services.ai.text_client import generate_vision

    if fake_providers.enabled() or not await enabled():
        return None
    try:
        data, mime = await asyncio.to_thread(_shrink, image, 768)
        url = await fal.upload(env_key="FAL_KEY_TEXT", data=data, content_type=mime, file_name="object-reference.jpg")
        answer = await generate_vision(stage="object_reference_review", model=REVIEW_MODEL, system=PERSON_SYSTEM,
                                       user="Is there a person in this picture?", image_urls=[url], max_tokens=60)
        start = (answer or "").find("{")
        return bool(json.JSONDecoder().raw_decode(answer[start:])[0].get("person")) if start >= 0 else None
    except Exception as e:  # noqa: BLE001
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[review] object reference check skipped: {type(e).__name__}: {str(e)[:160]}")
        return None


async def review_keyframe(shot_key: str, image: bytes, mime: str, expected: list[str], action: str,
                          sheets: list[tuple[str, bytes, str]] | None = None, objects: list[str] | None = None) -> dict:
    static = await asyncio.to_thread(static_verdict, [image])
    if static:
        return static
    verdict = await _ask("keyframe_review", shot_key, [(image, mime or "image/png")], expected, action, sheets,
                         objects=objects)
    # Nothing moves in one picture: the reviewer still flagged "object_alive" on
    # keyframes (three takes each, some without the toy in them at all).
    if "object_alive" in (verdict.get("problems") or []):
        problems = [p for p in verdict["problems"] if p != "object_alive"]
        verdict = {**verdict, "problems": problems, "ok": not problems}
    return verdict


def _clip_frames(data: bytes, count: int = CLIP_FRAMES) -> list[bytes]:
    from services.video_assembly_service import _ffmpeg_bin
    from storage import STORAGE_DIR

    root = STORAGE_DIR / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    work = tempfile.mkdtemp(prefix="review-", dir=str(root))
    try:
        src = os.path.join(work, "clip.mp4")
        with open(src, "wb") as f:
            f.write(data)
        probe = subprocess.run([_ffmpeg_bin(), "-hide_banner", "-i", src], capture_output=True, text=True, timeout=30)
        m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr or "")
        seconds = (int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) if m else 5.0
        frames = []
        for i in range(count):
            at = seconds * (i + 0.5) / count
            out = os.path.join(work, f"f{i}.jpg")
            subprocess.run([_ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{at:.2f}", "-i", src,
                            "-frames:v", "1", "-vf", "scale=768:-2", "-q:v", "4", out], check=True, timeout=60)
            with open(out, "rb") as f:
                frames.append(f.read())
        return frames
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def review_clip(shot_key: str, data: bytes, expected: list[str], action: str,
                      sheets: list[tuple[str, bytes, str]] | None = None, first: tuple[bytes, str] | None = None,
                      objects: list[str] | None = None) -> dict:
    try:
        frames = await asyncio.to_thread(_clip_frames, data)
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "skipped": "frames", "error": f"{type(e).__name__}: {str(e)[:160]}"}
    static = await asyncio.to_thread(static_verdict, frames)
    if static:
        return static
    return await _ask("clip_review", shot_key, [(f, "image/jpeg") for f in frames], expected, action, sheets, first,
                      objects)
