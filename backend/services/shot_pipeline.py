"""Shot-based video engine (M2).

A scene is a run of short animated shots with one narration line each — the
look of the reference videos the owner approved:

  character sheets   child from the photo; the rest of the cast drawn from the plan
  scene_keyframes    per shot, a 16:9 first frame drawn with the sheets (and the
                     previous shot of the scene) as references
  narration          per scene, one Gemini take in the chosen dialect, split at
                     the pauses into one line per shot
  clips              per shot, a Kling v3 clip at least as long as its line, so
                     assembly never holds a frame

Everything per shot lives in `shot_assets`; assembly is
video_assembly_service.assemble_shot_video.
"""
from __future__ import annotations

import asyncio
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
from services import clip_review, engine_config, house_style
from services.ai import AIPermanentError, fal
from services.ai.image_client import WIDE
from services.child_character_service import _fetch_source_bytes
from services.config_service import get_pipeline_config, video_tier_of
from services.model_catalog import video_model_for_tier
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
    t = profile.get("type") or "character"
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
                           "label": _label(profiles.get("child") or {"type": "child"}, child_name)}
    async for a in db.extra_character_assets.find(
        {"order_id": order["id"], "status": "completed", "generated_image_url": {"$ne": None}}, {"_id": 0},
    ):
        t = a.get("character_type")
        if t and t not in sheets:
            sheets[t] = {"url": a["generated_image_url"], "from_photo": True,
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
    with_photo = {c.get("type") for c in ((order.get("data") or {}).get("characters") or [])
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
REDRAW_NOTE = "Draw every person exactly once, each fully separate from the others, and no written words at all."
CALM_NOTE = "Calm, minimal motion: everyone stays where they are, nobody walks or jumps, the camera holds still."
PREV_SHOT_NOTE = "the previous shot of this scene — keep the same place, furniture, lighting and outfits"
PREV_SCENE_NOTE = ("the last shot of the previous scene — if the story is still in the same place, keep the "
                   "same room design and furniture (lighting may change)")


# Image and video models misspell any word they draw (a map once read "Costa
# Rria"), so pictures carry no writing at all.
NO_TEXT = ("No written words, letters, numbers or signs anywhere in the picture: maps, signs, books and screens "
           "show drawings only.")


def keyframe_prompt(scene: dict, sh: dict, profiles: dict, sheets: dict, child_name: str,
                    notes: list[str], style: dict) -> str:
    cast = "; ".join(_cast_line(profiles[t], child_name, bool((sheets.get(t) or {}).get("from_photo")))
                     for t in sh.get("characters") or [] if t in profiles)
    return " ".join(p for p in [
        sh.get("keyframe_prompt") or scene.get("visual_description") or "",
        f"Shot type: {sh.get('shot_type') or 'medium'}.",
        f"Setting: {scene['background_setting']}." if scene.get("background_setting") else "",
        f"Characters, matching their reference sheets exactly: {cast}." if cast else "",
        ("Reference images, in order: " + "; ".join(f"{i + 1}) {n}" for i, n in enumerate(notes)) + ".")
        if notes else "",
        f"Art style: {style['style_text']}",
        style["frame_rules"],
        NO_TEXT,
    ] if p)


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


def motion_prompt(motion: str | None, mapping: list[str], style: dict, cast: list[str] | None = None) -> str:
    return " ".join(p for p in [
        motion or "Gentle natural character motion and a slow camera push-in.",
        ("Characters: " + "; ".join(mapping) + ".") if mapping else "",
        cast_lock(cast or []),
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
    for sh in scene["shots"]:
        done = await db.shot_assets.find_one(
            {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"],
             "shot_index": sh["shot_index"], "keyframe_url": {"$ne": None}}, {"_id": 0, "keyframe_url": 1})
        if done:
            prev = await _fetch_source_bytes(done["keyframe_url"])
            hero_url = hero_url or done["keyframe_url"]
            continue
        refs, notes = [], []
        for t in by_likeness(sh.get("characters") or [], sheets)[:MAX_KEYFRAME_SHEETS]:
            if t not in sheet_bytes:
                got = await _fetch_source_bytes(sheets[t]["url"])
                if got:
                    sheet_bytes[t] = got
            if t in sheet_bytes:
                refs.append({"image_bytes": sheet_bytes[t][0], "mime_type": sheet_bytes[t][1]})
                notes.append(f"{sheets[t]['label']}'s character sheet")
        if prev:
            refs.append({"image_bytes": prev[0], "mime_type": prev[1]})
            notes.append(PREV_SHOT_NOTE)
        elif previous_scene:
            refs.append({"image_bytes": previous_scene[0], "mime_type": previous_scene[1]})
            notes.append(PREV_SCENE_NOTE)
        prompt = keyframe_prompt(scene, sh, profiles, sheets, child_name, notes, style)
        shot_key = f"{scene['scene_index']}_{sh['shot_index']}"
        cast = cast_labels(sh.get("characters") or [], sheets)
        for attempt in (1, 2):
            img, mime, meta = await generate_image(
                scene_prompt=prompt if attempt == 1 else f"{prompt} {REDRAW_NOTE}", references=refs or None,
                stage="scene_image_generation", size=WIDE, raw_prompt=True,
                session_hint=f"shot-{shot_key}-{order['id'][:6]}-{attempt}",
            )
            # A start frame with a cloned person or written words would be
            # animated as is: redraw it once (an image is cheaper than a clip).
            await db.shot_assets.update_one(
                {"order_id": order["id"], "production_plan_id": plan["id"], "scene_index": scene["scene_index"],
                 "shot_index": sh["shot_index"]},
                {"$inc": {"paid_keyframes": 1}, "$setOnInsert": {"id": str(uuid.uuid4()), "created_at": _now()}},
                upsert=True)
            review = await clip_review.review_keyframe(shot_key, img, mime, cast, sh.get("keyframe_prompt") or "")
            review["redrawn"] = attempt == 2
            if review.get("ok"):
                break
        url = await _store(order, "keyframe", img, mime, "png")
        model = meta.get("model")
        await _set_shot(order, plan, scene, sh["shot_index"], {
            "keyframe_url": url, "keyframe_at": _now(), "keyframe_prompt_used": prompt, "image_model": model, "keyframe_review": review,
            "narration_line": sh["narration_line"], "shot_type": sh.get("shot_type"),
            "characters": sh.get("characters") or [], "motion_prompt": sh.get("motion_prompt") or "",
            "style_key": style.get("key"), "style_version": style.get("version"),
        })
        prev = (img, mime)
        hero_url = hero_url or url

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
        gaps = [(e - s, (s + e) / 2) for s, e in zip(starts, ends) if 0.3 < s and e < total - 0.2]
        if len(gaps) < len(lines) - 1:
            return None
        cuts = sorted(mid for _, mid in sorted(gaps, reverse=True)[: len(lines) - 1])
        bounds = [0.0, *cuts, total]
        out = []
        for i, line in enumerate(lines):
            seg_len = bounds[i + 1] - bounds[i]
            expected = max(1.0, len(line.split()) / words_per_second)
            if not 0.35 <= seg_len / expected <= 2.6:
                return None
            dst = os.path.join(d, f"line{i}.wav")
            trim = ("silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                    "silenceremove=start_periods=1:start_threshold=-45dB,areverse")
            subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src,
                            "-ss", f"{bounds[i]:.3f}", "-to", f"{bounds[i + 1]:.3f}", "-af", trim, dst],
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
                    w, gmeta = await synthesize_gemini_fal(text, voice, dialect["tts_direction"], m, dialect_key)
                else:
                    w, gmeta = await synthesize_gemini(text, voice, dialect["tts_direction"], m)
                secs = await _seconds_of(w, "wav")
                if _plausible(secs, words, wps):
                    return w, gmeta
                tried.append(f"{gmeta.get('model')}={secs:.1f}s")
                logger.warning(f"[shots] implausible narration ({secs:.1f}s for {words} words) from {gmeta.get('model')}")
            raise AIError(f"narration for {words} words came out implausibly long/short ({', '.join(tried)})")

        wav, gmeta = await voice_text("\n".join(lines))
        meta.update(gmeta)
        take_url = await _store(order, "narration", wav, "audio/wav", "wav")
        pieces = await asyncio.to_thread(_split_take, wav, lines, wps)
        if pieces is None:
            logger.warning(f"[shots] scene {scene['scene_index']}: take didn't split cleanly; voicing line by line")
            pieces = [(await voice_text(line))[0] for line in lines]
            meta["split"] = "per_line"
        else:
            meta["split"] = "one_take"
        segments = [(p, "audio/wav", "wav") for p in pieces]
    else:
        voice = await narration_voice_for_order(order)
        segments = []
        for line in lines:
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
                          style: dict | None = None, pacing: dict | None = None, calm: bool = False) -> dict:
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
    prompt = motion_prompt(row.get("motion_prompt"), mapping, style, cast)
    if calm:
        prompt = f"{CALM_NOTE} {prompt}"
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


async def run_shot_clips(order: dict, plan: dict, run_id: str, scene_index: int | None = None,
                         sem: asyncio.Semaphore | None = None, summarize: bool = True) -> dict:
    """Animate the shots with Kling — one scene's (as soon as it's drawn) or
    every shot still missing a clip. Request ids are saved before polling so a
    crash can be resumed; each shot gets one retry on an error, and one calmer
    redo when the reviewer flags the clip."""
    if get_order_output_type(order) not in ("video", "both"):
        return {"ran": False, "reason": "output_type does not include video"}
    cfg = await get_pipeline_config()
    if not ((cfg.get("stages") or {}).get("video_generation") or {}).get("enabled", False):
        return {"ran": False, "reason": "video_generation disabled in pipeline_config"}
    # The parent's tier picks the renderer they paid for (premium = the admin's premium model).
    tier = video_tier_of(order)
    provider, model = await video_model_for_tier(tier)
    if provider != "kling":
        return {"ran": False, "reason": f"video provider '{provider}' has no shot executor"}

    all_rows = await shot_rows(order["id"], plan["id"])
    last = (all_rows[-1]["scene_index"], all_rows[-1]["shot_index"]) if all_rows else None
    rows = [r for r in all_rows if scene_index is None or r["scene_index"] == scene_index]
    sheets = await load_character_sheets(order, plan)
    style = await engine_config.style_for_order(order)
    pacing = await engine_config.get_pacing()
    sheet_urls: dict[str, str] = {}
    sem = sem or asyncio.Semaphore(CLIP_CONCURRENCY)
    key = {"order_id": order["id"], "production_plan_id": plan["id"]}

    async def _save(row: dict, patch: dict) -> None:
        await db.shot_assets.update_one({**key, "scene_index": row["scene_index"], "shot_index": row["shot_index"]},
                                        {"$set": {**patch, "updated_at": _now()}})

    async def one(row: dict) -> bool:
        if row.get("clip_url"):
            return True
        if row.get("clip_run_id") == run_id and row.get("clip_state") == "failed":
            return False  # already tried and retried in this run
        if not row.get("keyframe_url") or not row.get("narration_seconds"):
            await _save(row, {"clip_state": "skipped", "clip_error": "missing keyframe or narration"})
            return False
        shot_key = f"{row['scene_index']}_{row['shot_index']}"
        async with sem:
            request_id = row.get("clip_request_id") if row.get("clip_state") == "submitted" else None
            calm = False
            attempt = 0
            while attempt < 2:
                attempt += 1
                try:
                    if not request_id:
                        tail = pacing["end_tail_sec"] if (row["scene_index"], row["shot_index"]) == last else 0.0
                        args = await _clip_arguments(row, model, sheets, sheet_urls, tail, style, pacing, calm)
                        request_id = await fal.submit(stage="video_generation", env_key="FAL_KEY_VIDEO",
                                                      model=model, arguments=args)
                        await db.shot_assets.update_one(
                            {**key, "scene_index": row["scene_index"], "shot_index": row["shot_index"]},
                            {"$inc": {"paid_clip_seconds": int(args["duration"])}})
                        await _save(row, {"clip_request_id": request_id, "clip_model": model, "clip_state": "submitted",
                                          "clip_seconds": int(args["duration"]), "clip_prompt_used": args["prompt"],
                                          "clip_run_id": run_id})
                    result = await fal.wait(stage="video_generation", env_key="FAL_KEY_VIDEO", model=model,
                                            request_id=request_id, timeout=1500, poll_interval=8)
                    remote = ((result or {}).get("video") or {}).get("url")
                    if not remote:
                        raise RuntimeError("Kling returned no video url")
                    data = await fal.download(remote)
                    review = await clip_review.review_clip(shot_key, data, cast_labels(row.get("characters") or [], sheets),
                                                           row.get("motion_prompt") or "")
                    if not review.get("ok") and not calm:
                        # One calmer redo; it doesn't use up the error retry.
                        calm, attempt, request_id = True, attempt - 1, None
                        await _save(row, {"clip_state": "retrying", "clip_review": {**review, "redone": True},
                                          "clip_error": "review: " + ", ".join(review.get("problems") or [])})
                        continue
                    url = await _store(order, "clip", data, "video/mp4", "mp4")
                    await _save(row, {"clip_url": url, "clip_remote_url": remote, "clip_state": "completed",
                                      "clip_error": None, "clip_review": review, "clip_calm_redo": calm})
                    return True
                except AIPermanentError as e:
                    await _save(row, {"clip_state": "failed", "clip_error": str(e)[:300], "clip_run_id": run_id})
                    return False
                except Exception as e:  # noqa: BLE001 — one fresh retry per shot
                    logger.warning(f"[shots] clip {row['scene_index']}.{row['shot_index']} attempt {attempt}: {e}")
                    await _save(row, {"clip_state": "retrying" if attempt == 1 else "failed",
                                      "clip_error": f"{type(e).__name__}: {e}"[:300], "clip_run_id": run_id})
                    request_id = None
            return False

    results = await asyncio.gather(*(one(r) for r in rows))
    saved = sum(1 for ok in results if ok)
    if summarize:
        await db.orders.update_one({"id": order["id"]}, {"$set": {"video_generation_summary": {
            "mode": "shots", "total": len(rows), "saved": saved, "failed": len(rows) - saved,
            "model": model, "tier": tier, "run_id": run_id, "ran_at": _now(),
        }}})
    return {"ran": True, "saved": saved, "total": len(rows)}
