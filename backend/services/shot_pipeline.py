"""Shot-based video engine (M2).

A scene is a run of short animated shots with one narration line each — the
look of the reference videos the owner approved:

  character sheets   child from the photo; the rest of the cast drawn from the plan
  scene_keyframes    per shot, a 16:9 first frame drawn with the sheets (and the
                     previous shot of the scene) as references — GPT Image 2, or
                     Qwen Image 2.1 on Comfy Cloud (each sheet its own <imageN>)
  narration          per scene, one Gemini take in the chosen dialect, split at
                     the pauses into one line per shot
  clips              per shot, a Kling clip (or Wan 2.2 on Comfy, Kling rescuing a
                     shot it can't do) at least as long as its line, so assembly
                     never holds a frame

Everything per shot lives in `shot_assets`; assembly is
video_assembly_service.assemble_shot_video.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone

from db import db
from models import get_order_output_type
from storage import APP_NAME, STORAGE_DIR, put_object
from services import (clip_review, engine_config, engine_health, face_fix, head_views, house_style,
                      pronunciation, toy_freeze)
from services.ai import AIConfigError, AIError, AIPermanentError, comfy, fal
from services.ai.image_client import WIDE, comfy_image, comfy_workflow
from services.child_character_service import _fetch_source_bytes
from services.config_service import get_pipeline_config, resolve_model, video_tier_of
from services.model_catalog import premium_video_model, video_model_for_tier
from services.image_generation_service import generate_image

logger = logging.getLogger("shot_pipeline")

CLIP_CONCURRENCY = 4
MAX_ELEMENTS = 3  # character sheets passed to Kling per shot
# Sheets a start frame is drawn with. With only three, a five-person shot drew
# the child's parents without theirs (the mother came out looking like the
# other mother in the scene).
MAX_KEYFRAME_SHEETS = 5
# Scratch space on the data drive (C: is small on dev machines).
WORK_ROOT = STORAGE_DIR / "tmp"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def work_dir(prefix: str) -> str:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    return tempfile.mkdtemp(prefix=prefix, dir=str(WORK_ROOT))


def has_shots(scenes: list[dict]) -> bool:
    return any(s.get("shots") for s in scenes)


async def _scenes(order: dict, plan: dict) -> list[dict]:
    return await db.scene_plans.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "is_archived": False}, {"_id": 0},
    ).sort("scene_index", 1).to_list(50)


async def _store(order: dict, kind: str, data: bytes, mime: str, ext: str) -> str:
    file_id = str(uuid.uuid4())
    path = f"{APP_NAME}/orders/{order['id']}/generated/{kind}/{file_id}.{ext}"
    stored = await asyncio.to_thread(put_object, path, data, mime)
    await db.files.insert_one({
        "id": file_id,
        "user_id": order.get("user_id"),
        "scope": f"generated-{kind}",
        "storage_path": stored.get("path", path),
        "original_filename": f"{kind}.{ext}",
        "content_type": mime,
        "size": stored.get("size", len(data)),
        "is_deleted": False,
        "created_at": _now(),
    })
    return f"/api/uploads/file/{file_id}"


async def _set_shot(order: dict, plan: dict, scene: dict, shot_index: int, patch: dict) -> None:
    await db.shot_assets.update_one(
        {"order_id": order["id"], "production_plan_id": plan["id"],
         "scene_index": scene["scene_index"], "shot_index": shot_index},
        {"$set": {**patch, "scene_plan_id": scene["id"], "updated_at": _now()},
         "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _now()}},
        upsert=True,
    )


async def shot_rows(order_id: str, plan_id: str) -> list[dict]:
    return await db.shot_assets.find(
        {"order_id": order_id, "production_plan_id": plan_id}, {"_id": 0},
    ).sort([("scene_index", 1), ("shot_index", 1)]).to_list(400)


# ---------------------------------------------------------------- cast & sheets
def _label(profile: dict, child_name: str) -> str:
    t = house_style.base_type(profile.get("type") or "character")
    if t == "child":
        return profile.get("name_en") or child_name or "the child"
    name = profile.get("name_en") or profile.get("name")
    return f"{name} (the child's {t})" if name else f"the child's {t}"


def _cast_line(profile: dict, child_name: str, from_photo: bool = False) -> str:
    """How a cast member is described in a shot prompt. When their sheet comes from a
    real photo the face/hair come from that sheet only (the plan's text description
    is the LLM's guess and could contradict the photo); the outfit still applies."""
    parts = [_label(profile, child_name)]
    if from_photo:
        parts.append("face, hair and build exactly as in their reference sheet")
    elif profile.get("visual_description"):
        parts.append(profile["visual_description"])
    clothes = (profile.get("clothing_style") or "").strip()
    if clothes and "photo" in clothes.lower():
        parts.append("wearing the same outfit as in their reference sheet")
    elif clothes and clothes.lower() not in ("not shown", "not shown."):
        parts.append(f"wearing {clothes}")
    return ", ".join(parts)


async def _profiles(plan: dict) -> dict[str, dict]:
    rows = await db.character_profiles.find({"production_plan_id": plan["id"]}, {"_id": 0}).to_list(30)
    by_type: dict[str, dict] = {}
    for p in rows:
        by_type.setdefault(p.get("type") or "other", p)
    return by_type


async def load_character_sheets(order: dict, plan: dict) -> dict[str, dict]:
    """type → {"url", "label"} for every cast member that already has a sheet."""
    child_name = ((order.get("data") or {}).get("child") or {}).get("name") or ""
    profiles = await _profiles(plan)
    sheets: dict[str, dict] = {}
    child = await db.child_character_assets.find_one(
        {"order_id": order["id"], "status": "completed", "generated_image_url": {"$ne": None}},
        {"_id": 0}, sort=[("created_at", -1)],
    )
    if child:
        sheets["child"] = {"url": child["generated_image_url"], "from_photo": True,
                           "head_views_url": child.get("head_views_url"), "photo_url": child.get("source_image_url"),
                           "label": _label(profiles.get("child") or {"type": "child"}, child_name)}
    keys = house_style.cast_keys((order.get("data") or {}).get("characters") or [])
    async for a in db.extra_character_assets.find(
        {"order_id": order["id"], "status": "completed", "generated_image_url": {"$ne": None}}, {"_id": 0},
    ):
        i = a.get("character_index")
        t = keys[i] if isinstance(i, int) and 0 <= i < len(keys) else a.get("character_type")
        if t and t not in sheets:
            sheets[t] = {"url": a["generated_image_url"], "from_photo": True,
                         "head_views_url": a.get("head_views_url"), "photo_url": a.get("source_image_url"),
                         "label": _label(profiles.get(t) or {"type": t}, child_name)}
    async for s in db.character_sheets.find({"order_id": order["id"], "production_plan_id": plan["id"]}, {"_id": 0}):
        sheets.setdefault(s["type"], {"url": s["image_url"], "label": s["label"]})
    return sheets


async def ensure_character_sheets(order: dict, plan: dict, photo_free_only: bool = False) -> dict[str, dict]:
    """Draw a reference sheet for every cast member who appears in a shot and has
    neither a photo-based character nor a sheet yet (e.g. the mother), so they
    look the same in every shot. A failed sheet only costs consistency.

    The sheets are drawn at the same time. With `photo_free_only` (the pass that
    runs alongside the photo-based sheets) cast members with a photo are left to
    their own stage; the later pass draws any of those that failed."""
    child_name = ((order.get("data") or {}).get("child") or {}).get("name") or ""
    scenes = await _scenes(order, plan)
    needed = {c for s in scenes for sh in s.get("shots") or [] for c in sh.get("characters") or []}
    profiles = await _profiles(plan)
    sheets = await load_character_sheets(order, plan)
    style = await engine_config.style_for_order(order)
    chars = (order.get("data") or {}).get("characters") or []
    with_photo = {k for k, c in zip(house_style.cast_keys(chars), chars)
                  if c.get("role") == "visible" and c.get("image_url")}
    todo = [t for t in sorted(needed - set(sheets)) if profiles.get(t) and t != "child"
            and not (photo_free_only and t in with_photo)]
    style_ref = await engine_config.style_reference_bytes(style) if todo else None

    async def draw(t: str) -> None:
        profile = profiles[t]
        label = _label(profile, child_name)
        prompt = (f"Character design for an animated children's story. Character: {_cast_line(profile, child_name)}. "
                  f"{profile.get('key_features') or ''} "
                  f"{house_style.STYLE_REF_NOTE if style_ref else ''} STYLE: {style['style_text']} "
                  f"COMPOSITION: {style['sheet_rules']}")
        try:
            img, mime, meta = await generate_image(
                scene_prompt=prompt, stage="extra_character_i2i", size=house_style.SHEET_SIZE, raw_prompt=True,
                references=[{"image_bytes": style_ref, "mime_type": "image/png"}] if style_ref else None,
                session_hint=f"sheet-{t}")
        except AIPermanentError:
            raise
        except Exception as e:  # noqa: BLE001 — shots still get drawn from the text description
            logger.warning(f"[shots] order={order['id']} sheet for {t} failed: {e}")
            return
        url = await _store(order, "character-sheet", img, mime, "png")
        await db.character_sheets.insert_one({
            "id": str(uuid.uuid4()), "order_id": order["id"], "production_plan_id": plan["id"],
            "type": t, "label": label, "image_url": url, "prompt_used": prompt,
            "model": meta.get("model"), "created_at": _now(),
        })
        sheets[t] = {"url": url, "label": label}

    results = await asyncio.gather(*(draw(t) for t in todo), return_exceptions=True)
    for res in results:
        if isinstance(res, AIPermanentError):
            raise res
    return sheets


# ---------------------------------------------------------------- prompt builders
# Shared by the executors and the admin prompt preview, so the preview shows
# exactly what the image and video models receive.
# Appended when the reviewer flagged a start frame or a clip.
REDRAW_NOTE = ("Draw every person exactly once, each fully separate from the others and looking exactly like their "
               "own reference sheet (face, hair, skin, clothes and colors), and no written words at all.")
# A clip redone because clothes changed mid-shot.
OUTFIT_REDO_NOTE = ("Nothing comes off or changes on anyone: every hat, cap, badge, bag and piece of clothing stays "
                    "exactly as in the first frame until the last frame.")
CALM_NOTE = "Calm, minimal motion: everyone stays where they are, nobody walks or jumps, the camera holds still."
# How bad a flagged frame is, to keep the least broken of several takes.
# A start frame with a held problem is never animated, so any take without one is the better take.
FLAW_WEIGHT = {"noise": 30, "deformed": 8, "melting": 3, "duplicate": 8, "extra_person": 8, "role_swap": 8,
               "wrong_look": 2, "vanishing": 2, "action_missing": 2, "mood_mismatch": 2, "object_alive": 2,
               "camera_gaze": 4, "floating": 4, "object_mixup": 3, "wrong_stage": 6}


def flaw(review: dict) -> int:
    return sum(FLAW_WEIGHT.get(p, 1) for p in review.get("problems") or []) or 1


# The reviewer called a redrawn cartoon face "wrong_look" on 7 of 9 keyframes of the
# fourth real story; three takes each never cleared it (the face comes from the same
# sheet every time), and a flagged start frame turned off the clip retakes for
# real problems. A likeness-only flag stays on the shot for the admin, nothing more.
SOFT_PROBLEMS = {"wrong_look"}
# Start frames a clip would only animate the mistake of (reliably seen by the
# review); the shot is held for a new picture instead.
HOLD_PROBLEMS = {"noise", "duplicate", "extra_person", "role_swap", "deformed"}


def held_problems(review: dict | None) -> list[str]:
    review = review or {}
    return [] if review.get("ok", True) else sorted(set(review.get("problems") or []) & HOLD_PROBLEMS)


# Pictures whose cast came out wrong go to GPT Image (owner, 2026-10-26): Qwen drew the
# same extra child on nine takes of one shot (the composition causes it), while a GPT
# take costs about six Qwen takes. Soft flaws stay on Qwen.
RESCUE_ENGINE = ("fal_image", "openai/gpt-image-2")
# What GPT is for: the people came out wrong. Static is a random glitch: drawn again as is.
CAST_PROBLEMS = HOLD_PROBLEMS - {"noise"}


def content_refused(e: Exception) -> bool:
    text = str(e).lower()
    return "flagged" in text or "content checker" in text or "content_policy" in text or "safety system" in text


def without_toy_names(text: str, objects: list[dict]) -> str:
    """The prompt with each toy's own name words as "toy" ("the big toy doll"): OpenAI's
    content checker refused a shot naming a famous character; its look and reference
    picture still say what it is."""
    words = set().union(*[_toy_words(o) for o in objects if o.get("toy")]) if objects else set()
    if not words:
        return text
    one = "(?:" + "|".join(map(re.escape, sorted(words))) + ")(?:['’]s)?"
    return re.sub(rf"\b{one}(?:\s+{one})*\b", "toy", text, flags=re.I)


def next_take(review: dict, engine: str, attempt: int, last: int = 3) -> str | None:
    """The engine of the next take of a Comfy keyframe after a failed one, or None to keep
    the best take: a wrong cast (extra, repeated or swapped people, a broken body) is
    redrawn with GPT, static is drawn again on the same engine, someone looking into the
    camera gets one more Qwen take (with GAZE_REDO) and then GPT (owner), a soft flaw gets
    one more Qwen take, and a GPT take with only soft flaws is kept."""
    problems = set(held_problems(review))
    if attempt >= last:
        return None
    if problems & CAST_PROBLEMS:
        return "gpt"
    if problems:
        return engine
    # A plant drawn in full bloom before it flowered came back four Qwen takes running
    # (its name said what it becomes): GPT follows the scene's words for the stage.
    if "wrong_stage" in (review.get("problems") or []):
        return "gpt" if engine == "qwen" else None
    if "camera_gaze" in (review.get("problems") or []):
        return "qwen" if engine == "qwen" and attempt < 2 else "gpt" if engine == "qwen" else None
    return "qwen" if engine == "qwen" and attempt < 2 else None


# A retake after someone looked into the camera says so before anything else.
GAZE_REDO = ("NOBODY LOOKS AT THE VIEWER: every face is turned toward someone or something inside the picture, the "
             "eyes clearly aimed to the side, down or at each other, never straight out of the picture.")


def redraw_note(review: dict | None) -> str:
    """What a retake adds to the prompt after a flagged take."""
    gaze = "camera_gaze" in ((review or {}).get("problems") or [])
    return f"{GAZE_REDO} {REDRAW_NOTE}" if gaze else REDRAW_NOTE


def passes(review: dict | None) -> bool:
    """The review found nothing worth another take."""
    review = review or {}
    return bool(review.get("ok", True)) or not (set(review.get("problems") or []) - SOFT_PROBLEMS)
PREV_SHOT_NOTE = "the previous shot of this scene — keep the same place, furniture, lighting and outfits"
PREV_SCENE_NOTE = ("the last shot of the previous scene — if the story is still in the same place, keep the "
                   "same room design and furniture (lighting may change)")


# Image and video models misspell any word they draw (a map once read "Costa
# Rria"), so pictures carry no writing at all.
NO_TEXT = ("No written words, letters, numbers or signs anywhere in the picture: maps, signs, books and screens "
           "show drawings only.")


def keyframe_prompt(scene: dict, sh: dict, profiles: dict, sheets: dict, child_name: str,
                    notes: list[str], style: dict, objects: list[dict] | None = None,
                    sheet_types: list[str] | None = None) -> str:
    """`sheet_types`: whose sheets come first among the reference images, in order (their
    names in the scene then point at their picture); None marks the face picture that
    follows a sheet."""
    cast = "; ".join(_cast_line(profiles[t], child_name, bool((sheets.get(t) or {}).get("from_photo")))
                     for t in sh.get("characters") or [] if t in profiles)
    return " ".join(p for p in [
        tag_cast(sh.get("keyframe_prompt") or scene.get("visual_description") or "",
                 [{"kind": "sheet", "type": t} if t else {"kind": "faces"} for t in sheet_types or []], profiles,
                 child_name,
                 "reference image {n}"),
        f"Shot type: {sh.get('shot_type') or 'medium'}.",
        f"Setting: {scene['background_setting']}." if scene.get("background_setting") else "",
        f"Characters, matching their reference sheets exactly: {cast}." if cast else "",
        GAZE if cast else "",
        objects_line(objects or []),
        ("Reference images, in order: " + "; ".join(f"{i + 1}) {n}" for i, n in enumerate(notes)) + ".")
        if notes else "",
        f"Art style: {style['style_text']}",
        style["frame_rules"],
        NO_TEXT,
    ] if p)


# Comfy keyframes (Qwen Image 2.1 Edit): the template from the bake-off
# (comfy_workflows/README.md). Each reference is its own <imageN>, identity
# comes first, and there is no style image and no generic face words: the style
# image's own characters leaked into scenes, and "big eyes, small noses" pulled
# every face toward a stock cartoon face.
COMFY_INTRO = ("Create a brand-new 16:9 children's storybook illustration using the people and objects from the "
               "reference images (a new scene, not an edit of <image1>).")
# The face is copied, the expression is not: "copy the mouth and smile" kept a
# crying child smiling like his sheet in the first real story. The head size is said
# on its own: a wide shot gave the father and the son bobbleheads (owner: silly).
COMFY_COPY = ("Copy each character's identity from their reference exactly: the same face shape, eyes, eyebrows, "
              "nose, skin tone and age; the same hairstyle with the same hair volume, curls and hairline; the same "
              "beard shape and fullness; plus the same clothes, shoes and colors. Every head keeps its real size "
              "against its body for the person's age, never enlarged. Do not redesign, beautify or simplify the "
              "faces. Facial expressions, gaze and poses follow the SCENE below, not the reference sheets.")
COMFY_ONCE = "Each character appears exactly once and nobody else is in the picture."
# The sheets face the viewer, and whoever the scene doesn't give a gaze kept it:
# the parents clapped while staring into the camera. Eyes alone weren't enough: a
# father and son watching the view stood square to us like a photo (twice), and a
# face turned to us reads as looking at us once Wan moves it.
GAZE = ("Everyone looks at someone or something inside the picture, as the SCENE says; nobody looks out at the "
        "viewer or the camera. Heads and bodies turn toward what they look at, seen in three-quarter view or from "
        "the side, never posed square to the viewer like a photo.")
COMFY_NOBODY = "There are no people in this picture."
COMFY_STYLE = ("STYLE: exactly the same 2D cartoon storybook art style, line quality and shading as the reference "
               "sheets; premium picture-book rendering with soft painterly shading, a gentle visible brush texture, "
               "warm golden rim light along the characters' edges, and warm saturated colors.")
COMFY_FRAME = "Full-bleed 16:9 frame filling the whole canvas edge to edge: no border, no white margin, no vignette."
COVER_TITLE_SPACE = ("Leave calm sky or background space in the upper part of the frame for the book title "
                     "(the title is added later — don't write it).")
# A thing the story keeps coming back to (a block tower, a kite, a cake) was
# redrawn from two words in every shot: Lego-like in one, thin wooden blocks in
# the next, and the "bigger" rebuilt tower came out shorter. The plan fixes its
# look once (story_objects, sizes measured on the characters' bodies in each
# shot), and on Comfy one reference picture of it is drawn before the keyframes.
MAX_SHOT_OBJECTS = 2
# The reference's arrangement leaked: a toppled tower kept a stack standing among
# the scattered blocks. Changing objects get loose parts as their reference.
OBJECTS_NOTE = "not its arrangement: how many pieces, how big and how they are arranged follow the SCENE"
# Words a plan uses for a toy; the parent's own name for it counts too.
TOY_WORDS = ("toy", "toys", "plush", "plushie", "stuffed animal", "teddy", "doll", "figurine", "action figure")


async def keyframe_engine() -> tuple[str, str]:
    """(provider, model) the shot keyframes and the cover are drawn with."""
    provider, model, _src = await resolve_model("scene_image_generation", "", "")
    return provider, model


def favourite_toy(order: dict) -> dict | None:
    """The parent's photo of the child's favourite toy, what they call it and how
    the photo was described (the plan names the toy from that description)."""
    pers = (order.get("data") or {}).get("personalization") or {}
    if not pers.get("toy_image_url"):
        return None
    return {"url": pers["toy_image_url"],
            "name": str((((pers.get("favorites") or {}).get("toy") or {}).get("name") or "")).strip(),
            "description": str(pers.get("toy_description_auto") or "")}


def _mentions(text: str, term: str) -> bool:
    return bool(term) and re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", (text or "").lower()) is not None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{4,}", (text or "").lower())}


