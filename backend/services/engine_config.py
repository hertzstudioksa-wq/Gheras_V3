"""Admin-editable engine layers: art styles, dialect profiles, pacing and image quality.

The defaults are the house_style constants the owner approved (M1 lab + the
likeness bake-off); they are seeded once into the database and from then on the
admin edits them there. Getters cache for a few seconds, so a change applies to
the next generation without restarting anything, and fall back to the code
defaults if the database has nothing.

  style_presets     one doc per art style (style/sheet/frame/motion/negative text +
                    a style reference image); one is the default
  dialect_profiles  one doc per narration dialect (writing rules for the plan,
                    TTS direction, narrator voices)
  engine_settings   pacing and per-stage image quality (doc id "default")
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from db import db
from services import house_style

CACHE_SECONDS = 10
SOFT_STYLE_KEY = "storybook_soft"
DEFAULT_STYLE_KEY = "storybook_natural"
NATURAL_DEFAULT_MIGRATION = "style_natural_default"
ASSET_PREFIX = "asset:"  # reference image shipped with the code (backend/assets/styles/)

SOFT_STYLE = {
    "key": SOFT_STYLE_KEY,
    "name_ar": "ستوري بوك ناعم",
    "description_ar": "كرتون ثنائي الأبعاد ناعم بخطوط أنيقة وتظليل رسم يدوي وألوان دافئة.",
    "style_text": house_style.STYLE,
    "sheet_rules": house_style.SHEET_RULES,
    "frame_rules": house_style.FRAME_RULES,
    "motion_text": house_style.MOTION_STYLE,
    "negative_text": house_style.VIDEO_NEGATIVE,
    "palette": "warm appealing colors",
    "lighting": "soft warm storybook lighting",
    "reference_image": f"{ASSET_PREFIX}storybook_soft.png",
    "thumbnail_url": None,
    "is_default": False,
    "active": False,
}
# The owner's pick (2026-10-28): children and adults in one drawing (house_style.STYLE_NATURAL).
DEFAULT_STYLE = {
    **SOFT_STYLE,
    "key": DEFAULT_STYLE_KEY,
    "name_ar": "ستوري بوك طبيعي",
    "description_ar": "رسم ستوري بوك واحد للكبار والصغار: عيون بحجم طبيعي، ملامح حقيقية مبسّطة، وتظليل رسم يدوي "
                      "بألوان دافئة.",
    "style_text": house_style.STYLE_NATURAL,
    "reference_image": f"{ASSET_PREFIX}storybook_natural.png",
    "is_default": True,
    "active": True,
}

DEFAULT_PACING = {
    "id": "default",
    "words_per_second": house_style.WORDS_PER_SECOND,
    "shot_seconds": house_style.SHOT_SECONDS,
    "line_gap_sec": house_style.LINE_GAP_SEC,
    "end_tail_sec": house_style.END_TAIL_SEC,
    "five_second_stretch": house_style.FIVE_SECOND_STRETCH,
    "image_quality": dict(house_style.IMAGE_QUALITY),
}

_cache: dict[str, tuple[float, object]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def invalidate() -> None:
    _cache.clear()


async def _cached(key: str, loader):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    value = await loader()
    _cache[key] = (time.monotonic(), value)
    return value


# ---------------------------------------------------------------- seeding
async def seed_engine_config() -> None:
    """Insert the approved defaults once (never overwrites admin edits)."""
    now = _now()
    for preset in (SOFT_STYLE, DEFAULT_STYLE):
        if not await db.style_presets.find_one({"key": preset["key"]}, {"_id": 1}):
            await db.style_presets.insert_one({**preset, "is_default": False, "id": str(uuid.uuid4()), "version": 1,
                                               "created_at": now, "updated_at": now})
    # Once per database: the natural style becomes the default and the soft one leaves the
    # parents' choices (with it, cute children stood next to real-featured grown-ups again).
    # The admin may change either afterwards; a later boot never switches it back.
    if not await db.migrations.find_one({"id": NATURAL_DEFAULT_MIGRATION}, {"_id": 1}):
        await db.style_presets.update_many({"key": {"$ne": DEFAULT_STYLE_KEY}}, {"$set": {"is_default": False}})
        await db.style_presets.update_one({"key": SOFT_STYLE_KEY}, {"$set": {"active": False, "updated_at": now}})
        await db.style_presets.update_one({"key": DEFAULT_STYLE_KEY},
                                          {"$set": {"is_default": True, "active": True, "updated_at": now}})
        await db.migrations.update_one({"id": NATURAL_DEFAULT_MIGRATION},
                                       {"$setOnInsert": {"id": NATURAL_DEFAULT_MIGRATION, "applied_at": now}},
                                       upsert=True)
    # The natural style's first wording drew children with big heads: a preset still
    # holding it word for word gets the new one (an admin's own wording is left alone).
    await db.style_presets.update_one({"key": DEFAULT_STYLE_KEY, "style_text": house_style.STYLE_NATURAL_V1},
                                      {"$set": {"style_text": house_style.STYLE_NATURAL, "updated_at": now}})
    for key, d in house_style.DIALECTS.items():
        if not await db.dialect_profiles.find_one({"key": key}, {"_id": 1}):
            await db.dialect_profiles.insert_one({
                "id": str(uuid.uuid4()), "key": key, "name_ar": d["name_ar"], "writing_rules": d["writing"],
                "tts_direction": d["tts_direction"], "voices": dict(d["voices"]), "active": True,
                "version": 1, "created_at": now, "updated_at": now,
            })
    if not await db.engine_settings.find_one({"id": "default"}, {"_id": 1}):
        await db.engine_settings.insert_one({**DEFAULT_PACING, "version": 1, "created_at": now, "updated_at": now})
    invalidate()


# ---------------------------------------------------------------- styles
async def get_style(key: str | None = None) -> dict:
    """The requested active style, else the default one, else the code default."""
    async def load():
        docs = await db.style_presets.find({"active": True}, {"_id": 0}).to_list(50)
        return docs
    docs = await _cached("styles", load)
    by_key = {d["key"]: d for d in docs}
    if key and key in by_key:
        return {**DEFAULT_STYLE, **by_key[key]}
    default = next((d for d in docs if d.get("is_default")), None) or by_key.get(DEFAULT_STYLE_KEY)
    return {**DEFAULT_STYLE, **(default or {})}


async def style_for_order(order: dict) -> dict:
    """The art style the parent picked (data.style.art_style), else the default."""
    return await get_style(((order.get("data") or {}).get("style") or {}).get("art_style"))


async def style_reference_bytes(style: dict) -> bytes | None:
    ref = style.get("reference_image") or ""
    if ref.startswith(ASSET_PREFIX):
        path = house_style.STYLE_REF_PATH.parent / ref[len(ASSET_PREFIX):]
        try:
            return path.read_bytes()
        except OSError:
            return None
    if ref.startswith("/api/uploads/file/"):
        from services.child_character_service import _fetch_source_bytes
        got = await _fetch_source_bytes(ref)
        return got[0] if got else None
    return None


def style_guide(style: dict) -> dict:
    """The plan's style_guide (feeds legacy prompt builders and the storyboard)."""
    return {"art_direction": style.get("style_text") or DEFAULT_STYLE["style_text"],
            "palette": style.get("palette") or "", "lighting": style.get("lighting") or "",
            "style_key": style.get("key"), "style_version": style.get("version")}


