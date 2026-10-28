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
# Six frames: a child rose off the ground and a leg kicked the air between four of them.
CLIP_FRAMES = 6
PROBLEMS = ("duplicate", "extra_person", "role_swap", "clipping", "vanishing", "text", "deformed", "wrong_look",
            "outfit_change", "melting", "floating", "camera_gaze", "wrong_stage", "action_missing", "mood_mismatch",
            "noise", "object_alive")
# A model's words for one cast member standing in another's place (checked before the
# "wrong_..." prefix would read them as wrong_look).
ROLE_WORDS = ("swap", "switched", "wrong_person", "wrong_character", "wrong_role", "role")
# Other words models use for the same problems.
SYNONYMS = {"costume": "outfit_change", "clothing": "outfit_change", "clothes": "outfit_change",
            "accessor": "outfit_change", "hat": "outfit_change", "cap": "outfit_change",
            "identity": "wrong_look", "lookalike": "wrong_look", "look_alike": "wrong_look", "mismatch": "wrong_look",
            "clone": "duplicate", "twin": "duplicate",
            "melt": "melting", "stretch": "melting", "morph": "melting", "ooz": "melting", "warp": "melting",
            "not_happen": "action_missing", "no_action": "action_missing", "missing_action": "action_missing",
            "expression": "mood_mismatch", "emotion": "mood_mismatch", "mood": "mood_mismatch",
            "alive": "object_alive", "animated_toy": "object_alive", "toy_mov": "object_alive",
            "float": "floating", "levitat": "floating", "hover": "floating",
            "gaze": "camera_gaze", "viewer": "camera_gaze", "camera": "camera_gaze",
            "stage": "wrong_stage", "bloom": "wrong_stage",
            "color": "melting", "colour": "melting"}
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
# blank reference page (a thin ride-on toy: 4-5%) is not static, however scattered.
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
    "- melting: an object or body melts, oozes, stretches, grows, shrinks or changes shape or color between frames "
    "(a tower getting taller, blocks flowing like dough, a green bike turning blue)\n"
    "- floating: someone's feet leave the ground, the seat or the deck they stand on, or their body rises or sinks, "
    "with no jump in `action`; or a leg or arm moves in a way no body moves\n"
    "- camera_gaze: in a clip, someone turns to look straight out at the viewer, as if into the camera\n"
    "- wrong_stage: a thing that changes in the story is drawn at another stage than `action` says (a flower already "
    "open when the action says it has not bloomed yet, a finished tower when it is still being built)\n"
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
    'outfit_change, melting, floating, camera_gaze, wrong_stage, action_missing, mood_mismatch, object_alive], '
    '"note": "<one short English sentence>"}'
)


async def enabled() -> bool:
    s = await db.settings.find_one({"key": "clip_review.enabled"}, {"_id": 0, "value": 1})
    return (s or {}).get("value", True) is not False


def _problem(raw) -> str | None:
    """The known problem a model's wording names ("duplicate person", "Clipping through railing"...)."""
    text = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    if any(w in text for w in ROLE_WORDS):
        return "role_swap"
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
        # A malformed answer (a quote left unescaped in the note) passed a picture
        # unchecked: it is asked once more before the review counts as skipped.
        for tries in (1, 2):
            answer = await generate_vision(stage=stage, model=REVIEW_MODEL, system=SYSTEM, user=user,
                                           image_urls=urls, max_tokens=600)  # 300 cut a long note mid-string
            try:
                verdict = _verdict(answer)
                break
            except ValueError:
                if tries == 2:
                    raise
    except Exception as e:  # noqa: BLE001 — a review that can't run never blocks the story...
        if engine_health.is_balance_message(e):
            raise  # ...unless its balance ran out: the order pauses for the top-up
        logger.warning(f"[review] {stage} {shot_key} skipped: {type(e).__name__}: {str(e)[:160]}")
        return {"ok": True, "skipped": "unavailable", "error": f"{type(e).__name__}: {str(e)[:160]}"}
    if not verdict["ok"]:
        logger.warning(f"[review] {stage} {shot_key} flagged: {verdict['problems']} — {verdict['note']}")
    return verdict


