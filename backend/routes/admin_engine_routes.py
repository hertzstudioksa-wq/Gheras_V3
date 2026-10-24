"""Admin: the engine layers behind every generation (M3).

  /api/admin/engine/styles             art style presets (the parent picks one in the builder)
  /api/admin/engine/dialects           narration dialect profiles: writing rules, TTS direction, voices
  /api/admin/engine/pacing             speaking rate, shot length, gaps, image quality per stage
  /api/admin/engine/system-prompts     versioned system prompts of the text stages
  /api/admin/orders/{id}/prompt-preview  exactly what each stage sends for an order

Every edit bumps the layer's version, keeps the previous copy in a *_versions
collection and writes an audit row; plans record the versions they used.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from auth import require_admin
from db import db
from services import engine_config, house_style
from services.audit_service import record_audit

router = APIRouter(prefix="/admin", tags=["admin-engine"], dependencies=[Depends(require_admin)])

KEY_RE = r"^[a-z][a-z0-9_]{1,39}$"
Quality = Literal["low", "medium", "high"]
IMAGE_STAGES = {
    "child_character_i2i": "شخصية الطفل من الصورة",
    "extra_character_i2i": "الشخصيات الإضافية",
    "scene_image_generation": "صور اللقطات",
    "book_page_image_generation": "صور صفحات الكتاب",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _audit(admin: dict, entity_type: str, entity_id: str, action: str, summary: str,
                 before: dict | None = None, after: dict | None = None) -> None:
    await record_audit(entity_type=entity_type, entity_id=entity_id, action=action, actor_id=admin.get("id"),
                       actor_email=admin.get("email"), summary=summary, before=before, after=after)


async def _save_version(collection: str, before: dict, admin: dict) -> None:
    """Keep the copy being replaced so older plans stay traceable."""
    await db[f"{collection}_versions"].insert_one({**before, "archived_at": _now(), "archived_by": admin.get("email")})


# ============================================================================
# ART STYLES
# ============================================================================
class StyleIn(BaseModel):
    key: str = Field(pattern=KEY_RE)
    name_ar: str = Field(min_length=2, max_length=60)
    description_ar: str = Field(default="", max_length=300)
    style_text: str = Field(min_length=40, max_length=3000)
    sheet_rules: str = Field(default=house_style.SHEET_RULES, max_length=2000)
    frame_rules: str = Field(default=house_style.FRAME_RULES, max_length=1000)
    motion_text: str = Field(default=house_style.MOTION_STYLE, max_length=1000)
    negative_text: str = Field(default=house_style.VIDEO_NEGATIVE, max_length=1000)
    palette: str = Field(default="", max_length=200)
    lighting: str = Field(default="", max_length=200)
    reference_image: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sort_order: int = 0
    active: bool = True


class StylePatch(BaseModel):
    name_ar: Optional[str] = Field(default=None, min_length=2, max_length=60)
    description_ar: Optional[str] = Field(default=None, max_length=300)
    style_text: Optional[str] = Field(default=None, min_length=40, max_length=3000)
    sheet_rules: Optional[str] = Field(default=None, max_length=2000)
    frame_rules: Optional[str] = Field(default=None, max_length=1000)
    motion_text: Optional[str] = Field(default=None, max_length=1000)
    negative_text: Optional[str] = Field(default=None, max_length=1000)
    palette: Optional[str] = Field(default=None, max_length=200)
    lighting: Optional[str] = Field(default=None, max_length=200)
    reference_image: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sort_order: Optional[int] = None
    active: Optional[bool] = None


def _check_image_ref(ref: str | None) -> None:
    if ref and not (ref.startswith(engine_config.ASSET_PREFIX) or ref.startswith("/api/uploads/file/")):
        raise HTTPException(status_code=400, detail="الصورة المرجعية لازم تكون ملف مرفوع على غراس")


@router.get("/engine/styles")
async def list_styles():
    return await db.style_presets.find({}, {"_id": 0}).sort([("sort_order", 1), ("created_at", 1)]).to_list(100)


@router.post("/engine/styles")
async def create_style(payload: StyleIn, admin: dict = Depends(require_admin)):
    if await db.style_presets.find_one({"key": payload.key}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="فيه ستايل بنفس المفتاح")
    _check_image_ref(payload.reference_image)
    doc = {**payload.model_dump(), "id": str(uuid.uuid4()), "is_default": False, "version": 1,
           "created_at": _now(), "updated_at": _now()}
    await db.style_presets.insert_one(doc)
    engine_config.invalidate()
    await _audit(admin, "style_preset", payload.key, "style.create", f"ستايل جديد: {payload.name_ar}")
    return await db.style_presets.find_one({"key": payload.key}, {"_id": 0})


@router.patch("/engine/styles/{key}")
async def update_style(key: str, payload: StylePatch, admin: dict = Depends(require_admin)):
    before = await db.style_presets.find_one({"key": key}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="الستايل غير موجود")
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="لا يوجد تعديل")
    _check_image_ref(patch.get("reference_image"))
    if patch.get("active") is False and before.get("is_default"):
        raise HTTPException(status_code=400, detail="الستايل الافتراضي ما ينفعش يتوقف — اختار افتراضي تاني الأول")
    await _save_version("style_presets", before, admin)
    patch.update({"version": (before.get("version") or 1) + 1, "updated_at": _now()})
    await db.style_presets.update_one({"key": key}, {"$set": patch})
    engine_config.invalidate()
    await _audit(admin, "style_preset", key, "style.update", f"تعديل ستايل {before.get('name_ar')}",
                 before={k: before.get(k) for k in patch if k not in ("updated_at",)},
                 after={k: v for k, v in patch.items() if k != "updated_at"})
    return await db.style_presets.find_one({"key": key}, {"_id": 0})


@router.post("/engine/styles/{key}/make-default")
async def make_default_style(key: str, admin: dict = Depends(require_admin)):
    style = await db.style_presets.find_one({"key": key}, {"_id": 0})
    if not style or not style.get("active"):
        raise HTTPException(status_code=404, detail="الستايل غير موجود أو متوقف")
    await db.style_presets.update_many({"is_default": True}, {"$set": {"is_default": False}})
    await db.style_presets.update_one({"key": key}, {"$set": {"is_default": True, "updated_at": _now()}})
    engine_config.invalidate()
    await _audit(admin, "style_preset", key, "style.default", f"الستايل الافتراضي بقى {style.get('name_ar')}")
    return {"ok": True}


@router.get("/engine/styles/{key}/reference")
async def style_reference_image(key: str):
    """The style's reference image (for the admin page; the frontend fetches it with the admin token)."""
    style = await db.style_presets.find_one({"key": key}, {"_id": 0})
    data = await engine_config.style_reference_bytes(style or {})
    if not data:
        raise HTTPException(status_code=404, detail="لا توجد صورة مرجعية")
    return Response(content=data, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})


