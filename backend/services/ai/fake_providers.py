"""Free full-pipeline rehearsals (local development only).

With GHERAS_FAKE_PROVIDERS=1 every paid AI call is answered locally after a
realistic wait (GHERAS_FAKE_SPEED scales it; 0.2 = five times faster than the
real models):

  text        by stage: safety, scenario ideas and a production plan built
              from the order, tashkeel (returns the page unchanged), probes
  pictures    drawn with Pillow, stamped REHEARSAL
  narration   tones with a pause between lines (the per-shot split still works)
  music       a soft two-tone bed (ffmpeg)
  Kling clips a slow zoom over the shot's start frame (ffmpeg), as long as asked
  Comfy jobs  the same picture / zoom, returned as a job shaped like Comfy's
              (status, execution times in ms, outputs[node].images)

The whole order flow — progress, ETA, previews, payment, delivery, restart
recovery, an exhausted balance — can then be exercised from the UI at no cost.
Simulations live in db.fake_rehearsal (see `simulate`). The server refuses to
start in this mode against a production database.
"""
from __future__ import annotations

import asyncio
import contextvars
import hashlib
import io
import json
import math
import os
import re
import struct
import subprocess
import tempfile
import time
import uuid
import wave
from datetime import datetime, timezone

from db import db

# The order a scenario or planning run is working on (set by those runners), so
# the fake text can be built from the real order instead of parsing prompts.
CURRENT_ORDER: contextvars.ContextVar[str | None] = contextvars.ContextVar("fake_current_order", default=None)

LOCK_MESSAGE = "User is locked. Exhausted balance. Top up your balance at fal.ai/dashboard/billing."
# Comfy's real 402 body hasn't been seen yet; this follows its documented shape.
COMFY_LOCK_BODY = '{"code": "PAYMENT_REQUIRED", "message": "Payment required - Insufficient credits"}'
PREFIX = "fake://"

# Real-world seconds per call, measured on the first full test order (Comfy: the
# bake-off on an RTX PRO 6000).
REAL_SECONDS = {
    "safety_check": 3, "engine_probe": 1, "scenario_generation": 50, "production_planning": 115,
    "book_tashkeel": 20, "clip_review": 5, "keyframe_review": 5, "vision_describe": 4, "image": 45, "tts": 10, "music": 60,
    "video": 270, "comfy_keyframe": 20, "comfy_clip": 80,
}


def enabled() -> bool:
    return os.environ.get("GHERAS_FAKE_PROVIDERS") == "1"


def speed() -> float:
    try:
        return max(0.01, float(os.environ.get("GHERAS_FAKE_SPEED") or 0.2))
    except ValueError:
        return 0.2


def assert_safe_to_start() -> None:
    """Fake answers must never reach a real customer."""
    if not enabled():
        return
    db_name = (os.environ.get("DB_NAME") or "").lower()
    public = (os.environ.get("PUBLIC_APP_URL") or "").lower()
    if os.environ.get("GHERAS_ENV") == "production" or "prod" in db_name or \
            (public and "localhost" not in public and "127.0.0.1" not in public):
        raise RuntimeError("GHERAS_FAKE_PROVIDERS=1 is for local rehearsals only — refusing to start")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dir() -> str:
    from storage import STORAGE_DIR

    path = STORAGE_DIR / "tmp" / "fake"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


async def _wait(kind: str, extra: float = 0.0) -> None:
    await asyncio.sleep((REAL_SECONDS.get(kind, 5) + extra) * speed())


# ---------------------------------------------------------------- simulations
async def simulation() -> dict:
    return await db.fake_rehearsal.find_one({"id": "default"}, {"_id": 0}) or {}


async def simulate(**flags) -> dict:
    """locked=True → every fal call answers "exhausted balance";
    comfy_locked=True → Comfy answers 402 at submit, running jobs fail with
    InsufficientFundsError and the balance reads $0;
    bad_clips=["2_2"] → the clip review flags those shots once (then passes)."""
    await db.fake_rehearsal.update_one({"id": "default"}, {"$set": {"id": "default", **flags}}, upsert=True)
    return await simulation()