# A story object's reference is drawn with a cast sheet as the style sample, and
# a ride-on toy's reference came out with the child standing on it: in the shots that
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


# The full review saw "4 people" on a frame with a second child in a green helmet (five
# in all), and that shot was animated. A question with only this job, listing each person,
# counted all six test pictures right (three with an extra child, three without).
# The same question tells who looks out at the viewer: the parent saw a child staring into
# the camera at the start of the race, and the full review never asked. Checked on the
# courage story's 12 pictures + 2 broken ones: the counts all right, and every flagged
# face really looked at us.
PEOPLE_SYSTEM = ("You check the people drawn in one storybook picture. List every human figure you can see, left "
                 "to right, including small ones in the background and anyone partly hidden or cut off by the frame "
                 "edge, with a few words each (age, hair, hat or helmet color, top color). Dolls, plush toys, mascots, "
                 "statues and figures printed on things are not people. Two figures that look alike are still two "
                 "entries. For each, say whether their eyes look straight out of the picture at the viewer, as if "
                 "into the camera (at_viewer: true), or at someone or something inside the picture, down or to the "
                 "side (false). A face turned toward us with the eyes looking sideways is false; someone seen from "
                 'behind is false. Reply with JSON only: {"people": [{"who": "...", "at_viewer": true or false}]}')


def _person(p) -> dict:
    if isinstance(p, dict):
        return {"who": str(p.get("who") or ""), "at_viewer": p.get("at_viewer") is True}
    return {"who": str(p), "at_viewer": False}


# How to pick a cast member out of a group picture, from their sheet (asked once per
# sheet and kept): the video model is told who is who by these words, never by a name.
LOOK_SYSTEM = ("You look at one cartoon character sheet. Describe the character so they can be picked out of a "
               "group picture: age group, hair color and style, any hat, helmet or headscarf with its color, and the "
               "top's color. At most 14 words, no name, no pose. "
               'Reply with JSON only: {"look": "..."}')


async def sheet_look(image: bytes) -> str | None:
    """A few words that pick the character out of a group picture. None when the check can't run."""
    from services.ai import fake_providers, fal
    from services.ai.text_client import generate_vision

    if fake_providers.enabled() or not await enabled():
        return None
    try:
        data, mime = await asyncio.to_thread(_shrink, image, 768)
        url = await fal.upload(env_key="FAL_KEY_TEXT", data=data, content_type=mime, file_name="sheet-look.jpg")
        answer = await generate_vision(stage="keyframe_review", model=REVIEW_MODEL, system=LOOK_SYSTEM,
                                       user="Describe this character.", image_urls=[url], max_tokens=120)
        start = (answer or "").find("{")
        look = json.JSONDecoder().raw_decode(answer[start:])[0].get("look") if start >= 0 else None
        return str(look).strip(" .")[:120] if look else None
    except Exception as e:  # noqa: BLE001
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[review] sheet look skipped: {type(e).__name__}: {str(e)[:160]}")
        return None


def placed(looks: dict[str, str]) -> list[dict]:
    """The video's who-is-who: each cast member's look from their own sheet (name → look).
    Places in the picture were tried and dropped: the review put the child's name on the
    friend in the orange helmet, and called the third child "first from the left"; the
    sheet's own look picks the person out every time."""
    out = [{"name": name, "where": "", "looks": look} for name, look in looks.items() if look]
    return out if len(out) >= 2 else []