@router.get("/engine/styles/{key}/versions")
async def style_versions(key: str):
    return await db.style_presets_versions.find({"key": key}, {"_id": 0}).sort("version", -1).to_list(50)


# ============================================================================
# DIALECTS
# ============================================================================
class Voices(BaseModel):
    male: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{1,40}$")
    female: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{1,40}$")


# Gemini TTS reads long or multi-line directions aloud (it voiced a whole
# paragraph of instructions in the M2 test), so the direction stays one short line.
TTS_DIRECTION = Field(min_length=10, max_length=160, pattern=r"^[^\n\r]+$")


class DialectIn(BaseModel):
    key: str = Field(pattern=KEY_RE)
    name_ar: str = Field(min_length=2, max_length=40)
    writing_rules: str = Field(min_length=20, max_length=2000)
    tts_direction: str = TTS_DIRECTION
    voices: Voices
    active: bool = True


class DialectPatch(BaseModel):
    name_ar: Optional[str] = Field(default=None, min_length=2, max_length=40)
    writing_rules: Optional[str] = Field(default=None, min_length=20, max_length=2000)
    tts_direction: Optional[str] = Field(default=None, min_length=10, max_length=160, pattern=r"^[^\n\r]+$")
    voices: Optional[Voices] = None
    active: Optional[bool] = None


@router.get("/engine/dialects")
async def list_dialects():
    from services.tts_service import GEMINI_VOICES
    items = await db.dialect_profiles.find({}, {"_id": 0}).sort("created_at", 1).to_list(50)
    options = await db.story_options.find({"kind": "language"}, {"_id": 0, "name_ar": 1, "value": 1}).to_list(50)
    return {"items": items, "voice_suggestions": GEMINI_VOICES, "default_key": house_style.DEFAULT_DIALECT,
            # Which builder language option feeds which dialect (option value → profile key).
            "language_options": [{**o, "dialect_key": house_style._OPTION_TO_DIALECT.get(o.get("value"), o.get("value"))}
                                 for o in options]}