def toy_named_in(text: str, toy: dict, key_objects: list | None = None) -> str | None:
    """How `text` names the toy, or None. The plan lists the toy among the scene's
    key_objects (a toy word, the parent's name for it, or two words of the photo's
    description); a shot shows it when its prompt uses one of those, the parent's
    name, or a toy word."""
    name, described = toy.get("name") or "", _words(toy.get("description"))
    objects = [str(o) for o in key_objects or []
               if _mentions(str(o), name) or any(_mentions(str(o), w) for w in TOY_WORDS)
               or len(_words(str(o)) & described) >= 2]
    return next((t for t in [name, *objects, *TOY_WORDS] if _mentions(text, t)), None)


def _toy_ref(toy: dict, named: str) -> dict:
    return {"kind": "toy", "name": toy.get("name") or (named if named not in TOY_WORDS else "") or "favourite toy"}


def story_objects(plan: dict, toy: dict | None = None) -> dict[str, dict]:
    """key → {"key", "name", "look", "sheet_view"}: the plan's recurring objects,
    without the child's toy (its photo is its reference)."""
    out = {}
    for o in plan.get("story_objects") or []:
        if not (o.get("key") and o.get("name_en") and o.get("look")):
            continue
        if toy and toy_named_in(f"{o['name_en']} {o['look']}", toy):
            continue
        out[o["key"]] = {"key": o["key"], "name": o["name_en"], "look": o["look"], "sheet_view": o.get("sheet_view") or "",
                         "toy": bool(o.get("toy")), "changes": bool(o.get("changes")),
                         "owners": list(o.get("owners") or [])}
    return out


# A plush of a famous cartoon came out as the character itself (standing on its own,
# blinking in the clip); "flat stitched eyes, limp" then made a cheap plush nobody
# recognised. The owner: the famous design exactly, made as its plush, still a toy.
TOY_NOTE = ("It is a toy, not alive: if it is a known character, it has that character's famous design exactly "
            "(the same face, eye shape and colors, hair or quills, outfit and colors) made as its official plush or "
            "figure from a toy shop, in its toy material (soft plush fabric with seams, or molded plastic)")
TOY_POSE = "it sits upright like a stuffed toy or is held; it never stands, walks or poses by itself"


# Words that don't single a toy out: what every toy or size shares.
_PLAIN_WORDS = {"doll", "toy", "toys", "plush", "plushie", "stuffed", "soft", "figure", "figurine", "big", "small",
                "little", "tiny", "large", "official", "classic", "famous", "with", "the"}


def _toy_words(obj: dict) -> set[str]:
    """What names a toy in a prompt ("captain", "comet" for "the big Captain Comet doll"): its
    name only (a key can carry the owner, "x_teddy"), not its owner ("X's"), not a word any
    toy or size shares."""
    words = re.findall(r"[a-z]+(?:['’]s)?", obj["name"].lower())
    return {w for w in words if len(w) >= 4 and not w.endswith(("'s", "’s")) and w not in _PLAIN_WORDS}


def shot_objects(sh: dict, objects: dict[str, dict], scene: dict | None = None) -> list[dict]:
    """The shot's story objects: the plan's list, plus a toy its words or its scene's setting
    name. The setting put a doll "visible in the distance" in a shot that didn't list it:
    drawn with none of the toy rules, it rode a toy vehicle. Such a toy is `background`: its
    rules, freeze and review apply, but its reference picture doesn't go in (Qwen drew the
    doll big in the foreground, wearing the child's helmet). Toys come first under the cap."""
    listed = [k for k in dict.fromkeys(sh.get("objects") or []) if k in objects]
    said = set(re.findall(r"[a-z]+", f"{sh.get('keyframe_prompt') or ''} "
                                     f"{(scene or {}).get('background_setting') or ''}".lower()))
    named = [k for k, o in objects.items() if o.get("toy") and k not in listed and _toy_words(o) & said]
    keys = sorted(listed + named, key=lambda k: not objects[k].get("toy"))
    cast = set(sh.get("characters") or [])
    out = []
    for k in keys:
        o = objects[k]
        if k in named:
            o = {**o, "background": True}
        # A set's picture shows every owner's one side by side; with an owner missing, Qwen
        # still laid them all out in a row (five cans around one child): words only then.
        elif o.get("owners") and not set(o["owners"]) <= cast:
            o = {**o, "partial": True}
        out.append(o)
    return out[:MAX_SHOT_OBJECTS]