async def people_in(image: bytes) -> list[dict] | None:
    """Every human figure in the picture ({"who", "at_viewer"}). None when the check can't run."""
    from services.ai import fake_providers, fal
    from services.ai.text_client import generate_vision

    if fake_providers.enabled() or not await enabled():
        return None
    try:
        data, mime = await asyncio.to_thread(_shrink, image, 1024)
        url = await fal.upload(env_key="FAL_KEY_TEXT", data=data, content_type=mime, file_name="head-count.jpg")
        answer = await generate_vision(stage="keyframe_review", model=REVIEW_MODEL, system=PEOPLE_SYSTEM,
                                       user="List the people in this picture.", image_urls=[url], max_tokens=400)
        start = (answer or "").find("{")
        people = json.JSONDecoder().raw_decode(answer[start:])[0].get("people") if start >= 0 else None
        return [_person(p) for p in people] if isinstance(people, list) else None
    except Exception as e:  # noqa: BLE001
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[review] head count skipped: {type(e).__name__}: {str(e)[:160]}")
        return None


# A doll nobody held walked away down the path in its clip: a toy nobody touches in
# the start picture is frozen however much the clip moves it.
HELD_SYSTEM = ("You look at one storybook picture and a list of toys in it. For each toy, say whether a person is "
               "holding, hugging, carrying, riding or touching it with any part of their body. A toy only near "
               'someone, or alone on a seat, the floor or a shelf, is not held. Reply with JSON only: '
               '{"held": {"<toy as written>": true or false, ...}}')


async def toys_held(image: bytes, names: list[str]) -> dict[str, bool] | None:
    """name → whether someone touches that toy in the picture. None when the check can't run."""
    from services.ai import fake_providers, fal
    from services.ai.text_client import generate_vision

    if not names or fake_providers.enabled() or not await enabled():
        return None
    try:
        data, mime = await asyncio.to_thread(_shrink, image, 1024)
        url = await fal.upload(env_key="FAL_KEY_TEXT", data=data, content_type=mime, file_name="toys-held.jpg")
        answer = await generate_vision(stage="toy_freeze", model=REVIEW_MODEL, system=HELD_SYSTEM,
                                       user=json.dumps({"toys": names}, ensure_ascii=False), image_urls=[url],
                                       max_tokens=200)
        start = (answer or "").find("{")
        held = json.JSONDecoder().raw_decode(answer[start:])[0].get("held") if start >= 0 else None
        if not isinstance(held, dict):
            return None
        lowered = {str(k).strip().lower(): v for k, v in held.items()}
        return {n: lowered[n.strip().lower()] for n in names if isinstance(lowered.get(n.strip().lower()), bool)}
    except Exception as e:  # noqa: BLE001 — unknown: the toy is frozen only when it barely moves
        logger.warning(f"[review] held-toy check skipped: {type(e).__name__}: {str(e)[:160]}")
        return None


# Whether Wan brought a toy to life is asked on crops around the toy alone: in the whole
# frame a blink is a few pixels. A plush Wan had drawn right was frozen anyway, and the
# still patch around it showed against the moving plants behind.
ALIVE_SYSTEM = ("You see crops from one short cartoon clip, in time order from left to right, all around the same "
                "toy. Say whether the toy moves BY ITSELF like a living character: its eyes blink, close or look "
                "around, its mouth opens, its head turns or nods, an arm or a leg lifts or waves, it walks, or it "
                "changes shape. Being carried, hugged, squeezed or moved along by a person's hands or body is NOT "
                "moving by itself, and neither is a person moving next to it. "
                'Reply with JSON only: {"alive": true or false, "note": "a few words"}')


async def toy_alive(strip: bytes, name: str) -> dict | None:
    """{"alive", "note"} for one toy seen across a clip (`strip`: crops around it, in time order).
    None when the check can't run."""
    from services.ai import fake_providers, fal
    from services.ai.text_client import generate_vision

    if fake_providers.enabled() or not await enabled():
        return None
    try:
        data, mime = await asyncio.to_thread(_shrink, strip, 1600)
        url = await fal.upload(env_key="FAL_KEY_TEXT", data=data, content_type=mime, file_name="toy-alive.jpg")
        answer = await generate_vision(stage="toy_freeze", model=REVIEW_MODEL, system=ALIVE_SYSTEM,
                                       user=f"The toy: {name}.", image_urls=[url], max_tokens=120)
        start = (answer or "").find("{")
        verdict = json.JSONDecoder().raw_decode(answer[start:])[0] if start >= 0 else {}
        if not isinstance(verdict.get("alive"), bool):
            return None
        return {"alive": verdict["alive"], "note": str(verdict.get("note") or "")[:160]}
    except Exception as e:  # noqa: BLE001
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[review] toy-alive check skipped: {type(e).__name__}: {str(e)[:160]}")
        return None