@router.post("/engine/dialects")
async def create_dialect(payload: DialectIn, admin: dict = Depends(require_admin)):
    if await db.dialect_profiles.find_one({"key": payload.key}, {"_id": 1}):
        raise HTTPException(status_code=409, detail="فيه لهجة بنفس المفتاح")
    doc = {**payload.model_dump(), "id": str(uuid.uuid4()), "version": 1, "created_at": _now(), "updated_at": _now()}
    await db.dialect_profiles.insert_one(doc)
    engine_config.invalidate()
    await _audit(admin, "dialect_profile", payload.key, "dialect.create", f"لهجة جديدة: {payload.name_ar}")
    return await db.dialect_profiles.find_one({"key": payload.key}, {"_id": 0})


@router.patch("/engine/dialects/{key}")
async def update_dialect(key: str, payload: DialectPatch, admin: dict = Depends(require_admin)):
    before = await db.dialect_profiles.find_one({"key": key}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="اللهجة غير موجودة")
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="لا يوجد تعديل")
    if patch.get("active") is False and key == house_style.DEFAULT_DIALECT:
        raise HTTPException(status_code=400, detail="الفصحى هي اللهجة الاحتياطية وما ينفعش تتوقف")
    await _save_version("dialect_profiles", before, admin)
    patch.update({"version": (before.get("version") or 1) + 1, "updated_at": _now()})
    await db.dialect_profiles.update_one({"key": key}, {"$set": patch})
    engine_config.invalidate()
    await _audit(admin, "dialect_profile", key, "dialect.update", f"تعديل لهجة {before.get('name_ar')}",
                 before={k: before.get(k) for k in patch if k != "updated_at"},
                 after={k: v for k, v in patch.items() if k != "updated_at"})
    return await db.dialect_profiles.find_one({"key": key}, {"_id": 0})


# ============================================================================
# PACING + IMAGE QUALITY
# ============================================================================
class PacingPatch(BaseModel):
    words_per_second: Optional[float] = Field(default=None, ge=1.2, le=3.0)
    shot_seconds: Optional[float] = Field(default=None, ge=3, le=10)
    line_gap_sec: Optional[float] = Field(default=None, ge=0, le=1.5)
    end_tail_sec: Optional[float] = Field(default=None, ge=0, le=4)
    five_second_stretch: Optional[float] = Field(default=None, ge=1.0, le=1.6)
    image_quality: Optional[dict[str, Quality]] = None


@router.get("/engine/pacing")
async def get_pacing():
    return {"values": await engine_config.get_pacing(), "defaults": engine_config.DEFAULT_PACING,
            "image_stages": IMAGE_STAGES}


@router.patch("/engine/pacing")
async def update_pacing(payload: PacingPatch, admin: dict = Depends(require_admin)):
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="لا يوجد تعديل")
    unknown = set(patch.get("image_quality") or {}) - set(IMAGE_STAGES)
    if unknown:
        raise HTTPException(status_code=400, detail=f"مرحلة غير معروفة: {', '.join(sorted(unknown))}")
    before = await db.engine_settings.find_one({"id": "default"}, {"_id": 0}) or {}
    if before:
        await _save_version("engine_settings", before, admin)
    if "image_quality" in patch:
        patch["image_quality"] = {**(before.get("image_quality") or {}), **patch["image_quality"]}
    patch.update({"version": (before.get("version") or 1) + 1, "updated_at": _now()})
    await db.engine_settings.update_one({"id": "default"}, {"$set": patch}, upsert=True)
    engine_config.invalidate()
    await _audit(admin, "engine_settings", "default", "pacing.update", "تعديل إيقاع القصة وجودة الصور",
                 before={k: before.get(k) for k in patch if k != "updated_at"},
                 after={k: v for k, v in patch.items() if k != "updated_at"})
    return await engine_config.get_pacing()


# ============================================================================
# SYSTEM PROMPTS (text stages)
# ============================================================================
def _system_stages() -> dict[str, dict]:
    from services import production_service, scenario_service
    return {
        "scenario_generation": {"name_ar": "توليد السيناريوهات", "default": scenario_service.SYSTEM_MSG,
                                "must_contain": []},
        # The plan validator needs these keys, so a rewritten prompt must still ask for them.
        "production_planning": {"name_ar": "خطة الإنتاج", "default": production_service.SYSTEM_MSG,
                                "must_contain": ["production_plan", "scenes", "shots", "narration_line"]},
    }


def _stage_or_404(stage: str) -> dict:
    stages = _system_stages()
    if stage not in stages:
        raise HTTPException(status_code=404, detail="مرحلة غير معروفة")
    return stages[stage]