def without_picture(o: dict) -> bool:
    """A shot object whose reference picture stays out of that shot."""
    return bool(o.get("background") or o.get("partial"))


BACKGROUND_NOTE = "only small and far in the background, sitting still, never in front of anyone"
CHANGES_NOTE = ("it changes during the story: draw it exactly as the SCENE describes it in this picture, never a "
                "later stage")


def object_brief(obj: dict) -> str:
    """A story object for the review: its name and the start of its look (its colors, so a
    friend's thing painted in the child's colors is seen)."""
    look = (obj.get("look") or "").strip().rstrip(".")
    return f"{obj['name']} ({look[:160]})" if look else obj["name"]


def objects_line(objects: list[dict]) -> str:
    """The fixed look of the shot's story objects, word for word in every shot."""
    # A set some of whose owners aren't in the shot is left to the scene's own words: its look
    # lists every owner's one, and the three cans were drawn around one child.
    objects = [o for o in objects if not o.get("partial")]
    if not objects:
        return ""
    return ("OBJECTS (they look exactly the same in every picture of this story): "
            + "; ".join(f"{o['name']}: {o['look'].rstrip('.')}" + (f" ({TOY_NOTE}; {TOY_POSE})" if o.get("toy") else "")
                        + (f" ({BACKGROUND_NOTE})" if o.get("background") else "")
                        + (f" ({CHANGES_NOTE})" if o.get("changes") else "") for o in objects)
            + f" — {OBJECTS_NOTE}. Things that belong to different people keep each owner's own colors as written.")


# The last frame of every clip (owner, 2026-10-28). Given only its first frame, Wan ended
# shot after shot on faces turned to the camera (six takes of one shot running, whatever
# the prompt said), changed faces and woke toys. Each shot now also gets its end picture:
# the start picture a moment later (a Qwen edit of it), checked like any picture, and Wan
# only moves between the two (comfy_workflows/clip_wan22_flf_api.json). One more Qwen
# picture a shot (~2 cents); on the test shot nobody looked at the camera in any frame.
END_FRAME = ("<image1> is a picture from a children's storybook. Draw exactly the same picture a moment later, at "
             "the end of this action: {action} Everything else stays exactly the same: {who}, every object, the "
             "background, the light, the camera and the framing. Everyone keeps looking where they look in "
             "<image1>; nobody looks at the viewer. No text.")
END_FRAME_TAKES = 2
CLIP_PINNED = "clip_wan22_flf"


async def pin_last_frame_on() -> bool:
    s = await db.settings.find_one({"key": "comfy.pin_last_frame"}, {"_id": 0, "value": 1})
    return (s or {}).get("value", True) is not False


def end_frame_prompt(sh: dict) -> str:
    n = len(set(sh.get("characters") or []))
    who = ("the same person in the same place and pose, with the same face, hair, clothes and colors" if n == 1 else
           f"the same {n} people in the same places and poses, with the same faces, hair, clothes and colors" if n
           else "nobody appears")
    action = re.sub(r"\s+", " ", sh.get("motion_prompt") or "").strip() or "a calm, small change of expression."
    return END_FRAME.format(action=action if action.endswith(".") else f"{action}.", who=who)


async def draw_end_frame(order: dict, sh: dict, start: bytes, model: str, queue_key: str, fix=None) -> dict:
    """The shot's end picture, checked (static, head count, nobody at the camera): the
    fields for its row. Without one after END_FRAME_TAKES the clip runs from its start
    picture alone, as before — this never blocks a story. `fix(data, mime)` gives a
    grown-up from a photo their face back (the edit redraws the whole picture)."""
    n = len(set(sh.get("characters") or []))
    gpu, problems = 0.0, []
    for _take in range(END_FRAME_TAKES):
        try:
            data, mime, meta = await comfy_image(stage="end_frame", model=model, prompt=end_frame_prompt(sh),
                                                 references=[start], queue_key=queue_key)
        except AIConfigError:
            raise
        except Exception as e:  # noqa: BLE001
            problems = [f"error: {type(e).__name__}"]
            continue
        gpu += float(meta.get("gpu_seconds") or 0)
        problems = ["noise"] if clip_review.static_verdict([data]) else []
        people = await clip_review.people_in(data)
        if people is not None:
            if len(people) != n:
                problems.append("people_count")
            if any(p.get("at_viewer") for p in people):
                problems.append("camera_gaze")
        if not problems:
            face_gpu = 0.0
            if fix:
                data, mime, face_gpu, _who = await fix(data, mime)
            url = await _store(order, "keyframe_end", data, mime, "png")
            return {"end_keyframe_url": url, "end_frame_review": {"ok": True}, "end_frame_gpu_seconds": gpu,
                    "end_face_gpu_seconds": face_gpu}
    return {"end_keyframe_url": None, "end_frame_review": {"ok": False, "problems": problems},
            "end_frame_gpu_seconds": gpu}


def story_order(scene: dict, shot: dict) -> str:
    """Where a shot sits in the story, as a queue key that sorts in story order."""
    return f"{int(scene.get('scene_index') or 0):03d}.{int(shot.get('shot_index') or 0):03d}"


# The Qwen workflow needs an input picture. A cast sheet as the style sample put the
# child on the object in three references running: a blank page carries no one.
OBJECT_STYLE = ("STYLE: a 2D cartoon children's storybook illustration with clean confident outlines, soft painterly "
                "shading, a gentle visible brush texture and warm saturated colors.")


def blank_canvas() -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (1536, 864), (250, 243, 228)).save(out, "PNG")
    return out.getvalue()


def object_sheet_prompt(obj: dict) -> str:
    """A story object alone, drawn once as its reference (<image1> = a blank page)."""
    return "\n".join(p for p in [
        "Create a brand-new 16:9 children's storybook illustration on <image1>, which is an empty page.",
        # The name leads to the finished thing ("the block tower" got a tower drawn
        # over "loose cubes"), so the reference view, when given, comes alone.
        f"SUBJECT, as a clear reference picture: {obj['sheet_view'].rstrip('.')}. Look: {obj['look'].rstrip('.')}."
        if obj.get("sheet_view") else
        f"SUBJECT: {obj['name']} alone, as a clear reference picture: {obj['look'].rstrip('.')}.",
        f"{TOY_NOTE}. It sits upright on the floor like a stuffed toy, facing forward." if obj.get("toy") else "",
        "Centered, whole and large in the frame on a plain soft cream background with a light shadow under it. "
        "No people, no hands, nothing else.",
        OBJECT_STYLE,
        NO_TEXT,
    ] if p)


_object_locks: dict[str, asyncio.Lock] = {}


async def load_object_sheets(order: dict, plan: dict) -> dict[str, dict]:
    """key → {"url", "name"} for the story objects already drawn."""
    return {s["key"]: {"url": s["image_url"], "name": s["name"]}
            async for s in db.object_sheets.find({"order_id": order["id"], "production_plan_id": plan["id"],
                                                  "image_url": {"$ne": None}},
                                                 {"_id": 0, "key": 1, "image_url": 1, "name": 1})}


async def ensure_object_sheets(order: dict, plan: dict) -> dict[str, dict]:
    """Draw a reference picture of every story object a shot shows, once per plan
    (Comfy keyframes only: a few cents each). Scenes drawn at the same time wait
    for the first one; a failed picture only costs consistency (the shots still
    get the fixed look in words)."""
    if (await keyframe_engine())[0] != "comfy_image":
        return {}
    objects = story_objects(plan, favourite_toy(order))
    used = {o["key"] for s in await _scenes(order, plan) for sh in s.get("shots") or []
            for o in shot_objects(sh, objects, s) if not without_picture(o)}
    lock = _object_locks.setdefault(plan["id"], asyncio.Lock())
    async with lock:
        drawn = await load_object_sheets(order, plan)
        failed = {s["key"] async for s in db.object_sheets.find(
            {"order_id": order["id"], "production_plan_id": plan["id"], "failed": True}, {"_id": 0, "key": 1})}
        todo = [objects[k] for k in sorted(used) if k in objects and k not in drawn and k not in failed]
        if not todo:
            return drawn
        canvas = blank_canvas()
        _provider, model = await keyframe_engine()
        from services.clip_review import shows_person, static_verdict

        async def draw(obj: dict) -> None:
            prompt, gpu = object_sheet_prompt(obj), 0.0
            try:
                # Qwen sometimes returns coloured static, and once drew the style
                # sample's child on the object: a person here would be drawn twice.
                for _take in range(3):
                    img, mime, meta = await comfy_image(stage="scene_image_generation", model=model, prompt=prompt,
                                                        references=[canvas], queue_key="000")
                    gpu += meta.get("gpu_seconds") or 0
                    if not await asyncio.to_thread(static_verdict, [img]) and not await shows_person(img):
                        break
                else:
                    raise AIError(f"the reference of {obj['name']} came out as static or with a person three times")
            except AIPermanentError:
                raise
            except Exception as e:  # noqa: BLE001 — the shots still get the look in words
                logger.warning(f"[shots] order={order['id']} object sheet {obj['key']} failed: {e}")
                if gpu:  # paid all the same
                    await db.object_sheets.insert_one({
                        "id": str(uuid.uuid4()), "order_id": order["id"], "production_plan_id": plan["id"],
                        "key": obj["key"], "name": obj["name"], "image_url": None, "model": model,
                        "gpu_seconds": gpu, "failed": True, "created_at": _now()})
                return
            url = await _store(order, "object-sheet", img, mime, "png")
            await db.object_sheets.insert_one({
                "id": str(uuid.uuid4()), "order_id": order["id"], "production_plan_id": plan["id"],
                "key": obj["key"], "name": obj["name"], "image_url": url, "prompt_used": prompt,
                "model": model, "gpu_seconds": gpu, "created_at": _now()})
            drawn[obj["key"]] = {"url": url, "name": obj["name"]}

        results = await asyncio.gather(*(draw(o) for o in todo), return_exceptions=True)
        for res in results:
            if isinstance(res, AIPermanentError):
                raise res
        return drawn


def comfy_references(sh: dict, scene: dict, sheets: dict, toy: dict | None, previous: str | None,
                     objects: list[dict] | None = None) -> list[dict]:
    """What each <imageN> of a Comfy keyframe is, in order: the cast's sheets (the
    family first), the child's toy when the shot shows it, and the reference of
    each story object it shows (`objects`, those drawn). The previous frame
    (`previous` = "shot", "scene" or None) only goes with a shot that has nobody
    in it: Qwen copies the people it sees there too, and the first real story got
    the child twice (once from his sheet, once from the previous shot). A shot
    with nobody, no toy and no earlier frame gets one sheet as a style reference."""
    refs = [{"kind": "sheet", "type": t} for t in by_likeness(sh.get("characters") or [], sheets)[:MAX_KEYFRAME_SHEETS]]
    named = toy_named_in(sh.get("keyframe_prompt") or "", toy, scene.get("key_objects")) if toy else None
    if named:
        refs.append(_toy_ref(toy, named))
    refs += [{"kind": "object", "key": o["key"], "name": o["name"], "toy": bool(o.get("toy"))} for o in objects or []]
    if previous and not sh.get("characters"):
        refs.append({"kind": f"prev_{previous}"})
    if not refs and sheets:
        refs.append({"kind": "style", "type": by_likeness(sorted(sheets), sheets)[0]})
    # A grown-up's face from three sides right after their sheet, while there's room
    # (services/head_views.py). Children keep their sheet alone: with a face square for
    # the child too, Qwen drew him twice in three of four sample scenes, the copy with
    # the father's beard; their likeness was already right from the sheet.
    for t in [r["type"] for r in refs if r["kind"] == "sheet" and house_style.is_adult(r["type"])
              and (sheets.get(r["type"]) or {}).get("head_views_url")]:
        if len(refs) >= comfy.MAX_REFS:
            break
        at = next(i for i, r in enumerate(refs) if r["kind"] == "sheet" and r["type"] == t)
        refs.insert(at + 1, {"kind": "faces", "type": t})
    return refs