def counted_extra(verdict: dict, people: list | None, expected: list[str]) -> dict:
    """More people listed than the shot's cast: an extra person, whatever the full review said.
    Fewer is left alone (a cast member can be off the edge, and an animal isn't listed)."""
    if people is None or len(people) <= len(expected):
        return verdict
    people = [_person(p) for p in people]
    problems = list(dict.fromkeys([*(verdict.get("problems") or []), "extra_person"]))
    note = f"head count: {len(people)} people for {len(expected)} — " + "; ".join(p["who"] for p in people)
    logger.warning(f"[review] keyframe {note[:300]}")
    return {**verdict, "ok": False, "problems": problems, "people_seen": len(people),
            "note": (note + (" | " + verdict["note"] if verdict.get("note") else ""))[:600]}


# GPT stood the friend where the child should be apart. Asked inside the full review,
# the model also called correct pictures "swapped" (its own note said the right child
# was in place). Listing everyone with their sheet first and then naming who does each
# part, with the comparison left to the code, got 11 of 12 test pictures right and never
# called a correct one swapped.
PARTS_SYSTEM = ("You check who does what in one storybook picture. The images are one reference sheet per name in "
                "`sheets` (in that order), then the picture. First list every person in the picture, left to right: "
                "what they look like (hair, hat or helmet color, top color), which sheet they match, and what they "
                "are doing and where. Then, for each character the `action` gives a part of their own (standing "
                "apart from the others, holding, hugging or riding a certain thing, being in a named place), say who "
                "in your list does that part. Reply with JSON only: "
                '{"people": [{"looks": "...", "sheet": "<name from sheets, or none>", "doing": "..."}], '
                '"parts": [{"character": "<name from the action>", "part": "<a few words>", '
                '"done_by": "<the sheet name of the person doing it, or none>"}]}')