class SystemPromptIn(BaseModel):
    template_text: str = Field(min_length=200, max_length=60000)
    name: str = Field(default="", max_length=120)
    activate: bool = True


@router.get("/engine/system-prompts")
async def list_system_prompts():
    out = []
    for stage, meta in _system_stages().items():
        versions = await db.prompt_templates.find(
            {"stage_key": f"{stage}{engine_config.SYSTEM_SUFFIX}"}, {"_id": 0}).sort("version", -1).to_list(50)
        out.append({"stage": stage, "name_ar": meta["name_ar"], "code_default": meta["default"],
                    "must_contain": meta["must_contain"],
                    "active": next((v for v in versions if v.get("active")), None), "versions": versions})
    return out


@router.post("/engine/system-prompts/{stage}")
async def create_system_prompt(stage: str, payload: SystemPromptIn, admin: dict = Depends(require_admin)):
    meta = _stage_or_404(stage)
    missing = [w for w in meta["must_contain"] if w not in payload.template_text]
    if missing:
        raise HTTPException(status_code=400, detail=f"البرومبت لازم يطلب الحقول دي: {', '.join(missing)}")
    stage_key = f"{stage}{engine_config.SYSTEM_SUFFIX}"
    last = await db.prompt_templates.find_one({"stage_key": stage_key}, {"_id": 0, "version": 1}, sort=[("version", -1)])
    doc = {
        "id": str(uuid.uuid4()), "stage_key": stage_key,
        "name": payload.name or f"{meta['name_ar']} — برومبت النظام",
        "template_text": payload.template_text, "variables": [],
        "version": (last["version"] + 1) if last else 1, "active": False,
        "created_at": _now(), "updated_at": _now(), "created_by": admin.get("email"),
    }
    await db.prompt_templates.insert_one(doc)
    if payload.activate:
        await _activate_system_prompt(stage_key, doc["id"])
    await _audit(admin, "system_prompt", stage, "system_prompt.create",
                 f"نسخة {doc['version']} من برومبت نظام {meta['name_ar']}" + (" (مفعّلة)" if payload.activate else ""))
    return await db.prompt_templates.find_one({"id": doc["id"]}, {"_id": 0})


async def _activate_system_prompt(stage_key: str, prompt_id: str) -> None:
    await db.prompt_templates.update_many({"stage_key": stage_key, "active": True},
                                          {"$set": {"active": False, "updated_at": _now()}})
    await db.prompt_templates.update_one({"id": prompt_id}, {"$set": {"active": True, "updated_at": _now()}})