async def _raise_if_locked(stage: str) -> None:
    """Mirrors the real fal adapter: a lock is reported, a success clears it."""
    from services import engine_health

    if (await simulation()).get("locked"):
        from services.ai import classify_http_error

        await engine_health.note_error(stage, LOCK_MESSAGE)
        raise classify_http_error(stage, "fal", 403, LOCK_MESSAGE)
    await engine_health.note_success()


# ---------------------------------------------------------------- text
async def text(stage: str, provider: str, system: str, user: str) -> str:
    if provider == "fal_llm":
        await _raise_if_locked(stage)
    await _wait(stage)
    if stage == "safety_check":
        return json.dumps({"safe": True, "category": "ok", "reason_ar": ""})
    if stage == "engine_probe":
        return "OK"
    if stage == "book_tashkeel":
        return user  # {"pages": [...]} unchanged: passes the letter check, book stays plain
    if stage in ("clip_review", "keyframe_review"):
        return await _review(stage, user)
    if stage == "vision_describe":
        return "A person in simple casual clothes with a warm smile (rehearsal description)."
    order = await db.orders.find_one({"id": CURRENT_ORDER.get()}, {"_id": 0}) if CURRENT_ORDER.get() else None
    if stage == "scenario_generation":
        return json.dumps(_scenarios(order or {}), ensure_ascii=False)
    if stage == "production_planning":
        return json.dumps(_plan(order or {}, user), ensure_ascii=False)
    return "{}"


async def _review(stage: str, user: str) -> str:
    """Flags a shot listed in bad_clips the first time it's reviewed."""
    m = re.search(r'"shot"\s*:\s*"(\d+_\d+)"', user)
    shot = m.group(1) if m else ""
    sim = await simulation()
    if stage == "clip_review" and shot in (sim.get("bad_clips") or []) and shot not in (sim.get("flagged") or []):
        await db.fake_rehearsal.update_one({"id": "default"}, {"$addToSet": {"flagged": shot}})
        return json.dumps({"ok": False, "people_seen": 4, "problems": ["duplicate person"],
                           "note": "rehearsal: simulated duplicate"})
    return json.dumps({"ok": True, "people_seen": None, "problems": [], "note": "rehearsal"})


def _child(order: dict) -> dict:
    return ((order.get("data") or {}).get("child") or {})


def _scenarios(order: dict) -> dict:
    name = _child(order).get("name") or "البطل"
    target = int((order.get("duration") or {}).get("scene_target") or 4)
    angles = [("emotional", "حضن العيلة"), ("educational", "خطوة خطوة"), ("adventure", "مغامرة في الطبيعة")]
    return {"scenarios": [{
        "title": f"{name} و{label} (بروفة)",
        "short_summary": f"بروفة مجانية: {name} عنده هدف صغير، بيحاول ويتعب، يكمّل، والنتيجة الحلوة بتيجي من مجهوده.",
        "emotional_angle": angle,
        "learning_goal": "الاجتهاد بيجيب نتيجة حلوة",
        "visual_style_hint": "warm colors, family, nature",
        "estimated_scene_count": target,
        "why_this_fits": f"نص بروفة — مش من موديل حقيقي، عشان نجرّب المسار كله لـ{name} ببلاش.",
    } for angle, label in angles]}


_LINES = [
    "{n} صحي بدري وعينه بتلمع من الفرحة.",
    "بص من الشباك وشاف الشجر الأخضر.",
    "مسك إيد ماما وقال: يلا بينا!",
    "الطريق كان طويل، ورجليه تعبت شوية.",
    "قال لنفسه: خطوة كمان، أنا أقدر.",
    "بابا ضحك وقاله: إنت بطل أوي.",
    "وصلوا فوق، والمنظر كان يجنن.",
    "الطيور غنّت والمية لمعت تحت الشمس.",
    "{n} حضن بابا وماما جامد.",
    "التعب راح، وفضلت الفرحة.",
    "رجعوا البيت وهما بيغنّوا سوا.",
    "ونام {n} وهو مبتسم.",
]
_SHOT_TYPES = ["wide", "medium", "close-up", "insert", "medium", "back view"]