# Feelings belong to the scene, not to a character's permanent look.
_EXPRESSION = re.compile(r"\b(smil\w*|grin\w*|laugh\w*|frown\w*|cry\w*|tear\w*|happy|sad|angry|cheerful|joyful|"
                         r"expression\w*|pout\w*|mood)\b", re.I)


def _features(profile: dict) -> str:
    raw = profile.get("key_features") or ""
    text = ", ".join(map(str, raw)) if isinstance(raw, list) else str(raw)
    parts = [p.strip() for p in re.split(r"[,;]", re.sub(r"\s+", " ", text)) if p.strip()]
    return ", ".join(p for p in parts if not _EXPRESSION.search(p)).strip(" .,;")[:200]


FROM_PHOTO_FACE = "copy the face, hairline, hair texture and any beard exactly as drawn in the reference"
FACES_COPY = "copy the face, hairline, hair and any beard exactly from it"
# With a bearded father's face close-ups in the references, the child got stubble.
CHILD_FACE = "a child's smooth face with no beard, moustache or stubble"
CHILD_TYPES = {"child", "friend", "brother", "sister", "sibling", "cousin"}


def comfy_identity(refs: list[dict], profiles: dict, sheets: dict) -> str:
    parts = []
    faces_at = {r["type"]: n for n, r in enumerate(refs, 1) if r["kind"] == "faces"}
    for n, r in enumerate(refs, 1):
        tag, kind = f"<image{n}>", r["kind"]
        if kind == "sheet":
            # Someone drawn from a real photo keeps the face their sheet has, not the plan's
            # guess at it: "neatly trimmed beard, closely cropped hair" gave the father a
            # barber's fade and a sculpted beard his sheet never had.
            if r["type"] in faces_at:
                note = f"their full figure and clothes; their face is <image{faces_at[r['type']]}>"
            elif (sheets.get(r["type"]) or {}).get("from_photo"):
                note = FROM_PHOTO_FACE
            else:
                features = _features(profiles.get(r["type"]) or {})
                note = f"keep {features} exactly as in the reference" if features else ""
            if faces_at and house_style.base_type(r["type"]) in CHILD_TYPES:
                note = f"{note}; {CHILD_FACE}" if note else CHILD_FACE
            parts.append(f"{tag} is {sheets[r['type']]['label']}" + (f" ({note})" if note else ""))
        elif kind == "faces":
            label = sheets[r["type"]]["label"]
            parts.append(f"{tag} is {label}'s face from the front, three-quarter and side, close up: {FACES_COPY}; "
                         f"these faces are {label}'s alone, nobody else takes anything from them")
        elif kind == "toy":
            parts.append(f"{tag} shows only the child's {r['name']} (ignore any hands or background around it)")
        elif kind == "object":
            # A plush's red shoes ended up on the friend's feet: the object's look is its own.
            parts.append(f"{tag} shows only {r['name']}: copy its material, shape and colors exactly, {OBJECTS_NOTE}; "
                         "its colors and parts belong to it alone, people keep their own clothes and shoes"
                         + (f"; it is a lifeless toy: {TOY_POSE}" if r.get("toy") else ""))
        elif kind == "prev_shot":
            parts.append(f"{tag} is the previous shot of this scene: keep the same place, furniture and lighting, "
                         "and take the people from their own references")
        elif kind == "prev_scene":
            parts.append(f"{tag} is the last shot of the previous scene: if the story is still in the same place, "
                         "keep the same place and furniture; take the people from their own references")
        elif kind == "style":
            parts.append(f"{tag} shows the art style only: the character in it is not in this picture")
    return "IDENTITY (most important): " + ", ".join(parts) + "." if parts else ""


def _name(profile: dict, child_name: str) -> str | None:
    """A cast member's own name as the plan's English prompts write it (None for "the dog")."""
    if house_style.base_type(profile.get("type") or "") == "child":
        return profile.get("name_en") or child_name or None
    return profile.get("name_en") or profile.get("name") or None


def comfy_once(cast: list[str], profiles: dict, child_name: str) -> str:
    """The head count in words. With one friend standing apart, the sheets were lined up
    side by side and a fourth child was drawn for the one apart (twice in a row)."""
    names = [_name(profiles.get(t) or {"type": t}, child_name) or f"the child's {house_style.base_type(t)}"
             for t in cast]
    who = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    count = f"exactly one character ({who})" if len(names) == 1 else f"exactly {len(names)} characters ({who})"
    return (f"The picture shows {count}: each appears exactly once and nobody else is in it, no extra children "
            "or adults even in the background.")


def tag_cast(text: str, refs: list[dict], profiles: dict, child_name: str, tag: str = "<image{n}>") -> str:
    """Each named character's first mention in the SCENE points at their reference
    (a name -> "<name> (<image1>)"): Qwen ties an action to a picture by its tag, not by a
    name it only met in the IDENTITY line. GPT put a friend in the child's place the same
    way when the references were only listed at the end of its prompt."""
    for n, r in enumerate(refs, 1):
        if r["kind"] != "sheet":
            continue
        name = _name(profiles.get(r["type"]) or {"type": r["type"]}, child_name)
        if name:
            text = re.sub(rf"\b{re.escape(name)}\b(?!['’]s\b)", lambda m: f"{m.group(0)} ({tag.format(n=n)})", text,
                          count=1)
    return text


def keyframe_prompt_comfy(scene: dict, sh: dict, profiles: dict, sheets: dict, child_name: str,
                          refs: list[dict], objects: list[dict] | None = None) -> str:
    """The README template, filled from the plan, the profiles and the sheets;
    `objects` = the shot's story objects (their fixed look goes in words)."""
    cast = list(dict.fromkeys(sh.get("characters") or []))
    with_ref = {r["type"] for r in refs if r["kind"] == "sheet"}
    without = [_cast_line(profiles[t], child_name) for t in cast if t not in with_ref and t in profiles]
    shot_type = sh.get("shot_type") or "medium"
    article = "an" if shot_type[:1].lower() in "aeiou" else "a"
    return "\n".join(p for p in [
        COMFY_INTRO,
        comfy_identity(refs, profiles, sheets),
        COMFY_COPY if with_ref else "",
        f"Also in the picture, without a reference image: {'; '.join(without)}." if without else "",
        comfy_once(cast, profiles, child_name) if cast else COMFY_NOBODY,
        " ".join(p for p in [
            f"SCENE: {article} {shot_type} shot, with the {'characters' if cast else 'main subject'} "
            "large in the frame.",
            tag_cast(sh.get("keyframe_prompt") or scene.get("visual_description") or "", refs, profiles, child_name),
            f"Setting: {scene['background_setting']}." if scene.get("background_setting") else "",
        ] if p),
        objects_line(objects or []),
        GAZE if cast else "",
        COMFY_STYLE,
        COMFY_FRAME,
        NO_TEXT,
    ] if p)


def cover_prompt_comfy(plan: dict, profiles: dict, sheets: dict, refs: list[dict]) -> str:
    idea = plan.get("cover_prompt") or f"A warm storybook cover scene for “{plan.get('title', '')}”."
    people = any(r["kind"] == "sheet" for r in refs)
    return "\n".join(p for p in [
        COMFY_INTRO,
        comfy_identity(refs, profiles, sheets),
        COMFY_COPY if people else "",
        COMFY_ONCE if people else "",
        f"SCENE: a storybook cover, with the {'characters' if people else 'main subject'} large in the frame. {idea}",
        COVER_TITLE_SPACE,
        COMFY_STYLE,
        COMFY_FRAME,
        NO_TEXT,
    ] if p)


def describe_refs(refs: list[dict], sheets: dict) -> list[str]:
    """The <imageN> list in words, for the admin."""
    words = {"toy": "the child's toy", "prev_shot": "the previous shot", "prev_scene": "the previous scene's last shot"}
    return [f"<image{n}> " + (sheets[r["type"]]["label"] + ("'s sheet (style only)" if r["kind"] == "style" else
                                                         "'s face from three sides" if r["kind"] == "faces" else "'s sheet")
                               if r["kind"] in ("sheet", "style", "faces") else
                               f"{r['name']}'s reference" if r["kind"] == "object" else words[r["kind"]])
            for n, r in enumerate(refs, 1)]


# Kling invented a second father when a shot's camera arc "revealed" the room,
# and walked the child through a rope railing in a shot that packed five
# actions. Every clip now says who is in it and that bodies stay solid.
OUTFIT_LOCK = ("Everyone keeps exactly the clothes and accessories they wear in the first frame (hats, caps, "
               "badges, glasses, bags) for the whole shot; the character references are for faces only.")
PHYSICS = ("Bodies stay solid: nobody passes through railings, ropes, furniture, walls or each other, and nobody "
           "floats.")
CLIP_NEGATIVE_GUARD = ("duplicate person, cloned character, twins, extra people, person appearing from nowhere, "
                       "body passing through objects, clipping, merged bodies, floating, character vanishing")


def by_likeness(types: list[str], sheets: dict) -> list[str]:
    """Cast members with a sheet, the ones the family will recognise first: the
    child, then relatives drawn from their photos, then everyone else."""
    have = [t for t in dict.fromkeys(types) if t in sheets]
    return sorted(have, key=lambda t: (t != "child", not (sheets[t] or {}).get("from_photo"), have.index(t)))


def cast_labels(types: list[str], sheets: dict) -> list[str]:
    return [sheets[t]["label"] if t in sheets else ("the child" if t == "child" else f"the child's {t}")
            for t in types]


def cast_lock(labels: list[str]) -> str:
    if not labels:
        return "Nobody new enters the frame and no one is duplicated."
    n = len(labels)
    return (f"Exactly {n} {'person' if n == 1 else 'people'} in this shot — {'; '.join(labels)} — each appearing "
            "only once and all already in the first frame: nobody new enters and no one is duplicated. "
            f"{OUTFIT_LOCK}")


def clip_negative(style: dict) -> str:
    return f"{style['negative_text']}, {CLIP_NEGATIVE_GUARD}"


# Wan at CFG 1 follows a short prompt with the action first; what must NOT move goes
# in words (a negative prompt does nothing there). The long Kling guards buried the
# action, ambient motion made hair fly indoors, camera moves stretched objects.
WAN_STILL = ("Static camera, no zoom or pan. Nothing else moves: objects stay where they are, same shape, size and "
             "colors. Feet stay on the ground or deck; nobody rises or floats. No wind: hair and clothes hang still.")