@router.post("/engine/system-prompts/{stage}/activate/{prompt_id}")
async def activate_system_prompt(stage: str, prompt_id: str, admin: dict = Depends(require_admin)):
    meta = _stage_or_404(stage)
    stage_key = f"{stage}{engine_config.SYSTEM_SUFFIX}"
    doc = await db.prompt_templates.find_one({"id": prompt_id, "stage_key": stage_key}, {"_id": 0, "version": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="النسخة غير موجودة")
    await _activate_system_prompt(stage_key, prompt_id)
    await _audit(admin, "system_prompt", stage, "system_prompt.activate",
                 f"تفعيل نسخة {doc.get('version')} من برومبت نظام {meta['name_ar']}")
    return {"ok": True}


@router.post("/engine/system-prompts/{stage}/reset")
async def reset_system_prompt(stage: str, admin: dict = Depends(require_admin)):
    """Back to the text shipped with the code (admin versions stay in history)."""
    meta = _stage_or_404(stage)
    await db.prompt_templates.update_many(
        {"stage_key": f"{stage}{engine_config.SYSTEM_SUFFIX}", "active": True},
        {"$set": {"active": False, "updated_at": _now()}})
    await _audit(admin, "system_prompt", stage, "system_prompt.reset", f"رجوع برومبت نظام {meta['name_ar']} للنص الأصلي")
    return {"ok": True}


# ============================================================================
# PROMPT PREVIEW — what each stage sends for one order, with the settings as they are now
# ============================================================================
@router.get("/orders/{order_id}/prompt-preview")
async def prompt_preview(order_id: str):
    from services import shot_pipeline
    from services.child_character_service import _resolve_prompt_safely
    from services.config_service import resolve_model, video_tier_of, VIDEO_TIERS
    from services.production_service import build_planning_request, target_scene_count
    from services.scenario_service import build_scenario_request

    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    style = await engine_config.style_for_order(order)
    dialect = await engine_config.get_dialect(await house_style.dialect_for_order(order))
    pacing = await engine_config.get_pacing()
    out: dict = {
        "layers": {
            "style": {k: style.get(k) for k in ("key", "name_ar", "version", "reference_image")},
            "dialect": {k: dialect.get(k) for k in ("key", "name_ar", "version", "tts_direction", "voices")},
            "narrator": await house_style.narrator_for_order(order),
            "pacing": pacing,
            "video_tier": video_tier_of(order),
            "story_fragments": (await engine_config.story_fragments(order)).strip(),
        },
        "stages": {},
    }

    async def stage(name: str, coro):
        try:
            out["stages"][name] = await coro
        except Exception as e:  # noqa: BLE001 — one stage failing to compose doesn't hide the others
            out["stages"][name] = {"error": f"{type(e).__name__}: {e}"}

    async def scenarios():
        r = await build_scenario_request(order)
        return {"model": r["trace"]["model"], "system": r["system"], "user": r["user"], "trace": r["trace"]}

    await stage("scenario_generation", scenarios())

    scenario = order.get("selected_scenario_snapshot")
    if scenario:
        async def planning():
            r = await build_planning_request(order, scenario, target_scene_count(order, scenario))
            return {"model": r["trace"]["model"], "system": r["system"], "user": r["user"], "trace": r["trace"]}
        await stage("production_planning", planning())

    plan = await db.production_plans.find_one({"id": order.get("production_plan_id")}, {"_id": 0}) \
        if order.get("production_plan_id") else None

    async def child_sheet():
        prompt, source = await _resolve_prompt_safely(order, plan, style)
        provider, model, _ = await resolve_model("child_character_i2i", "openai", "gpt-image-2")
        return {"model": f"{provider}/{model}", "prompt": prompt, "prompt_source": source,
                "quality": house_style.image_quality("child_character_i2i", pacing["image_quality"]),
                "references": ["child photo"] + (["style reference image"] if style.get("reference_image") else [])}

    await stage("child_character_i2i", child_sheet())

    if plan:
        out["plan_trace"] = plan.get("engine_trace")

        async def shots():
            scenes = await shot_pipeline._scenes(order, plan)
            profiles = await shot_pipeline._profiles(plan)
            sheets = await shot_pipeline.load_character_sheets(order, plan)
            used = {(r["scene_index"], r["shot_index"]): r
                    for r in await shot_pipeline.shot_rows(order["id"], plan["id"])}
            child_name = ((order.get("data") or {}).get("child") or {}).get("name") or ""
            provider, model, _ = await resolve_model("video_generation", "kling", shot_pipeline.KLING_DEFAULT)
            tier = video_tier_of(order)
            if VIDEO_TIERS[tier]["model_name"]:
                model = VIDEO_TIERS[tier]["model_name"]
            rows = []
            for sc in scenes:
                for sh in sc.get("shots") or []:
                    notes = [f"{sheets[t]['label']}'s character sheet"
                             for t in (sh.get("characters") or []) if t in sheets][:shot_pipeline.MAX_ELEMENTS]
                    if sh["shot_index"] > 1:
                        notes.append(shot_pipeline.PREV_SHOT_NOTE)
                    elif sc["scene_index"] > 1:
                        notes.append(shot_pipeline.PREV_SCENE_NOTE)
                    mapping = [f"{sheets[t]['label']} is @Element{i + 1}"
                               for i, t in enumerate([t for t in (sh.get("characters") or []) if t in sheets]
                                                     [:shot_pipeline.MAX_ELEMENTS])] if "/v3/" in model else []
                    row = used.get((sc["scene_index"], sh["shot_index"])) or {}
                    rows.append({
                        "scene_index": sc["scene_index"], "shot_index": sh["shot_index"],
                        "narration_line": sh.get("narration_line"),
                        "keyframe_prompt": shot_pipeline.keyframe_prompt(sc, sh, profiles, sheets, child_name, notes,
                                                                         style),
                        "keyframe_prompt_used": row.get("keyframe_prompt_used"),
                        "motion_prompt": shot_pipeline.motion_prompt(sh.get("motion_prompt"), mapping, style),
                        "motion_prompt_used": row.get("clip_prompt_used"),
                        "negative_prompt": style["negative_text"],
                    })
            return {"image_model": "scene_image_generation",
                    "image_quality": house_style.image_quality("scene_image_generation", pacing["image_quality"]),
                    "video_model": f"{provider}/{model}", "shots": rows}

        await stage("shots", shots())
    return out