def _plan(order: dict, user: str) -> dict:
    child = _child(order)
    name = child.get("name") or "البطل"
    visible = [c for c in ((order.get("data") or {}).get("characters") or []) if c.get("role") == "visible"]
    cast = ["child"] + [c.get("type") or "other" for c in visible]
    counts = [int(n) for _, n in re.findall(r"- المشهد (\d+): (\d+) لقطات", user)]
    if not counts:
        counts = [2] * int((order.get("duration") or {}).get("scene_target") or 4)
    characters = [{"type": "child", "name": name, "name_en": "the child",
                   "visual_description": "a cheerful young child", "clothing_style": "same as in the photo",
                   "key_features": "big smile", "reference_image_url": child.get("image_url")}]
    for c in visible:
        characters.append({"type": c.get("type") or "other", "name": c.get("name"), "name_en": c.get("type"),
                           "visual_description": f"the child's {c.get('type')}",
                           "clothing_style": "same as in the photo" if c.get("image_url") else "simple casual clothes",
                           "key_features": "kind eyes", "reference_image_url": c.get("image_url")})
    scenes, pages, k = [], [], 0
    for i, n in enumerate(counts, 1):
        shots = []
        for j in range(1, n + 1):
            line = _LINES[k % len(_LINES)].format(n=name)
            k += 1
            shot_type = _SHOT_TYPES[(i + j) % len(_SHOT_TYPES)]
            who = [] if shot_type == "insert" else cast[:2] if shot_type in ("medium", "close-up") else cast[:3]
            shots.append({"shot_index": j, "narration_line": line, "shot_type": shot_type, "characters": who,
                          "keyframe_prompt": f"Rehearsal frame {i}.{j}: the family in a green valley, warm light.",
                          "motion_prompt": "The child smiles and waves. Leaves sway gently. Slow push-in."})
        text_ar = " ".join(sh["narration_line"] for sh in shots)
        scenes.append({
            "scene_index": i, "arc_beat": "beat", "title": f"المشهد {i}", "scene_goal": "بروفة",
            "narration_text": text_ar, "book_text": text_ar, "emotional_tone": "warm",
            "visual_description": "a green valley with a river", "characters_in_scene": cast[:3],
            "key_objects": ["backpack"], "background_setting": "green valley, river, mountains",
            "continuity_notes": "same outfits", "image_prompt": {"prompt_text": "rehearsal", "style_reference": "",
                                                                 "character_reference_note": ""},
            "animation_prompt": {}, "video_prompt": "rehearsal", "voice_prompt": "warm", "music_prompt": "gentle",
            "music_keywords": ["gentle"], "camera_motion_hint": "slow push-in", "estimated_duration_seconds": 5 * n,
            "shots": shots,
        })
        pages.append({"page_number": i, "scene_index": i, "text": text_ar, "illustration_prompt": "rehearsal"})
    return {
        "production_plan": {
            "title": f"{name} والرحلة الحلوة (بروفة)",
            "story_summary": f"قصة بروفة مجانية عن {name} — النصوص والصور والأصوات مولّدة محلياً للتجربة.",
            "main_message": "الاجتهاد بيجيب نتيجة حلوة",
            "emotional_arc": "effort to joy",
            "cover_prompt": "rehearsal cover: the family on a hill at sunset",
            "story_keywords": ["family", "nature"], "story_music_prompt": "gentle acoustic guitar",
            "story_music_keywords": ["warm"], "story_voice_prompt": "warm", "safety_check": "ok",
        },
        "characters": characters,
        "scenes": scenes,
        "book_pages": pages,
    }