def _sheet_name(label: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", label or "").strip().lower()


def _resolve(value, known: set[str]) -> str | None:
    """A cast member's sheet name, or None: an exact name, or a first name ("Sami's" → "sami")."""
    v = _sheet_name(str(value or ""))
    if v in known:
        return v
    first = re.sub(r"['’]s$", "", v.split(" ")[0]) if v else ""
    return first if first in known else None


def swapped_parts(parts: list | None, names: list[str]) -> list[dict]:
    """The parts done by another cast member than the one the action gives them to (both
    must be cast members by name: "none", a toy or a vague answer is never a swap)."""
    known = {_sheet_name(n) for n in names if _sheet_name(n)}

    def who(value) -> str | None:
        return _resolve(value, known)

    out = []
    for p in parts if isinstance(parts, list) else []:
        if isinstance(p, dict):
            owner, doer = who(p.get("character")), who(p.get("done_by"))
            if owner and doer and owner != doer:
                out.append(p)
    return out


async def who_does_what(image: bytes, sheets: list[tuple[str, bytes, str]], action: str) -> dict | None:
    """{"people": everyone left to right with their sheet, "parts": the action's parts and
    whose sheet the person doing each one matches}. None when the check can't run."""
    from services.ai import fake_providers, fal
    from services.ai.text_client import generate_vision

    if fake_providers.enabled() or len(sheets) < 2 or not await enabled():
        return None
    try:
        urls = []
        for i, (_label, data, _mime) in enumerate(sheets):
            small, mime = await asyncio.to_thread(_shrink, data)
            urls.append(await fal.upload(env_key="FAL_KEY_TEXT", data=small, content_type=mime, file_name=f"sheet-{i}.jpg"))
        small, mime = await asyncio.to_thread(_shrink, image, 1024)
        urls.append(await fal.upload(env_key="FAL_KEY_TEXT", data=small, content_type=mime, file_name="parts.jpg"))
        answer = await generate_vision(stage="keyframe_review", model=REVIEW_MODEL, system=PARTS_SYSTEM, image_urls=urls,
                                       user=json.dumps({"sheets": [_sheet_name(lb) for lb, _, _ in sheets],
                                                        "action": (action or "")[:600]}, ensure_ascii=False),
                                       max_tokens=900)
        start = (answer or "").find("{")
        found = json.JSONDecoder().raw_decode(answer[start:])[0] if start >= 0 else None
        return found if isinstance(found, dict) else None
    except Exception as e:  # noqa: BLE001
        if engine_health.is_balance_message(e):
            raise
        logger.warning(f"[review] who-does-what check skipped: {type(e).__name__}: {str(e)[:160]}")
        return None


def with_gaze(verdict: dict, people: list | None) -> dict:
    """Someone looking straight out at the viewer (owner: never in a story)."""
    at = [p["who"] for p in (_person(p) for p in people or []) if p["at_viewer"]]
    if not at:
        return verdict
    note = "looking at the viewer: " + "; ".join(at)
    logger.warning(f"[review] keyframe {note[:300]}")
    return {**verdict, "ok": False, "problems": list(dict.fromkeys([*(verdict.get("problems") or []), "camera_gaze"])),
            "note": (note + (" | " + verdict["note"] if verdict.get("note") else ""))[:600]}


def with_swaps(verdict: dict, parts: list | None, sheets: list[tuple[str, bytes, str]] | None) -> dict:
    swaps = swapped_parts(parts, [label for label, _, _ in sheets or []])
    if not swaps:
        return verdict
    note = "swapped: " + "; ".join(f"{p.get('character')}'s part ({p.get('part')}) is done by {p.get('done_by')}"
                                   for p in swaps)
    logger.warning(f"[review] keyframe {note[:300]}")
    return {**verdict, "ok": False, "problems": list(dict.fromkeys([*(verdict.get("problems") or []), "role_swap"])),
            "note": (note + (" | " + verdict["note"] if verdict.get("note") else ""))[:600]}


async def review_keyframe(shot_key: str, image: bytes, mime: str, expected: list[str], action: str,
                          sheets: list[tuple[str, bytes, str]] | None = None, objects: list[str] | None = None) -> dict:
    static = await asyncio.to_thread(static_verdict, [image])
    if static:
        return static
    verdict, people, found = await asyncio.gather(
        _ask("keyframe_review", shot_key, [(image, mime or "image/png")], expected, action, sheets, objects=objects),
        people_in(image) if expected else asyncio.sleep(0),
        who_does_what(image, sheets or [], action) if len(sheets or []) >= 2 else asyncio.sleep(0))
    # Nothing moves in one picture: the reviewer still flagged "object_alive" on keyframes
    # (three takes each, some without the toy in them at all), and called a child standing on
    # a ride-on toy "floating". The gaze is the head count's to say: the full review guessed
    # it. Colors inside the full review were noisy too (its own note said they matched), so a
    # friend's thing in the child's colors is prevented at the source instead (one reference
    # showing every owner's colors).
    noise = {"object_alive", "floating", "camera_gaze", "vanishing"}
    if set(verdict.get("problems") or []) & noise:
        problems = [p for p in verdict["problems"] if p not in noise]
        verdict = {**verdict, "problems": problems, "ok": not problems}
    parts = found if isinstance(found, list) else (found or {}).get("parts")
    return with_swaps(with_gaze(counted_extra(verdict, people, expected), people), parts, sheets)


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
    verdict = await _ask("clip_review", shot_key, [(f, "image/jpeg") for f in frames], expected, action, sheets,
                         first, objects)
    # The whole-clip question passed a clip where the father and the child turned to the
    # camera in its last second; asked person by person on the frames of its second half,
    # it was caught every time.
    late = await asyncio.gather(*(people_in(f) for f in frames[len(frames) // 2:]))
    return with_gaze(verdict, [p for found in late if found for p in found])