def who_is_who(motion: str, cast_in_frame: list[dict] | None) -> str:
    """The video model sees the picture, not the names: "Sami bounces" moved another child.
    Each name's first mention says how that person looks (from their own sheet)."""
    for c in cast_in_frame or []:
        name, where = c.get("name") or "", c.get("where") or ""
        looks = re.sub(r"\s+\S*$", "", (c.get("looks") or "")[:110]) if len(c.get("looks") or "") > 110 else             (c.get("looks") or "")
        looks = looks.strip(" ,.")
        desc = ", ".join(p for p in (f"the one {where}" if where else "", looks) if p)
        if name and desc:
            motion = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)(?!['’]s)", lambda m: f"{m.group(0)} ({desc})", motion,
                            count=1, flags=re.I)
    return motion


# A plush with a face is a character to a video model: a cartoon-hero plush raised its
# arms and opened its mouth when the boys cheered.
def lifeless(objects: list[str] | None, toys: list[str] | None = None) -> str:
    # Said positively: "never blinks" still let a doll sitting alone close its eyes.
    toy_text = " ".join(f"{t[:1].upper()}{t[1:]} is a toy frozen like a statue: its eyes stay wide open and fixed, the "
                        "same face in every frame."
                        for t in dict.fromkeys(toys or []))
    if not objects:
        return toy_text
    names = list(dict.fromkeys(objects))
    text = " and ".join(names)
    one = len(names) == 1
    return " ".join(p for p in [
        f"{text[:1].upper()}{text[1:]} {'is a lifeless object' if one else 'are lifeless objects'}: never moving, "
        f"waving, blinking or opening a mouth by {'itself' if one else 'themselves'}, only moved by a hand.",
        toy_text] if p)


def wan_motion_prompt(motion: str | None, people: int, calm: bool = False, outfit: bool = False,
                      objects: list[str] | None = None, toys: list[str] | None = None,
                      cast_in_frame: list[dict] | None = None) -> str:
    who = "Nobody is in the frame." if not people else (
        f"Exactly {people} {'person' if people == 1 else 'people'}, all already in the frame; nobody appears, leaves "
        "or is duplicated, bodies stay solid, and nobody turns to look at the camera.")
    # Right after the action: Wan weighs the first sentences most, and the plush
    # still cheered along when the line came after the stillness guards.
    return " ".join(p for p in [
        who_is_who(motion or "A small natural movement of the main character.", cast_in_frame),
        lifeless(objects, toys),
        CALM_NOTE if calm else "",
        OUTFIT_REDO_NOTE if outfit else "",
        WAN_STILL,
        who,
        "2D storybook cartoon, no written words.",
    ] if p)


def motion_prompt(motion: str | None, mapping: list[str], style: dict, cast: list[str] | None = None,
                  objects: list[str] | None = None, toys: list[str] | None = None,
                  cast_in_frame: list[dict] | None = None) -> str:
    return " ".join(p for p in [
        who_is_who(motion or "Gentle natural character motion and a slow camera push-in.", cast_in_frame),
        ("Characters: " + "; ".join(mapping) + ".") if mapping else "",
        cast_lock(cast or []),
        lifeless(objects, toys),
        "Nobody turns to look at the camera." if cast else "",
        PHYSICS,
        style["motion_text"],
        NO_TEXT,
    ] if p)


async def cover_request(order: dict, plan: dict) -> tuple[str, list[dict], list[str]]:
    """The cover (also the video thumbnail) is drawn like a keyframe of the whole
    cast: every character sheet rides along as a reference, so relatives look
    like their photos instead of being invented from the cover text.
    Returns (prompt, references, cast types)."""
    child_name = ((order.get("data") or {}).get("child") or {}).get("name") or ""
    sheets = await load_character_sheets(order, plan)
    profiles = await _profiles(plan)
    style = await engine_config.style_for_order(order)
    cast_types = by_likeness(sorted(sheets), sheets)[:MAX_KEYFRAME_SHEETS]
    if (await keyframe_engine())[0] == "comfy_image":
        # Same path as the keyframes: each sheet its own <imageN>, the toy when
        # the cover idea shows it, no style image.
        toy = favourite_toy(order)
        named = toy_named_in(plan.get("cover_prompt") or "", toy) if toy else None
        wanted = [{"kind": "sheet", "type": t} for t in cast_types] + ([_toy_ref(toy, named)] if named else [])
        kept, refs = [], []
        for r in wanted:
            got = await _fetch_source_bytes(sheets[r["type"]]["url"] if r["kind"] == "sheet" else toy["url"])
            if got:
                kept.append(r)
                refs.append({"image_bytes": got[0], "mime_type": got[1]})
        return cover_prompt_comfy(plan, profiles, sheets, kept), refs, cast_types
    refs, notes = [], []
    for t in cast_types:
        got = await _fetch_source_bytes(sheets[t]["url"])
        if got:
            refs.append({"image_bytes": got[0], "mime_type": got[1]})
            notes.append(f"{sheets[t]['label']}'s character sheet")
    cast = "; ".join(_cast_line(profiles[t], child_name, bool(sheets[t].get("from_photo")))
                     for t in cast_types if t in profiles)
    idea = plan.get("cover_prompt") or f"A warm storybook cover scene for “{plan.get('title', '')}”."
    prompt = " ".join(p for p in [
        "Storybook cover illustration.",
        idea,
        f"Characters, matching their reference sheets exactly: {cast}." if cast else "",
        ("Reference images, in order: " + "; ".join(f"{i + 1}) {n}" for i, n in enumerate(notes)) + ". "
         "Draw every character exactly like their sheet (face, hair, beard, glasses, clothes, colors); "
         "where the scene description says otherwise, the sheet wins.") if notes else "",
        "Leave calm sky or background space in the upper part of the frame for the book title "
        "(the title is added later — don't write it).",
        NO_TEXT,
        f"Art style: {style['style_text']}",
        style["frame_rules"],
    ] if p)
    return prompt, refs, cast_types


# ---------------------------------------------------------------- keyframes
async def execute_scene_keyframes(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    """Draw the scene's shot keyframes in order (each sees the previous one). A
    retry resumes after the last finished shot."""
    scene = await db.scene_plans.find_one({"id": job["target_id"]}, {"_id": 0})
    if not scene or not scene.get("shots"):
        raise ValueError(f"scene_plan {job['target_id']} has no shots")
    child_name = ((order.get("data") or {}).get("child") or {}).get("name") or ""
    sheets = await load_character_sheets(order, plan)
    profiles = await _profiles(plan)
    style = await engine_config.style_for_order(order)
    sheet_bytes: dict[str, tuple[bytes, str]] = {}
    prev: tuple[bytes, str] | None = None
    # The first shot of a scene sees the previous scene's last shot, so a story
    # that stays in one room keeps the same room.
    last_of_previous = await db.shot_assets.find_one(
        {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"] - 1,
         "keyframe_url": {"$ne": None}}, {"_id": 0, "keyframe_url": 1}, sort=[("shot_index", -1)])
    previous_scene = await _fetch_source_bytes(last_of_previous["keyframe_url"]) if last_of_previous else None
    hero_url = None
    model = None
    provider, comfy_model = await keyframe_engine()
    on_comfy = provider == "comfy_image"
    pin = on_comfy and await pin_last_frame_on()

    async def end_frame_for(sh: dict, start: bytes) -> None:
        fields = await draw_end_frame(order, sh, start, comfy_model, story_order(scene, sh), fix=lambda d, m: (
            face_fix.fix_faces(order, sh, d, m, sheets, story_order(scene, sh))))
        gpu = fields.get("end_frame_gpu_seconds") or 0
        face_gpu = fields.pop("end_face_gpu_seconds", 0) or 0
        await _set_shot(order, plan, scene, sh["shot_index"], fields)
        if gpu or face_gpu:
            await db.shot_assets.update_one(
                {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"],
                 "shot_index": sh["shot_index"]}, {"$inc": {"comfy_gpu_seconds": gpu + face_gpu,
                                                            "end_frames_gpu_seconds": gpu,
                                                            "face_fix_gpu_seconds": face_gpu}})
    toy = favourite_toy(order) if on_comfy else None
    toy_bytes: tuple[bytes, str] | None = None
    uploads: dict = {}  # Comfy names of the images already sent in this run
    objects = story_objects(plan, toy)
    object_refs = await ensure_object_sheets(order, plan) if objects and on_comfy else {}
    object_bytes: dict[str, tuple[bytes, str] | None] = {}

    async def sheet_data(t: str) -> tuple[bytes, str] | None:
        if t not in sheet_bytes:
            got = await _fetch_source_bytes(sheets[t]["url"])
            if got:
                sheet_bytes[t] = got
        return sheet_bytes.get(t)

    faces_bytes: dict[str, tuple[bytes, str] | None] = {}

    async def faces_data(t: str) -> tuple[bytes, str] | None:
        """A person's face from three sides, laid out on a square (services/head_views.py)."""
        if t not in faces_bytes:
            heads = await _fetch_source_bytes(sheets[t]["head_views_url"]) if sheets[t].get("head_views_url") else None
            faces_bytes[t] = (head_views.grid(heads[0]), "image/png") if heads else None
        return faces_bytes[t]

    looks_seen: dict[str, str | None] = {}

    async def look_of(t: str) -> str | None:
        """How to pick this cast member out of a group picture, asked once per sheet and kept."""
        url = sheets[t]["url"]
        if url not in looks_seen:
            doc = await db.sheet_looks.find_one({"url": url}, {"_id": 0, "look": 1})
            look = (doc or {}).get("look")
            if not look and await sheet_data(t):
                look = await clip_review.sheet_look(sheet_bytes[t][0])
                if look:
                    await db.sheet_looks.update_one({"url": url}, {"$set": {"url": url, "look": look,
                                                                            "created_at": _now()}}, upsert=True)
            looks_seen[url] = look
        return looks_seen[url]

    async def who_is_where(sh: dict) -> list[dict]:
        types = [t for t in dict.fromkeys(sh.get("characters") or []) if t in sheets]
        if len(types) < 2:
            return []
        looks = {}
        for t in types:
            look = await look_of(t)
            if look:
                looks[re.sub(r"\s*\(.*\)\s*$", "", sheets[t]["label"]).strip()] = look
        return clip_review.placed(looks)

    async def gpt_inputs(sh: dict, in_shot: list[dict], extra: list[tuple]) -> tuple[list[dict], str, list[str]]:
        """References, prompt and reference notes for a GPT Image draw of the shot; `extra`
        = (picture, note) of the toy and story objects a rescued Comfy shot had."""
        refs, notes, types = [], [], []
        for t in by_likeness(sh.get("characters") or [], sheets)[:MAX_KEYFRAME_SHEETS]:
            if await sheet_data(t):
                refs.append({"image_bytes": sheet_bytes[t][0], "mime_type": sheet_bytes[t][1]})
                notes.append(f"{sheets[t]['label']}'s character sheet (full figure and clothes)")
                types.append(t)
                faces = await faces_data(t) if house_style.is_adult(t) else None
                if faces:
                    refs.append({"image_bytes": faces[0], "mime_type": faces[1]})
                    notes.append(f"{sheets[t]['label']}'s face from the front, three-quarter and side ({FACES_COPY}; "
                                 "nobody else takes anything from it)")
                    types.append(None)  # keeps the next sheet's "(reference image N)" right
        for data, note in extra:
            refs.append({"image_bytes": data[0], "mime_type": data[1]})
            notes.append(note)
        if prev:
            refs.append({"image_bytes": prev[0], "mime_type": prev[1]})
            notes.append(PREV_SHOT_NOTE)
        elif previous_scene:
            refs.append({"image_bytes": previous_scene[0], "mime_type": previous_scene[1]})
            notes.append(PREV_SCENE_NOTE)
        return refs, keyframe_prompt(scene, sh, profiles, sheets, child_name, notes, style, in_shot, types), notes

    for sh in scene["shots"]:
        row = await db.shot_assets.find_one(
            {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"],
             "shot_index": sh["shot_index"]},
            {"_id": 0, "keyframe_url": 1, "keyframe_prompt_id": 1, "keyframe_prompt_attempt": 1,
             "keyframe_counted_id": 1, "end_keyframe_url": 1, "end_frame_review": 1}) or {}
        if row.get("keyframe_url"):
            prev = await _fetch_source_bytes(row["keyframe_url"])
            hero_url = hero_url or row["keyframe_url"]
            if pin and prev and not row.get("end_keyframe_url") and not row.get("end_frame_review"):
                await end_frame_for(sh, prev[0])
            continue
        refs, notes, comfy_refs, extra_refs = [], [], [], []
        in_shot = shot_objects(sh, objects, scene)
        if on_comfy:
            for r in comfy_references(sh, scene, sheets, toy, "shot" if prev else "scene" if previous_scene else None,
                                      [o for o in in_shot if o["key"] in object_refs and not without_picture(o)]):
                if r["kind"] in ("sheet", "style"):
                    data = await sheet_data(r["type"])
                elif r["kind"] == "faces":
                    data = await faces_data(r["type"])
                elif r["kind"] == "toy":
                    toy_bytes = toy_bytes or await _fetch_source_bytes(toy["url"])
                    data = toy_bytes
                elif r["kind"] == "object":
                    if r["key"] not in object_bytes:
                        object_bytes[r["key"]] = await _fetch_source_bytes(object_refs[r["key"]]["url"])
                    data = object_bytes[r["key"]]
                else:
                    data = prev if r["kind"] == "prev_shot" else previous_scene
                if data:
                    comfy_refs.append(r)
                    refs.append({"image_bytes": data[0], "mime_type": data[1]})
                    if r["kind"] in ("toy", "object"):
                        extra_refs.append((data, f"the child's {r['name']} (its look only)" if r["kind"] == "toy" else
                                           f"{r['name']}'s reference picture (its look only, {OBJECTS_NOTE})"))
            prompt = keyframe_prompt_comfy(scene, sh, profiles, sheets, child_name, comfy_refs, in_shot)
        else:
            refs, prompt, notes = await gpt_inputs(sh, in_shot, [])
        shot_key = f"{scene['scene_index']}_{sh['shot_index']}"
        cast = cast_labels(sh.get("characters") or [], sheets)
        # A Comfy job submitted before a restart is waited on, not paid for again.
        resume_id = row.get("keyframe_prompt_id") if on_comfy else None
        first = (row.get("keyframe_prompt_attempt") or 1) if resume_id else 1
        # Qwen takes cost ~3 cents; a soft flaw gets one more, a wrong cast goes to GPT
        # (see next_take). Then the least broken take is kept (Qwen once returned pure
        # noise on a redraw).
        best = chosen = rescue = last_review = None
        engine = "qwen" if on_comfy else "stage"
        # GPT refused a shot naming a famous toy ("content flagged") and the whole shot
        # failed: a refused or failed GPT take is drawn on Qwen instead, and GPT isn't asked again.
        gpt_ok = True
        for attempt in range(first, (3 if on_comfy else 2) + 1):
            resumed = False
            if engine == "gpt":
                rescue = rescue or await gpt_inputs(sh, in_shot, extra_refs)
                take_refs, used, used_notes = rescue
                for scrubbed in (False, True):
                    try:
                        img, mime, meta = await generate_image(
                            scene_prompt=used if attempt == 1 else f"{used} {redraw_note(last_review)}",
                            references=take_refs or None, stage="scene_image_generation", size=WIDE,
                            raw_prompt=True, session_hint=f"shot-{shot_key}-{order['id'][:6]}-{attempt}",
                            engine=RESCUE_ENGINE)
                        used_refs = [f"{n}) {note}" for n, note in enumerate(used_notes, 1)]
                        break
                    except Exception as e:  # noqa: BLE001 — this take goes back to Qwen...
                        if engine_health.is_balance_message(e):
                            raise  # ...unless the balance ran out: the order pauses
                        # A famous toy's name got the prompt refused: once more without the names.
                        if not scrubbed and content_refused(e) and without_toy_names(used, in_shot) != used:
                            used = without_toy_names(used, in_shot)
                            rescue = (take_refs, used, used_notes)
                            continue
                        logger.warning(f"[shots] {shot_key}: GPT take failed, drawing on Qwen: "
                                       f"{type(e).__name__}: {str(e)[:160]}")
                        gpt_ok, engine = False, "qwen"
                        break
            if engine == "qwen":
                text = prompt if attempt == 1 else f"{prompt} {redraw_note(last_review)}"

                async def submitted(prompt_id: str, attempt: int = attempt) -> None:
                    await _set_shot(order, plan, scene, sh["shot_index"],
                                    {"keyframe_prompt_id": prompt_id, "keyframe_prompt_attempt": attempt})

                try:
                    img, mime, meta = await comfy_image(
                        stage="scene_image_generation", model=comfy_model, prompt=text,
                        references=[r["image_bytes"] for r in refs], upload_cache=uploads,
                        prompt_id=resume_id, on_submitted=submitted, queue_key=story_order(scene, sh))
                except Exception as e:
                    if getattr(e, "gpu_seconds", None):  # a failed job's GPU time is billed too
                        await db.shot_assets.update_one(
                            {"order_id": order["id"], "production_plan_id": plan["id"],
                             "scene_index": scene["scene_index"], "shot_index": sh["shot_index"]},
                            {"$inc": {"comfy_gpu_seconds": e.gpu_seconds, "keyframe_gpu_seconds": e.gpu_seconds}})
                    raise
                resumed, resume_id = bool(resume_id), None
                used, used_refs = prompt, describe_refs(comfy_refs, sheets)
            elif engine == "stage":
                img, mime, meta = await generate_image(
                    scene_prompt=prompt if attempt == 1 else f"{prompt} {REDRAW_NOTE}", references=refs or None,
                    stage="scene_image_generation", size=WIDE, raw_prompt=True,
                    session_hint=f"shot-{shot_key}-{order['id'][:6]}-{attempt}",
                )
                used, used_refs = prompt, None
            # A start frame with a cloned person or written words would be
            # animated as is: redraw it once (an image is cheaper than a clip).
            paid = {"paid_keyframes": 1}
            if meta.get("gpu_seconds"):
                paid.update(comfy_gpu_seconds=meta["gpu_seconds"], keyframe_gpu_seconds=meta["gpu_seconds"])
            if engine == "gpt":
                paid["paid_rescue_keyframes"] = 1
            # A job resumed after its review paused the order (empty balance) was counted then.
            if not (resumed and row.get("keyframe_counted_id") == meta.get("prompt_id")):
                await db.shot_assets.update_one(
                    {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"],
                     "shot_index": sh["shot_index"]},
                    {"$inc": paid, "$set": {"keyframe_counted_id": meta.get("prompt_id"),
                                            **({"rescue_model": RESCUE_ENGINE[1]} if engine == "gpt" else {})},
                     "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _now()}},
                    upsert=True)
            review = await clip_review.review_keyframe(
                shot_key, img, mime, cast, sh.get("keyframe_prompt") or "",
                [(sheets[t]["label"], *sheet_bytes[t]) for t in by_likeness(sh.get("characters") or [], sheets)
                 [:MAX_KEYFRAME_SHEETS] if t in sheet_bytes], [object_brief(o) for o in in_shot])
            review["redrawn"] = attempt >= 2
            if engine == "gpt":
                review["rescue"] = RESCUE_ENGINE[1]
            take = (img, mime, meta, review, used, used_refs)
            last_review = review
            if passes(review):
                chosen = take
                break
            if best is None or flaw(review) < flaw(best[3]):
                best = take
            if on_comfy:
                engine = next_take(review, engine, attempt)
                if engine is None:
                    break
                if engine == "gpt" and not gpt_ok:
                    engine = "qwen"
        img, mime, meta, review, used, used_refs = chosen or best
        if "noise" in (review.get("problems") or []):
            # Static on every take: a visible failure beats a broken frame in the story.
            await _set_shot(order, plan, scene, sh["shot_index"], {"keyframe_prompt_id": None,
                                                                    "keyframe_prompt_attempt": None})
            raise AIError(f"shot {shot_key}: every keyframe take came out as coloured static")
        faced: list[str] = []
        if on_comfy:
            # A grown-up drawn from a photo gets the parent's own face back (services/face_fix.py).
            img, mime, face_gpu, faced = await face_fix.fix_faces(order, sh, img, mime, sheets, story_order(scene, sh))
            if face_gpu:
                await db.shot_assets.update_one(
                    {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"],
                     "shot_index": sh["shot_index"]}, {"$inc": {"comfy_gpu_seconds": face_gpu,
                                                                "face_fix_gpu_seconds": face_gpu}})
        url = await _store(order, "keyframe", img, mime, "png")
        model = meta.get("model")
        await _set_shot(order, plan, scene, sh["shot_index"], {
            "keyframe_url": url, "keyframe_at": _now(), "keyframe_prompt_used": used, "image_model": model,
            "keyframe_review": review, "faces_fixed": faced,
            "narration_line": sh["narration_line"], "shot_type": sh.get("shot_type"),
            "characters": sh.get("characters") or [], "motion_prompt": sh.get("motion_prompt") or "",
            "style_key": style.get("key"), "style_version": style.get("version"),
            "keyframe_prompt_id": None, "keyframe_prompt_attempt": None,
            "keyframe_refs": used_refs,
            "keyframe_seed": meta.get("seed"),
            "objects": [o["name"] for o in in_shot],
            "toys": [o["name"] for o in in_shot if o.get("toy")],
            "cast_in_frame": await who_is_where(sh),
            "end_keyframe_url": None, "end_frame_review": None,
        })
        prev = (img, mime)
        hero_url = hero_url or url
        if pin:
            await end_frame_for(sh, img)

    # The first shot stands for the scene in the PDF book and the storyboard.
    await db.scene_images.delete_many({"order_id": order["id"], "production_plan_id": plan["id"],
                                       "kind": "scene", "scene_index": scene["scene_index"]})
    await db.scene_images.insert_one({
        "id": str(uuid.uuid4()), "order_id": order["id"], "production_plan_id": plan["id"],
        "scene_plan_id": scene["id"], "generation_job_id": job["id"], "kind": "scene",
        "scene_index": scene["scene_index"], "image_url": hero_url, "provider": "ai", "source_type": "ai",
        "shot_count": len(scene["shots"]), "created_at": _now(),
    })
    return hero_url, {"provider": "ai", "model": model, "shots": len(scene["shots"])}


# ---------------------------------------------------------------- narration
def _probe_seconds(path: str) -> float:
    from services.video_assembly_service import _ffmpeg_bin

    res = subprocess.run([_ffmpeg_bin(), "-i", path], capture_output=True, text=True, timeout=30)
    m = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", res.stderr or "")
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def _quietest(wav: bytes, start: float, end: float, step: float = 0.01) -> float:
    """The quietest moment of a pause: its middle held the breath before the next line, and
    the piece ended on a cut-off breath. The middle when the take isn't plain PCM."""
    import io
    import wave

    import numpy as np

    try:
        with wave.open(io.BytesIO(wav)) as w:
            sr, width, ch = w.getframerate(), w.getsampwidth(), w.getnchannels()
            w.setpos(int(start * sr))
            raw = w.readframes(int((end - start) * sr))
        if width != 2:
            raise ValueError("not 16-bit")
        a = np.frombuffer(raw, dtype="<i2").astype(float).reshape(-1, ch).mean(axis=1)
        k = max(1, int(step * sr))
        frames = len(a) // k
        if frames < 3:
            raise ValueError("too short")
        energy = (a[: frames * k].reshape(frames, k) ** 2).mean(axis=1)
        return start + (int(energy[1:-1].argmin()) + 1.5) * step
    except Exception:  # noqa: BLE001
        return (start + end) / 2


def _split_take(wav: bytes, lines: list[str], words_per_second: float = house_style.WORDS_PER_SECOND) -> list[bytes] | None:
    """Cut one narration take into one clip per line at its longest pauses.
    Returns None when the pauses don't line up with the lines (caller re-voices
    line by line instead)."""
    from services.video_assembly_service import _ffmpeg_bin

    if len(lines) == 1:
        return [wav]
    ff = _ffmpeg_bin()
    d = work_dir("narr-")
    try:
        src = os.path.join(d, "take.wav")
        with open(src, "wb") as f:
            f.write(wav)
        total = _probe_seconds(src)
        log = subprocess.run([ff, "-hide_banner", "-i", src, "-af", "silencedetect=noise=-35dB:d=0.25",
                              "-f", "null", "-"], capture_output=True, text=True, timeout=60).stderr
        starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", log)]
        ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", log)]
        gaps = [(e - s, s, e) for s, e in zip(starts, ends) if 0.3 < s and e < total - 0.2]
        if len(gaps) < len(lines) - 1:
            return None
        cuts = sorted(_quietest(wav, s, e) for _, s, e in sorted(gaps, reverse=True)[: len(lines) - 1])
        bounds = [0.0, *cuts, total]
        out = []
        for i, line in enumerate(lines):
            seg_len = bounds[i + 1] - bounds[i]
            expected = max(1.0, len(line.split()) / words_per_second)
            if not 0.35 <= seg_len / expected <= 2.6:
                return None
            dst = os.path.join(d, f"line{i}.wav")
            # The cut comes first, inside the filter: as output options -ss/-to counted the
            # time after the take's leading silence was removed, so every cut slid by that
            # silence and the next line's first sound ended the previous piece (the owner
            # heard the voice break at second 5).
            trim = (f"atrim=start={bounds[i]:.3f}:end={bounds[i + 1]:.3f},asetpts=PTS-STARTPTS,"
                    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-45dB,areverse")
            subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-af", trim, dst],
                           check=True, timeout=60)
            with open(dst, "rb") as f:
                out.append(f.read())
        return out
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _plausible(seconds: float, words: int, words_per_second: float = house_style.WORDS_PER_SECOND) -> bool:
    """Spoken length a child-paced narrator could produce for `words` words."""
    expected = words / words_per_second
    return expected * 0.35 <= seconds <= expected * 2.0 + 1.5


async def _seconds_of(data: bytes, ext: str) -> float:
    d = work_dir("dur-")
    try:
        p = os.path.join(d, f"a.{ext}")
        with open(p, "wb") as f:
            f.write(data)
        return round(await asyncio.to_thread(_probe_seconds, p), 3)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# The plan writes how each scene should sound ("bright and playful, a lively lift on the
# shout"), but the voice only ever got the dialect's one fixed line: the owner heard the
# right words with the wrong feeling. Through fal the direction is a field of its own, so
# the scene's few sentences go along; direct Gemini reads its direction aloud when it is
# long, so it keeps the short line.
SCENE_DIRECTION_CHARS = 260


def scene_direction(base: str, voice_prompt: str | None) -> str:
    mood = re.sub(r"\s+", " ", (voice_prompt or "")).strip()
    if not mood:
        return base
    if len(mood) > SCENE_DIRECTION_CHARS:
        mood = mood[:SCENE_DIRECTION_CHARS].rsplit(". ", 1)[0].rstrip(".") + "."
    return f"{base.rstrip(' :')}. In this scene: {mood}"


async def execute_scene_narration(job: dict, order: dict, plan: dict) -> tuple[str, dict]:
    """Voice a shot scene: one Gemini take for the whole scene (natural flow),
    split into one clip per shot line; other providers voice line by line."""
    from services.ai import AIError
    from services.tts_service import (GEMINI_TTS_MODELS, _resolve_narration_provider, generate_tts,
                                      narration_voice_for_order, synthesize_gemini, synthesize_gemini_fal)

    scene = await db.scene_plans.find_one({"id": job["target_id"]}, {"_id": 0})
    shots = (scene or {}).get("shots") or []
    if not shots:
        raise ValueError(f"scene_plan {job['target_id']} has no shots")
    lines = [sh["narration_line"] for sh in shots]
    voiced = {r["shot_index"]: r for r in await db.shot_assets.find(
        {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"],
         "narration_url": {"$ne": None}}, {"_id": 0, "shot_index": 1, "narration_url": 1,
                                           "narration_line": 1}).to_list(50)}
    if all((voiced.get(sh["shot_index"]) or {}).get("narration_line") == sh["narration_line"] for sh in shots):
        take = await db.narration_assets.find_one({"order_id": order["id"], "production_plan_id": plan["id"],
                                                   "scene_index": scene["scene_index"]}, {"_id": 0})
        return ((take or {}).get("audio_url") or voiced[shots[0]["shot_index"]]["narration_url"],
                {"provider": (take or {}).get("provider"), "model": (take or {}).get("model"), "reused": True})
    provider, model = await _resolve_narration_provider()
    dialect = await engine_config.get_dialect(await house_style.dialect_for_order(order))
    dialect_key = dialect["key"]
    wps = (await engine_config.get_pacing())["words_per_second"]

    take_url = None
    meta: dict = {"provider": provider, "model": model, "dialect": dialect_key}
    # The voice reads the lines with the words it could misread marked; everyone else sees them plain.
    said = await pronunciation.spoken(lines, dialect.get("name_ar") or dialect_key)
    if said != lines:
        meta["spoken_lines"] = said
    if provider in ("gemini_tts", "fal_gemini_tts"):
        voice = dialect["voices"][await house_style.narrator_for_order(order)]
        via_fal = provider == "fal_gemini_tts"
        # Direct Gemini falls back across models; through fal, a fresh take of the same model.
        candidates = [model] * 3 if via_fal else [model, *[x for x in GEMINI_TTS_MODELS if x != model]][:3]

        async def voice_text(text: str) -> tuple[bytes, dict]:
            # A take far longer than its words means the model also spoke the
            # direction or ad-libbed: retry, never deliver it.
            words = len(text.split())
            tried = []
            for m in candidates:
                if via_fal:
                    w, gmeta = await synthesize_gemini_fal(text, voice, scene_direction(dialect["tts_direction"],
                                                                                         scene.get("voice_prompt")),
                                                           m, dialect_key)
                else:
                    w, gmeta = await synthesize_gemini(text, voice, dialect["tts_direction"], m)
                secs = await _seconds_of(w, "wav")
                if _plausible(secs, words, wps):
                    return w, gmeta
                tried.append(f"{gmeta.get('model')}={secs:.1f}s")
                logger.warning(f"[shots] implausible narration ({secs:.1f}s for {words} words) from {gmeta.get('model')}")
            raise AIError(f"narration for {words} words came out implausibly long/short ({', '.join(tried)})")

        wav, gmeta = await voice_text("\n".join(said))
        meta.update(gmeta)
        take_url = await _store(order, "narration", wav, "audio/wav", "wav")
        pieces = await asyncio.to_thread(_split_take, wav, lines, wps)
        if pieces is None:
            logger.warning(f"[shots] scene {scene['scene_index']}: take didn't split cleanly; voicing line by line")
            pieces = [(await voice_text(line))[0] for line in said]
            meta["split"] = "per_line"
        else:
            meta["split"] = "one_take"
        segments = [(p, "audio/wav", "wav") for p in pieces]
    else:
        voice = await narration_voice_for_order(order)
        segments = []
        for line in said:
            audio, mime, tmeta = await generate_tts(text=line, voice=voice, language="ar")
            meta.update({k: tmeta.get(k) for k in ("provider", "model") if tmeta.get(k)})
            segments.append((audio, mime, "mp3" if "mpeg" in (mime or "") else "wav"))
    meta["voice"] = voice

    total = 0.0
    first_url = None
    for sh, (data, mime, ext) in zip(shots, segments):
        secs = await _seconds_of(data, ext)
        url = await _store(order, "narration-line", data, mime, ext)
        first_url = first_url or url
        await _set_shot(order, plan, scene, sh["shot_index"], {
            "narration_url": url, "narration_seconds": secs, "narration_line": sh["narration_line"],
        })
        total += secs
    await db.narration_assets.delete_many({"order_id": order["id"], "production_plan_id": plan["id"],
                                           "scene_index": scene["scene_index"]})
    await db.narration_assets.insert_one({
        "id": str(uuid.uuid4()), "order_id": order["id"], "production_plan_id": plan["id"],
        "scene_plan_id": scene["id"], "generation_job_id": job["id"], "scene_index": scene["scene_index"],
        "text": " ".join(lines), "voice_type": voice, "dialect": dialect_key, "language": "ar",
        "audio_url": take_url or first_url, "duration_seconds": round(total, 2),
        "provider": meta.get("provider"), "model": meta.get("model"), "split": meta.get("split"),
        "created_at": _now(),
    })
    return take_url or first_url, meta


async def story_seconds(order_id: str, plan_id: str) -> float:
    """Length of the assembled story: every line plus its gap, plus the end tail."""
    rows = await shot_rows(order_id, plan_id)
    if not rows:
        return 0.0
    pacing = await engine_config.get_pacing()
    return sum((r.get("narration_seconds") or 0) + pacing["line_gap_sec"] for r in rows) + pacing["end_tail_sec"]


# ---------------------------------------------------------------- clips
async def _clip_arguments(row: dict, model: str, sheets: dict, sheet_urls: dict, tail: float = 0.0,
                          style: dict | None = None, pacing: dict | None = None, calm: bool = False,
                          outfit: bool = False) -> dict:
    style = style or engine_config.DEFAULT_STYLE
    pacing = pacing or engine_config.DEFAULT_PACING
    img = await _fetch_source_bytes(row["keyframe_url"])
    if not img:
        raise ValueError(f"keyframe for shot {row['scene_index']}.{row['shot_index']} is missing")
    start_url = await fal.upload(env_key="FAL_KEY_VIDEO", data=img[0], content_type=img[1] or "image/png",
                                 file_name=f"shot{row['scene_index']}-{row['shot_index']}.png")
    v3 = "/v3/" in model
    elements, mapping = [], []
    if v3:
        for t in by_likeness(row.get("characters") or [], sheets)[:MAX_ELEMENTS]:
            if t not in sheet_urls:
                got = await _fetch_source_bytes(sheets[t]["url"])
                if not got:
                    continue
                sheet_urls[t] = await fal.upload(env_key="FAL_KEY_VIDEO", data=got[0], content_type=got[1] or "image/png",
                                                 file_name=f"sheet-{t}.png")
            elements.append({"frontal_image_url": sheet_urls[t], "reference_image_urls": [sheet_urls[t]]})
            mapping.append(f"{sheets[t]['label']} is @Element{len(elements)}")
    cast = cast_labels(row.get("characters") or [], sheets)
    prompt = motion_prompt(row.get("motion_prompt"), mapping, style, cast, row.get("objects"), row.get("toys"),
                           row.get("cast_in_frame"))
    if calm:
        prompt = f"{CALM_NOTE} {prompt}"
    if outfit:
        prompt = f"{OUTFIT_REDO_NOTE} {prompt}"
    args = {
        "prompt": prompt[:2400],
        "duration": str(house_style.clip_seconds_for(model, (row.get("narration_seconds") or 0) + tail,
                                                     pacing["line_gap_sec"], pacing["five_second_stretch"])),
        "negative_prompt": clip_negative(style),
        "cfg_scale": 0.5,
    }
    if v3:
        args.update({"start_image_url": start_url, "generate_audio": False})
        if elements:
            args["elements"] = elements
    else:
        args["image_url"] = start_url
    return args


async def _comfy_clip_fills(row: dict, model: str, sheets: dict, tail: float, style: dict, pacing: dict,
                            calm: bool, outfit: bool, uploads: dict) -> dict:
    """Wan 2.2 on Comfy: the keyframe is the start image and the motion prompt is
    Kling's without @Element names. The workflow runs at CFG 1, where a negative
    prompt does nothing, so the cast lock, physics and no-text guards stay in the
    prompt itself (they already are)."""
    if row["keyframe_url"] not in uploads:
        img = await _fetch_source_bytes(row["keyframe_url"])
        if not img:
            raise ValueError(f"keyframe for shot {row['scene_index']}.{row['shot_index']} is missing")
        uploads[row["keyframe_url"]] = await comfy.upload(
            img[0], f"shot{row['scene_index']}-{row['shot_index']}.png", stage="video_generation")
    prompt = wan_motion_prompt(row.get("motion_prompt"), len(set(row.get("characters") or [])), calm, outfit,
                               row.get("objects"), row.get("toys"), row.get("cast_in_frame"))
    end = {}
    if row.get("end_keyframe_url"):
        if row["end_keyframe_url"] not in uploads:
            img = await _fetch_source_bytes(row["end_keyframe_url"])
            if img:
                uploads[row["end_keyframe_url"]] = await comfy.upload(
                    img[0], f"shot{row['scene_index']}-{row['shot_index']}-end.png", stage="video_generation")
        if row["end_keyframe_url"] in uploads:
            end = {"end_image": uploads[row["end_keyframe_url"]]}
    return {
        **end,
        "start_image": uploads[row["keyframe_url"]],
        "motion_prompt": prompt[:2400],
        "seed": comfy.new_seed(),
        "duration_seconds": house_style.clip_seconds_for(model, (row.get("narration_seconds") or 0) + tail,
                                                         pacing["line_gap_sec"], pacing["five_second_stretch"]),
        "output_prefix": f"gheras/{row['order_id'][:8]}/clip_{row['scene_index']}_{row['shot_index']}",
    }


async def kling_rescue_enabled() -> bool:
    """Off unless the owner turns it on: a Kling shot costs 4-5 times a Wan one,
    and the story was priced on Wan."""
    s = await db.settings.find_one({"key": "comfy.kling_rescue"}, {"_id": 0, "value": 1})
    return (s or {}).get("value") is True


async def run_shot_clips(order: dict, plan: dict, run_id: str, scene_index: int | None = None,
                         sem: asyncio.Semaphore | None = None, summarize: bool = True) -> dict:
    """Animate the shots with Kling or Wan 2.2 on Comfy — one scene's (as soon as
    it's drawn) or every shot still missing a clip. Request / prompt ids are
    saved before polling so a crash can be resumed; each shot gets one retry on
    an error, and one calmer redo when the reviewer flags the clip. A Wan clip
    flagged again or failing goes to Kling for that shot only (comfy.kling_rescue)."""
    if get_order_output_type(order) not in ("video", "both"):
        return {"ran": False, "reason": "output_type does not include video"}
    cfg = await get_pipeline_config()
    if not ((cfg.get("stages") or {}).get("video_generation") or {}).get("enabled", False):
        return {"ran": False, "reason": "video_generation disabled in pipeline_config"}
    # The parent's tier picks the renderer they paid for (premium = the admin's premium model).
    tier = video_tier_of(order)
    provider, model = await video_model_for_tier(tier)
    if provider not in ("kling", "comfy_video"):
        return {"ran": False, "reason": f"video provider '{provider}' has no shot executor"}
    on_comfy = provider == "comfy_video"
    rescue_on = on_comfy and await kling_rescue_enabled()
    rescue_model = await premium_video_model() if on_comfy else None

    all_rows = await shot_rows(order["id"], plan["id"])
    last = (all_rows[-1]["scene_index"], all_rows[-1]["shot_index"]) if all_rows else None
    rows = [r for r in all_rows if scene_index is None or r["scene_index"] == scene_index]
    sheets = await load_character_sheets(order, plan)
    style = await engine_config.style_for_order(order)
    pacing = await engine_config.get_pacing()
    sheet_urls: dict[str, str] = {}
    sheet_files: dict[str, tuple[bytes, str]] = {}
    sem = sem or asyncio.Semaphore(CLIP_CONCURRENCY)

    async def review_refs(row: dict) -> tuple[list, tuple | None]:
        """The shot's sheets and start frame, for the clip review."""
        refs = []
        for t in by_likeness(row.get("characters") or [], sheets)[:MAX_KEYFRAME_SHEETS]:
            if t not in sheet_files:
                got = await _fetch_source_bytes(sheets[t]["url"])
                if got:
                    sheet_files[t] = got
            if t in sheet_files:
                refs.append((sheets[t]["label"], *sheet_files[t]))
        return refs, await _fetch_source_bytes(row["keyframe_url"])
    key = {"order_id": order["id"], "production_plan_id": plan["id"]}

    async def _save(row: dict, patch: dict) -> None:
        await db.shot_assets.update_one({**key, "scene_index": row["scene_index"], "shot_index": row["shot_index"]},
                                        {"$set": {**patch, "updated_at": _now()}})

    async def _paid(row: dict, inc: dict, counted: str | None = None) -> None:
        await db.shot_assets.update_one({**key, "scene_index": row["scene_index"], "shot_index": row["shot_index"]},
                                        {"$inc": inc, **({"$set": {"clip_counted_id": counted}} if counted else {})})

    uploads: dict[str, str] = {}  # keyframe url → its name on Comfy
    rescued: list[str] = []

    async def failed_gpu(row: dict, e: Exception) -> None:
        """A Comfy job that failed still ran on the GPU: it's paid."""
        if getattr(e, "gpu_seconds", None):
            await _paid(row, {"comfy_gpu_seconds": e.gpu_seconds, "clip_gpu_seconds": e.gpu_seconds})

    async def attempt(row: dict, engine: str, engine_model: str) -> str:
        """One shot on one engine: "done", "failed", or "rescue" (a Wan clip
        flagged twice or failing, when Kling may take over)."""
        shot_key = f"{row['scene_index']}_{row['shot_index']}"
        wan = engine == "comfy_video"
        give_up = "rescue" if wan and rescue_on else "failed"
        resume = row.get("clip_state") == "submitted"
        request_id = row.get("clip_request_id") if resume and not wan else None
        prompt_id = row.get("clip_prompt_id") if resume and wan else None
        calm = outfit = reseeded = False
        best = None  # the flagged Wan take with the fewest problems
        tries = 0
        while tries < 2:
            tries += 1
            made = False  # the clip is downloaded (and paid)
            try:
                tail = pacing["end_tail_sec"] if (row["scene_index"], row["shot_index"]) == last else 0.0
                remote = None
                if wan:
                    fills = {} if prompt_id else await _comfy_clip_fills(row, engine_model, sheets, tail, style,
                                                                         pacing, calm, outfit, uploads)

                    async def submitted(pid: str, fills: dict = fills) -> None:
                        seconds = int(fills["duration_seconds"])
                        await _paid(row, {"paid_clip_seconds": seconds, "comfy_clip_seconds": seconds})
                        await _save(row, {"clip_prompt_id": pid, "clip_request_id": None, "clip_model": engine_model,
                                          "comfy_clip_model": engine_model, "clip_state": "submitted",
                                          "clip_seconds": seconds, "clip_prompt_used": fills["motion_prompt"],
                                          "clip_run_id": run_id})

                    # Pinned at both ends when the shot has its checked end picture (on a
                    # resumed job the fills are gone: the row says which workflow it was).
                    pinned = bool(fills.get("end_image")) if fills else bool(row.get("end_keyframe_url"))
                    data, _mime, job = await comfy.run(
                        stage="video_generation", workflow=CLIP_PINNED if pinned else comfy_workflow(engine_model),
                        fills=fills,
                        on_submitted=submitted, prompt_id=prompt_id, timeout=1200.0, poll_interval=5.0,
                        queue_key=story_order(row, row))
                    gpu = comfy.gpu_seconds(job)
                    # A job resumed after its review paused the order (empty balance) was counted then.
                    if gpu and not (prompt_id and row.get("clip_counted_id") == job.get("prompt_id")):
                        await _paid(row, {"comfy_gpu_seconds": gpu, "clip_gpu_seconds": gpu}, job.get("prompt_id"))
                else:
                    if not request_id:
                        args = await _clip_arguments(row, engine_model, sheets, sheet_urls, tail, style, pacing,
                                                     calm, outfit)
                        request_id = await fal.submit(stage="video_generation", env_key="FAL_KEY_VIDEO",
                                                      model=engine_model, arguments=args)
                        await _paid(row, {"paid_clip_seconds": int(args["duration"])})
                        await _save(row, {"clip_request_id": request_id, "clip_prompt_id": None,
                                          "clip_model": engine_model, "clip_state": "submitted",
                                          "clip_seconds": int(args["duration"]), "clip_prompt_used": args["prompt"],
                                          "clip_run_id": run_id})
                    result = await fal.wait(stage="video_generation", env_key="FAL_KEY_VIDEO", model=engine_model,
                                            request_id=request_id, timeout=1500, poll_interval=8)
                    remote = ((result or {}).get("video") or {}).get("url")
                    if not remote:
                        raise RuntimeError("Kling returned no video url")
                    data = await fal.download(remote)
                request_id = prompt_id = None  # used: a redo is a new request
                made = True
                refs, first = await review_refs(row)
                review = await clip_review.review_clip(shot_key, data, cast_labels(row.get("characters") or [], sheets),
                                                       row.get("motion_prompt") or "", refs, first, row.get("objects"))
                # The model first: a toy is checked in Wan's own clip. One that came alive
                # counts against the take (a redo); one that didn't leaves the clip exactly as
                # Wan made it (services/toy_freeze.py).
                toys = await toy_freeze.toy_check(data, first[0] if first else None, row.get("toys"))
                review = toy_freeze.with_check(review, toys)
                if not passes(review) and wan and not passes(row.get("keyframe_review")):
                    # The start frame itself was still flagged after its redraw: another
                    # Wan take animates the same picture, so none is paid for. The admin
                    # redoes frame + clip from the shots tab.
                    review = {**review, "start_frame_flagged": True}
                elif not passes(review):
                    problems = "review: " + ", ".join(review.get("problems") or [])
                    if wan and (best is None or len(review.get("problems") or []) <= len(best[1].get("problems") or [])):
                        best = (data, review, toys)
                    if not calm:
                        # One calmer redo; it doesn't use up the error retry.
                        calm, tries = True, tries - 1
                        outfit = "outfit_change" in (review.get("problems") or [])
                        await _save(row, {"clip_state": "retrying", "clip_review": {**review, "redone": True},
                                          "clip_error": problems})
                        continue
                    if give_up == "rescue":
                        await _save(row, {"clip_state": "retrying", "clip_review": {**review, "redone": True},
                                          "clip_error": problems})
                        return "rescue"
                    if wan and not reseeded:
                        # One more Wan take (every submit draws a new seed), then the best of them.
                        reseeded, tries = True, tries - 1
                        await _save(row, {"clip_state": "retrying", "clip_review": {**review, "redone": True},
                                          "clip_error": problems})
                        continue
                    if wan and best:
                        data, review, toys = best[0], {**best[1], "best_of_takes": True}, best[2]
                raw_url = None
                if toys and toys.get("alive"):
                    # Still alive in the take kept: the paste is the last resort. Wan's own
                    # clip is kept beside it for the admin.
                    raw_url = await _store(order, "clip_raw", data, "video/mp4", "mp4")
                    data, freeze_info = await toy_freeze.freeze_alive(data, toys)
                    review = {**review, "toy_freeze": freeze_info}
                url = await _store(order, "clip", data, "video/mp4", "mp4")
                await _save(row, {"clip_url": url, "clip_raw_url": raw_url, "clip_remote_url": remote,
                                  "clip_state": "completed",
                                  "clip_error": None, "clip_review": review, "clip_calm_redo": calm,
                                  "clip_prompt_id": None, "clip_engine": engine})
                return "done"
            except AIConfigError as e:
                # No key or no credit: the order pauses for the top-up (engine_health);
                # Kling doesn't quietly take over a whole story.
                await failed_gpu(row, e)
                if made:
                    # Only the review hit the empty balance: the clip's job stays saved
                    # ("submitted"), so the resume downloads it again instead of paying.
                    return "failed"
                await _save(row, {"clip_state": "failed", "clip_error": str(e)[:300], "clip_run_id": run_id})
                return "failed"
            except AIPermanentError as e:
                await failed_gpu(row, e)
                await _save(row, {"clip_state": "failed", "clip_error": str(e)[:300], "clip_run_id": run_id})
                return give_up
            except Exception as e:  # noqa: BLE001 — one fresh retry per shot
                await failed_gpu(row, e)
                logger.warning(f"[shots] clip {shot_key} on {engine} attempt {tries}: {e}")
                await _save(row, {"clip_state": "retrying" if tries == 1 else "failed",
                                  "clip_error": f"{type(e).__name__}: {e}"[:300], "clip_run_id": run_id})
                request_id = prompt_id = None
        return give_up

    async def one(row: dict) -> bool:
        if row.get("clip_url"):
            return True
        if row.get("clip_run_id") == run_id and row.get("clip_state") == "failed":
            return False  # already tried and retried in this run
        if not row.get("keyframe_url") or not row.get("narration_seconds"):
            await _save(row, {"clip_state": "skipped", "clip_error": "missing keyframe or narration"})
            return False
        bad = held_problems(row.get("keyframe_review"))
        if bad:
            await _save(row, {"clip_state": "held", "clip_error": "start frame: " + ", ".join(bad)})
            return False
        async with sem:
            if on_comfy and row.get("clip_rescue"):
                # Kling had taken over this shot before a restart: carry on there.
                outcome = await attempt(row, "kling", rescue_model)
            else:
                outcome = await attempt(row, provider, model)
                if outcome == "rescue":
                    fresh = await db.shot_assets.find_one(
                        {**key, "scene_index": row["scene_index"], "shot_index": row["shot_index"]},
                        {"_id": 0, "clip_error": 1}) or {}
                    logger.info(f"[shots] clip {row['scene_index']}.{row['shot_index']}: Wan gave up "
                                f"({fresh.get('clip_error')}), rendering this shot with Kling")
                    await _save(row, {"clip_rescue": {"from": model, "to": rescue_model, "at": _now(),
                                                      "reason": fresh.get("clip_error")}})
                    rescued.append(f"{row['scene_index']}_{row['shot_index']}")
                    outcome = await attempt({**row, "clip_state": None}, "kling", rescue_model)
            return outcome == "done"

    results = await asyncio.gather(*(one(r) for r in rows))
    saved = sum(1 for ok in results if ok)
    if summarize:
        await db.orders.update_one({"id": order["id"]}, {"$set": {"video_generation_summary": {
            "mode": "shots", "total": len(rows), "saved": saved, "failed": len(rows) - saved,
            "model": model, "tier": tier, "run_id": run_id, "ran_at": _now(),
            "kling_rescues": rescued,
        }}})
    return {"ran": True, "saved": saved, "total": len(rows), "kling_rescues": rescued}