# ---------------------------------------------------------------- pictures
def _size(size: str) -> tuple[int, int]:
    m = re.match(r"(\d+)x(\d+)", size or "")
    return (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)


def picture(prompt: str, size: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    w, h = _size(size)
    seed = hashlib.md5((prompt or "").encode("utf-8")).digest()
    sky = (110 + seed[0] % 100, 150 + seed[1] % 80, 190 + seed[2] % 60)
    img = Image.new("RGB", (w, h), sky)
    d = ImageDraw.Draw(img)
    d.rectangle([0, int(h * 0.68), w, h], fill=(90 + seed[3] % 60, 150 + seed[4] % 60, 80))
    d.ellipse([int(w * 0.78), int(h * 0.08), int(w * 0.9), int(h * 0.08) + int(w * 0.12)], fill=(250, 220, 120))
    figures = 1 if h > w else 1 + seed[5] % 3
    for f in range(figures):
        cx = int(w * (f + 1) / (figures + 1))
        body_h = int(h * (0.45 if h > w else 0.3))
        top = int(h * 0.68) - body_h
        color = (180 + seed[6 + f] % 70, 90 + seed[9 + f] % 120, 90 + seed[12 + f] % 120)
        d.rounded_rectangle([cx - body_h // 6, top + body_h // 3, cx + body_h // 6, int(h * 0.68)], 20, fill=color)
        r = body_h // 6
        d.ellipse([cx - r, top, cx + r, top + 2 * r], fill=(240, 200, 170))
    big = ImageFont.load_default(size=max(28, w // 18))
    small = ImageFont.load_default(size=max(14, w // 64))
    d.text((w // 24, h // 24), "REHEARSAL", fill=(255, 255, 255), font=big, stroke_width=3, stroke_fill=(60, 60, 60))
    words, line, lines = re.sub(r"\s+", " ", prompt or "")[:260].split(" "), "", []
    for word in words:
        if len(line) + len(word) > max(30, w // 14):
            lines.append(line)
            line = ""
        line += word + " "
    lines.append(line)
    for n, text_line in enumerate(lines[:4]):
        d.text((w // 24, int(h * 0.74) + n * (w // 50)), text_line, fill=(255, 255, 255), font=small)
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


async def image(stage: str, provider: str, model: str, prompt: str, size: str, quality: str) -> tuple[bytes, str, dict]:
    if provider == "fal_image":
        await _raise_if_locked(stage)
    await _wait("image")
    return picture(prompt, size), "image/png", {
        "provider": provider, "model": f"rehearsal:{model}", "size": size, "quality": quality, "rehearsal": True,
    }


# ---------------------------------------------------------------- sound & clips
def _tone_wav(lines: list[str], words_per_second: float = 2.0, rate: int = 24000) -> bytes:
    """One tone per line, 0.7 s of silence between lines (the take splitter cuts there)."""
    frames = bytearray()

    def silence(sec: float):
        frames.extend(b"\x00\x00" * int(rate * sec))

    silence(0.25)
    for i, line in enumerate(lines):
        secs = max(0.8, len(line.split()) / words_per_second)
        freq = 260 + 40 * (i % 4)
        for t in range(int(rate * secs)):
            env = min(1.0, t / 800, (rate * secs - t) / 800)
            frames.extend(struct.pack("<h", int(9000 * env * math.sin(2 * math.pi * freq * t / rate))))
        silence(0.7 if i < len(lines) - 1 else 0.3)
    out = io.BytesIO()
    with wave.open(out, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(bytes(frames))
    return out.getvalue()


def _ffmpeg_out(args: list[str], ext: str) -> bytes:
    from services.video_assembly_service import _ffmpeg_bin

    with tempfile.TemporaryDirectory(dir=_dir()) as work:
        out = os.path.join(work, f"out.{ext}")
        subprocess.run([_ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *[a.replace("{work}", work) for a in args], out],
                       check=True, timeout=300)
        with open(out, "rb") as f:
            return f.read()


def _music(seconds: float) -> bytes:
    return _ffmpeg_out(["-f", "lavfi", "-i", f"sine=frequency=196:duration={seconds:.2f}",
                        "-f", "lavfi", "-i", f"sine=frequency=294:duration={seconds:.2f}",
                        "-filter_complex", "amix=inputs=2,volume=0.25", "-c:a", "libmp3lame", "-b:a", "128k"], "mp3")


def _clip(start_png: bytes, seconds: int) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".png", dir=_dir(), delete=False) as f:
        f.write(start_png)
        src = f.name
    try:
        frames = int(seconds * 24)
        return _ffmpeg_out(["-i", src, "-vf",
                            f"scale=2560:1440,zoompan=z='min(zoom+0.0012,1.35)':x='iw/2-(iw/zoom/2)':"
                            f"y='ih/2-(ih/zoom/2)':d={frames}:s=1280x720:fps=24",
                            "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p"], "mp4")
    finally:
        os.unlink(src)


def _save(data: bytes, ext: str) -> str:
    name = f"{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(_dir(), name), "wb") as f:
        f.write(data)
    return PREFIX + name


def read(url: str) -> bytes:
    with open(os.path.join(_dir(), url[len(PREFIX):].split("/")[-1]), "rb") as f:
        return f.read()


async def fal_upload(data: bytes, content_type: str) -> str:
    await _raise_if_locked("upload")
    ext = (content_type or "application/octet-stream").split("/")[-1].split(";")[0] or "bin"
    return _save(data, ext)


async def fal_submit(stage: str, model: str, arguments: dict) -> str:
    await _raise_if_locked(stage)
    request_id = f"fake-{uuid.uuid4()}"
    # Persisted, so a restart in the middle resumes like a real queued request.
    await db.fake_requests.insert_one({"id": request_id, "stage": stage, "model": model, "arguments": arguments,
                                       "created_at": _now(), "t0": time.time()})
    return request_id


def _kind(model: str) -> str:
    m = model.lower()
    if "kling" in m or "video" in m:
        return "video"
    if "tts" in m or "elevenlabs/tts" in m or "speech" in m:
        return "tts"
    if "music" in m or "cassette" in m or "audio" in m:
        return "music"
    return "other"


async def fal_wait(stage: str, model: str, request_id: str) -> dict:
    await _raise_if_locked(stage)
    req = await db.fake_requests.find_one({"id": request_id}, {"_id": 0})
    if not req:
        from services.ai import AIError
        raise AIError(f"rehearsal request {request_id} not found")
    if req.get("result"):
        return req["result"]
    kind, args = _kind(model), req.get("arguments") or {}
    remaining = REAL_SECONDS.get(kind, 5) * speed() - (time.time() - float(req.get("t0") or time.time()))
    if remaining > 0:
        await asyncio.sleep(remaining)
    if kind == "video":
        start = read(args.get("start_image_url") or args.get("image_url"))
        url = _save(await asyncio.to_thread(_clip, start, int(args.get("duration") or 5)), "mp4")
        result = {"video": {"url": url, "content_type": "video/mp4"}}
    elif kind == "tts":
        lines = [x for x in str(args.get("prompt") or args.get("text") or "").split("\n") if x.strip()] or ["..."]
        result = {"audio": {"url": _save(_tone_wav(lines), "wav"), "content_type": "audio/wav"}}
    elif kind == "music":
        secs = float(args.get("duration") or args.get("seconds_total") or (args.get("music_length_ms") or 30000) / 1000)
        result = {"audio": {"url": _save(await asyncio.to_thread(_music, secs), "mp3"), "content_type": "audio/mpeg"}}
    else:
        result = {}
    await db.fake_requests.update_one({"id": request_id}, {"$set": {"result": result}})
    return result


# ---------------------------------------------------------------- Comfy Cloud
async def comfy_upload(data: bytes, name: str) -> str:
    """Uploads are free on Comfy, so they work while the credit is out too."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else "png"
    return _save(data, ext)[len(PREFIX):]


async def comfy_submit(stage: str, workflow: str, prompt: dict) -> str:
    """Records what the job would draw: the prompt text, and for a clip its start
    image and length (read back from the filled workflow)."""
    from services.ai.comfy import WORKFLOWS

    if (await simulation()).get("comfy_locked"):
        from services import engine_health
        from services.ai import classify_http_error

        message = "PAYMENT_REQUIRED — Payment required - Insufficient credits"
        await engine_health.note_error(stage, message, provider="comfy", status=402, raw=COMFY_LOCK_BODY)
        raise classify_http_error(stage, "Comfy", 402, message)
    spec = WORKFLOWS[workflow]
    node, field = spec["prompt_input"]
    info = {"text": prompt[node]["inputs"][field]}
    if "start_input" in spec:
        node, field = spec["start_input"]
        info["start_image"] = prompt[node]["inputs"][field]
        node, field = spec["duration_input"]
        info["seconds"] = prompt[node]["inputs"][field]
    prompt_id = str(uuid.uuid4())
    # Persisted, so a restart in the middle resumes like a real queued job.
    await db.fake_requests.insert_one({"id": prompt_id, "kind": "comfy", "stage": stage, "workflow": workflow,
                                       "info": info, "created_at": _now(), "t0": time.time()})
    return prompt_id


async def comfy_job(prompt_id: str) -> dict:
    """The finished job (after the scaled wait), shaped like Comfy's GET /api/jobs/{id}."""
    from services.ai.comfy import WORKFLOWS

    req = await db.fake_requests.find_one({"id": prompt_id, "kind": "comfy"}, {"_id": 0})
    if not req:
        return {"id": prompt_id, "status": "failed", "execution_error": {
            "exception_type": "ServiceError", "exception_message": "rehearsal job not found", "node_type": "",
            "node_id": "", "traceback": [], "current_inputs": {}, "current_outputs": {}}}
    if req.get("job"):
        return req["job"]
    clip = req["workflow"] == "clip_wan22"
    kind = "comfy_clip" if clip else "comfy_keyframe"
    remaining = REAL_SECONDS[kind] * speed() - (time.time() - float(req.get("t0") or time.time()))
    if remaining > 0:
        await asyncio.sleep(remaining)
    start_ms = int(float(req.get("t0") or time.time()) * 1000)
    if (await simulation()).get("comfy_locked"):
        job = {"id": prompt_id, "status": "failed", "execution_start_time": start_ms,
               "execution_end_time": start_ms + 1000, "execution_error": {
                   "exception_type": "InsufficientFundsError", "exception_message": "Account balance too low",
                   "node_type": "", "node_id": "", "traceback": [], "current_inputs": {}, "current_outputs": {}}}
    else:
        info = req.get("info") or {}
        if clip:
            data = await asyncio.to_thread(_clip, read(PREFIX + info["start_image"]), int(info.get("seconds") or 5))
            name, mime = _save(data, "mp4")[len(PREFIX):], "video/mp4"
        else:
            name, mime = _save(picture(info.get("text") or "", "1536x864"), "png")[len(PREFIX):], "image/png"
        out = {"images": [{"filename": name, "subfolder": "rehearsal", "type": "output", "mime_type": mime}]}
        if clip:
            out["animated"] = [True]
        # GPU time as the real job would take, not the scaled wait: costs stay realistic.
        job = {"id": prompt_id, "status": "completed", "execution_start_time": start_ms,
               "execution_end_time": start_ms + REAL_SECONDS[kind] * 1000,
               "outputs": {WORKFLOWS[req["workflow"]]["output_node"]: out}}
    await db.fake_requests.update_one({"id": prompt_id}, {"$set": {"job": job}})
    return job


def comfy_download(filename: str) -> bytes:
    return read(PREFIX + filename)


async def comfy_balance() -> float:
    sim = await simulation()
    return 0.0 if sim.get("comfy_locked") else float(sim.get("comfy_balance_usd") or 20.0)
