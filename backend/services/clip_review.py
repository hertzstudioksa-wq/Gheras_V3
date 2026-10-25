"""Automatic check of every shot before it's used (owner decision, 2026-10-25).

Kling sometimes clones a character (the father appeared twice when the camera
"revealed" the room) or walks a body through an object (the child through a
bridge railing), and image models write misspelled words. A small vision model
looks at the shot's start frame, and later at four frames of its clip, and
says whether that happened. A flagged keyframe is redrawn once, a flagged clip
is animated once more with calmer motion; the verdict stays on the shot so the
admin sees it. It never blocks delivery: when the reviewer can't be reached,
or the setting is off, the shot is used as is.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

from db import db

logger = logging.getLogger("clip_review")

REVIEW_MODEL = "anthropic/claude-haiku-5.5"
CLIP_FRAMES = 4
PROBLEMS = ("duplicate", "extra_person", "clipping", "vanishing", "text", "deformed")

SYSTEM = (
    "You check frames of a 2D cartoon shot from a children's story before a family sees it. You get the people who "
    "should be in the shot and what they do. Report only clear, visible mistakes:\n"
    "- duplicate: the same character appears twice in one frame (two copies of the father)\n"
    "- extra_person: more people than expected (ignore tiny far-away background figures)\n"
    "- clipping: a body passes through a solid object (railing, rope, wall, furniture, another person) or a limb "
    "merges into something\n"
    "- vanishing: a character disappears or pops in between frames\n"
    "- text: written words or letters anywhere\n"
    "- deformed: a badly broken face or body\n"
    "A natural cartoon pose, motion blur, or someone partly out of frame is fine. When unsure, it is fine.\n"
    'Answer with JSON only: {"ok": true or false, "people_seen": <most people in one frame>, '
    '"problems": [zero or more of: duplicate, extra_person, clipping, vanishing, text, deformed], '
    '"note": "<one short English sentence>"}'
)


async def enabled() -> bool:
    s = await db.settings.find_one({"key": "clip_review.enabled"}, {"_id": 0, "value": 1})
    return (s or {}).get("value", True) is not False


def _problem(raw) -> str | None:
    """The known problem a model's wording names ("duplicate person", "Clipping through railing"...)."""
    text = re.sub(r"[\s\-]+", "_", str(raw or "").strip().lower())
    return next((p for p in PROBLEMS if p in text or text.startswith(p.split("_")[0])), None)


def _verdict(answer: str) -> dict:
    m = re.search(r"\{.*\}", answer or "", re.S)
    data = json.loads(m.group(0)) if m else {}
    problems = sorted({p for p in map(_problem, data.get("problems") or []) if p})
    return {"ok": not problems, "problems": problems, "people_seen": data.get("people_seen"),
            "note": str(data.get("note") or "")[:200]}


async def _ask(stage: str, shot_key: str, images: list[tuple[bytes, str]], expected: list[str], action: str) -> dict:
    """{ok, problems, people_seen, note} — or ok with `skipped` when the check can't run."""
    if not await enabled():
        return {"ok": True, "skipped": "off"}
    from services.ai import fal
    from services.ai.text_client import generate_vision

    try:
        urls = [await fal.upload(env_key="FAL_KEY_TEXT", data=data, content_type=mime,
                                 file_name=f"review-{shot_key}-{i}.{mime.split('/')[-1]}")
                for i, (data, mime) in enumerate(images)]
        user = json.dumps({"shot": shot_key, "frames": len(urls), "expected_people": expected or ["nobody"],
                           "expected_count": len(expected), "action": (action or "")[:400]}, ensure_ascii=False)
        answer = await generate_vision(stage=stage, model=REVIEW_MODEL, system=SYSTEM, user=user, image_urls=urls,
                                       max_tokens=300)
        verdict = _verdict(answer)
    except Exception as e:  # noqa: BLE001 — a review that can't run never blocks the story
        logger.warning(f"[review] {stage} {shot_key} skipped: {type(e).__name__}: {str(e)[:160]}")
        return {"ok": True, "skipped": "unavailable", "error": f"{type(e).__name__}: {str(e)[:160]}"}
    if not verdict["ok"]:
        logger.warning(f"[review] {stage} {shot_key} flagged: {verdict['problems']} — {verdict['note']}")
    return verdict


async def review_keyframe(shot_key: str, image: bytes, mime: str, expected: list[str], action: str) -> dict:
    return await _ask("keyframe_review", shot_key, [(image, mime or "image/png")], expected, action)


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


async def review_clip(shot_key: str, data: bytes, expected: list[str], action: str) -> dict:
    if not await enabled():
        return {"ok": True, "skipped": "off"}
    try:
        frames = await asyncio.to_thread(_clip_frames, data)
    except Exception as e:  # noqa: BLE001
        return {"ok": True, "skipped": "frames", "error": f"{type(e).__name__}: {str(e)[:160]}"}
    return await _ask("clip_review", shot_key, [(f, "image/jpeg") for f in frames], expected, action)