# ---------------------------------------------------------------- dialects
async def get_dialect(key: str) -> dict:
    """Dialect profile in the shape the engine uses: name_ar, writing, tts_direction, voices."""
    async def load():
        return {d["key"]: d for d in await db.dialect_profiles.find({"active": True}, {"_id": 0}).to_list(20)}
    docs = await _cached("dialects", load)
    code = house_style.DIALECTS.get(key) or house_style.DIALECTS[house_style.DEFAULT_DIALECT]
    d = docs.get(key) or {}
    return {
        "key": key if (key in docs or key in house_style.DIALECTS) else house_style.DEFAULT_DIALECT,
        "name_ar": d.get("name_ar") or code["name_ar"],
        "writing": d.get("writing_rules") or code["writing"],
        "tts_direction": d.get("tts_direction") or code["tts_direction"],
        "voices": {**code["voices"], **(d.get("voices") or {})},
        "version": d.get("version"),
    }


# ---------------------------------------------------------------- pacing
async def get_pacing() -> dict:
    async def load():
        return await db.engine_settings.find_one({"id": "default"}, {"_id": 0}) or {}
    doc = await _cached("pacing", load)
    merged = {**DEFAULT_PACING, **{k: v for k, v in doc.items() if v is not None}}
    merged["image_quality"] = {**DEFAULT_PACING["image_quality"], **(doc.get("image_quality") or {})}
    return merged


# ---------------------------------------------------------------- story layer
async def story_fragments(order: dict) -> str:
    """Admin direction attached to the parent's choices (value category / topic /
    story type / tone / setting), appended to the scenario and plan prompts."""
    data = order.get("data") or {}
    goal, style = data.get("goal") or {}, data.get("style") or {}
    picks = []
    if goal.get("category_id"):
        picks.append(("التصنيف", await db.categories.find_one({"id": goal["category_id"]}, {"_id": 0})))
    if goal.get("subcategory_id"):
        picks.append(("الموضوع", await db.subcategories.find_one({"id": goal["subcategory_id"]}, {"_id": 0})))
    for field, label in (("type_id", "نوع القصة"), ("tone_id", "النبرة"), ("setting_id", "البيئة")):
        if style.get(field):
            picks.append((label, await db.story_options.find_one({"id": style[field]}, {"_id": 0})))
    lines = [f"- {label} ({doc.get('name_ar') or doc.get('name') or ''}): {doc['prompt_fragment'].strip()}"
             for label, doc in picks if doc and (doc.get("prompt_fragment") or "").strip()]
    return ("\n\n## توجيهات الإدارة لاختيارات ولي الأمر\n" + "\n".join(lines)) if lines else ""


# ---------------------------------------------------------------- stage system prompts
SYSTEM_SUFFIX = ".system"  # prompt_templates.stage_key for a stage's system prompt


async def system_prompt(stage: str, default: str) -> tuple[str, dict]:
    """Active admin system prompt for a stage (versioned in prompt_templates), else the code default."""
    doc = await db.prompt_templates.find_one({"stage_key": f"{stage}{SYSTEM_SUFFIX}", "active": True},
                                             {"_id": 0, "id": 1, "template_text": 1, "version": 1})
    if doc and (doc.get("template_text") or "").strip():
        return doc["template_text"], {"source": "admin", "id": doc["id"], "version": doc.get("version")}
    return default, {"source": "code"}
