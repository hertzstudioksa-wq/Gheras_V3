"""Admin: the engine layers behind every generation (M3).

  /api/admin/engine/styles             art style presets (the parent picks one in the builder)
  /api/admin/engine/dialects           narration dialect profiles: writing rules, TTS direction, voices
  /api/admin/engine/pacing             speaking rate, shot length, gaps, image quality per stage
  /api/admin/engine/system-prompts     versioned system prompts of the text stages
  /api/admin/orders/{id}/prompt-preview  exactly what each stage sends for an order
  /api/admin/engine/stages             each stage's catalog model, key, switch; test; reset (M4)
  /api/admin/engine/video-premium      the model the "فاخر" video tier renders with (M4)
  /api/admin/engine/presets/{id}/apply ready-made model sets made only of catalog models (M4)
  /api/admin/engine/catalog            the model catalog: what each model costs and can do (M4)
  /api/admin/engine/prompt-templates   the user-message templates generation reads, versioned (M5)
  /api/admin/overview                  operations home: what needs attention, KPIs, engine health (M5)

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
    from services.config_service import resolve_model, video_tier_of
    from services.model_catalog import video_model_for_tier
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
            provider, model = await video_model_for_tier(video_tier_of(order))
            image_provider, image_model = await shot_pipeline.keyframe_engine()
            on_comfy = image_provider == "comfy_image"
            toy = shot_pipeline.favourite_toy(order) if on_comfy else None
            objects = shot_pipeline.story_objects(plan, toy)
            rows = []
            for sc in scenes:
                for sh in sc.get("shots") or []:
                    notes = [f"{sheets[t]['label']}'s character sheet" for t in shot_pipeline.by_likeness(
                        sh.get("characters") or [], sheets)[:shot_pipeline.MAX_KEYFRAME_SHEETS]]
                    previous = "shot" if sh["shot_index"] > 1 else "scene" if sc["scene_index"] > 1 else None
                    if previous == "shot":
                        notes.append(shot_pipeline.PREV_SHOT_NOTE)
                    elif previous == "scene":
                        notes.append(shot_pipeline.PREV_SCENE_NOTE)
                    in_shot = shot_pipeline.shot_objects(sh, objects)
                    # On Comfy every story object gets its reference before the keyframes.
                    comfy_refs = shot_pipeline.comfy_references(sh, sc, sheets, toy, previous, in_shot) \
                        if on_comfy else []
                    mapping = [f"{sheets[t]['label']} is @Element{i + 1}" for i, t in enumerate(
                        shot_pipeline.by_likeness(sh.get("characters") or [], sheets)[:shot_pipeline.MAX_ELEMENTS])
                    ] if "/v3/" in model else []
                    row = used.get((sc["scene_index"], sh["shot_index"])) or {}
                    rows.append({
                        "scene_index": sc["scene_index"], "shot_index": sh["shot_index"],
                        "narration_line": sh.get("narration_line"),
                        "keyframe_prompt": shot_pipeline.keyframe_prompt_comfy(sc, sh, profiles, sheets, child_name,
                                                                               comfy_refs, in_shot) if on_comfy else
                        shot_pipeline.keyframe_prompt(sc, sh, profiles, sheets, child_name, notes, style, in_shot),
                        "keyframe_references": shot_pipeline.describe_refs(comfy_refs, sheets) if on_comfy else
                        [f"<image{i + 1}> {n}" for i, n in enumerate(notes)],
                        "keyframe_prompt_used": row.get("keyframe_prompt_used"),
                        "motion_prompt": shot_pipeline.wan_motion_prompt(
                            sh.get("motion_prompt"), len(set(sh.get("characters") or [])))
                        if provider == "comfy_video" else shot_pipeline.motion_prompt(
                            sh.get("motion_prompt"), mapping, style,
                            shot_pipeline.cast_labels(sh.get("characters") or [], sheets)),
                        "motion_prompt_used": row.get("clip_prompt_used"),
                        # Wan on Comfy runs at CFG 1: a negative prompt does nothing there.
                        "negative_prompt": None if provider == "comfy_video" else shot_pipeline.clip_negative(style),
                    })
            return {"image_model": f"{image_provider}/{image_model}", "image_on_comfy": on_comfy,
                    "image_quality": house_style.image_quality("scene_image_generation", pacing["image_quality"]),
                    "video_model": f"{provider}/{model}", "shots": rows}

        await stage("shots", shots())
    return out


# ============================================================================
# STAGES & MODELS (M4) — which catalog model each stage uses
# ============================================================================
class StageModelPatch(BaseModel):
    provider: Optional[str] = None
    model_name: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/engine/stages")
async def engine_stages():
    from services import model_catalog
    from services.preset_stacks_service import list_presets

    premium = await model_catalog.premium_video_model()
    presets = []
    for p in await list_presets():
        if p.get("is_archived") or not await model_catalog.preset_is_valid(p):
            continue
        presets.append({"id": p["id"], "name": p.get("name"), "description": p.get("description"),
                        "intended_use": p.get("intended_use"), "is_active": bool(p.get("is_active")),
                        "is_seeded": bool(p.get("is_seeded")),
                        "stages": sorted((p.get("stage_map") or {}).keys())})
    return {
        "stages": await model_catalog.stage_rows(),
        "premium_video": {"model_name": premium, "entry": await model_catalog.find_model("kling", premium)},
        "presets": presets,
        "catalog": await model_catalog.list_catalog(include_inactive=False),
        "capability_labels": model_catalog.CAPABILITY_LABELS,
        "statuses": model_catalog.STATUSES,
    }


async def _stage_row(stage: str) -> dict | None:
    from services import model_catalog

    return next((r for r in await model_catalog.stage_rows() if r["stage_key"] == stage), None)


@router.patch("/engine/stages/{stage}")
async def patch_engine_stage(stage: str, payload: StageModelPatch, admin: dict = Depends(require_admin)):
    from services import model_catalog

    try:
        if payload.enabled is not None:
            await model_catalog.set_stage_enabled(stage, payload.enabled, admin)
        if payload.provider and payload.model_name:
            await model_catalog.set_stage_model(stage, payload.provider, payload.model_name, admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _stage_row(stage)


@router.post("/engine/stages/{stage}/reset")
async def reset_engine_stage(stage: str, admin: dict = Depends(require_admin)):
    from services import model_catalog
    from services.config_service import DEFAULT_MODELS

    if stage not in model_catalog.CAPABILITY_OF_STAGE:
        raise HTTPException(status_code=404, detail="مرحلة غير معروفة")
    d = DEFAULT_MODELS[stage]
    try:
        await model_catalog.set_stage_model(stage, d["provider"], d["model_name"], admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _stage_row(stage)


# Key / connection checks (no generation, nothing billed).
_DIRECT_TESTS = {"anthropic": "anthropic", "openai": "openai", "gemini": "gemini", "gemini_tts": "gemini",
                 "elevenlabs": "elevenlabs", "comfy_image": "comfy", "comfy_video": "comfy"}


# ============================================================================
# ENGINE HEALTH (fal balance)
# ============================================================================
@router.get("/engine/health")
async def engine_health_status():
    from services import engine_health

    return await engine_health.status(fresh=True)


@router.post("/engine/health/probe")
async def engine_health_probe():
    """A real few-token request: the only check that sees an exhausted balance."""
    from services import engine_health

    return {**await engine_health.probe(), **await engine_health.status(fresh=True)}


@router.post("/engine/resume-paused")
async def engine_resume_paused(admin: dict = Depends(require_admin)):
    from services import engine_health

    result = await engine_health.resume_paused(admin.get("id"))
    if not result["ok"]:
        raise HTTPException(status_code=409, detail=f"لسه مش شغّال: {result['error']}")
    await _audit(admin, "engine", "fal", "engine.resume_paused",
                 f"استكمال {len(result['resumed'])} طلب موقوف بعد شحن الرصيد",
                 after={"resumed": result["resumed"], "skipped": result["skipped"]})
    return result


@router.post("/engine/stages/{stage}/test")
async def test_engine_stage(stage: str):
    from services.provider_test_service import _test_fal_key, test_provider

    row = await _stage_row(stage)
    if not row or not row["selectable"]:
        raise HTTPException(status_code=404, detail="مرحلة غير معروفة أو محلية")
    provider, key = row["provider"], row["key"]
    if provider in _DIRECT_TESTS:
        result = await test_provider(_DIRECT_TESTS[provider])
    elif (key.get("env_key") or "").startswith("FAL_KEY"):
        # The key fal would actually use (a capability key falls back to the others).
        result = await _test_fal_key(key.get("shared_from") or key["env_key"], provider)
    else:
        raise HTTPException(status_code=400, detail="مفيش اختبار للمزوّد ده")
    return {"stage": stage, "provider": provider, "model_name": row["model_name"],
            "ok": bool(result.get("ok")), "latency_ms": result.get("latency_ms"),
            "error": result.get("error"), "key_source": key["source"]}


class PremiumVideoIn(BaseModel):
    model_name: str


@router.put("/engine/video-premium")
async def set_video_premium(payload: PremiumVideoIn, admin: dict = Depends(require_admin)):
    from services import model_catalog

    try:
        entry = await model_catalog.set_premium_video_model(payload.model_name, admin)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"model_name": payload.model_name, "entry": entry}


class PresetSaveIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(default="", max_length=300)


@router.post("/engine/presets")
async def save_engine_preset(payload: PresetSaveIn, admin: dict = Depends(require_admin)):
    """Save the models every stage uses right now as a ready-made set (AF-21)."""
    from services import model_catalog
    from services.preset_stacks_service import create_preset

    rows = await model_catalog.stage_rows()
    stage_map = {r["stage_key"]: {"provider": r["provider"], "model_name": r["model_name"],
                                  "env_key": model_catalog.env_key_for(r["provider"])}
                 for r in rows if r["stage_key"] in model_catalog.CAPABILITY_OF_STAGE}
    try:
        p = await create_preset({"name": payload.name.strip(), "description": payload.description.strip(),
                                 "stage_map": stage_map}, admin.get("id"), admin.get("email"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    p.pop("_id", None)
    return {"ok": True, "preset": p}


@router.delete("/engine/presets/{preset_id}")
async def delete_engine_preset(preset_id: str, admin: dict = Depends(require_admin)):
    """Admin-made sets only; the seeded ones stay."""
    from services.preset_stacks_service import delete_preset, get_preset

    p = await get_preset(preset_id)
    if not p:
        raise HTTPException(status_code=404, detail="المجموعة غير موجودة")
    if p.get("is_seeded"):
        raise HTTPException(status_code=400, detail="المجموعات الأساسية ما تتمسحش")
    await delete_preset(preset_id, admin.get("id"), admin.get("email"))
    return {"ok": True}


@router.post("/engine/presets/{preset_id}/apply")
async def apply_engine_preset(preset_id: str, admin: dict = Depends(require_admin)):
    """Apply a ready-made model set, only if every model is in the catalog and every key is there."""
    from services import model_catalog
    from services.preset_stacks_service import apply_preset, get_preset

    p = await get_preset(preset_id)
    if not p or p.get("is_archived"):
        raise HTTPException(status_code=404, detail="المجموعة غير موجودة")
    if not await model_catalog.preset_is_valid(p):
        raise HTTPException(status_code=400, detail="المجموعة فيها موديلات مش في الكتالوج")
    missing = set()
    for m in (p.get("stage_map") or {}).values():
        env_key = model_catalog.env_key_for(m["provider"])
        if not (await model_catalog.key_status(env_key))["configured"]:
            missing.add(env_key)
    if missing:
        raise HTTPException(status_code=400, detail=f"مفاتيح ناقصة: {', '.join(sorted(missing))}")
    result = await apply_preset(preset_id, admin.get("id"), admin.get("email"))
    return {"ok": True, "applied_stages": result.get("applied_stages")}


# ============================================================================
# MODEL CATALOG (M4)
# ============================================================================
Capability = Literal["text", "image", "tts", "video", "music"]
Status = Literal["recommended", "available", "testing_only", "retired"]
Unit = Literal["1m_tokens", "image", "second", "minute"]


class Price(BaseModel):
    unit: Unit
    usd: Optional[float] = Field(default=None, ge=0, le=100)
    input_usd: Optional[float] = Field(default=None, ge=0, le=1000)
    output_usd: Optional[float] = Field(default=None, ge=0, le=1000)
    by_quality: Optional[dict[Literal["low", "medium", "high"], float]] = None
    source: Optional[Literal["invoice", "list", "estimate"]] = None


class CatalogIn(BaseModel):
    capability: Capability
    provider: str = Field(pattern=r"^[a-z_]{2,30}$")
    model_name: str = Field(min_length=2, max_length=160, pattern=r"^[A-Za-z0-9._/:-]+$")
    label: str = Field(min_length=2, max_length=80)
    status: Status = "available"
    price: Price
    notes_ar: str = Field(default="", max_length=600)


class CatalogPatch(BaseModel):
    label: Optional[str] = Field(default=None, min_length=2, max_length=80)
    status: Optional[Status] = None
    price: Optional[Price] = None
    notes_ar: Optional[str] = Field(default=None, max_length=600)
    active: Optional[bool] = None


async def _models_in_use() -> dict[str, list[str]]:
    """Maps "provider|model" to the stages (or the premium tier) using it now."""
    from services import model_catalog

    used: dict[str, list[str]] = {}
    for r in await model_catalog.stage_rows():
        if r["selectable"]:
            used.setdefault(f"{r['provider']}|{r['model_name']}", []).append(r["name_ar"])
    used.setdefault(f"kling|{await model_catalog.premium_video_model()}", []).append("الفيديو الفاخر")
    return used


@router.get("/engine/catalog")
async def get_catalog():
    from services import model_catalog

    return {
        "items": await model_catalog.list_catalog(),
        "in_use": await _models_in_use(),
        "executors": {k: sorted(v) for k, v in model_catalog.EXECUTORS.items()},
        "capability_labels": model_catalog.CAPABILITY_LABELS,
        "statuses": model_catalog.STATUSES,
        "units": model_catalog.UNITS,
    }


@router.post("/engine/catalog")
async def add_catalog_model(payload: CatalogIn, admin: dict = Depends(require_admin)):
    from services import model_catalog

    if payload.provider not in model_catalog.EXECUTORS[payload.capability]:
        raise HTTPException(status_code=400, detail=(
            f"مفيش كود بيشغّل {payload.provider} لـ{model_catalog.CAPABILITY_LABELS[payload.capability]}. "
            f"المتاح: {', '.join(sorted(model_catalog.EXECUTORS[payload.capability]))}"))
    if await model_catalog.find_model(payload.provider, payload.model_name):
        raise HTTPException(status_code=409, detail="الموديل موجود في الكتالوج")
    doc = {**payload.model_dump(), "id": str(uuid.uuid4()), "active": True, "seeded": False,
           "created_at": _now(), "updated_at": _now()}
    await db.model_catalog.insert_one(doc)
    await _audit(admin, "model_catalog", doc["id"], "catalog.add", f"موديل جديد في الكتالوج: {payload.label}")
    return await db.model_catalog.find_one({"id": doc["id"]}, {"_id": 0})


@router.patch("/engine/catalog/{model_id}")
async def update_catalog_model(model_id: str, payload: CatalogPatch, admin: dict = Depends(require_admin)):
    before = await db.model_catalog.find_one({"id": model_id}, {"_id": 0})
    if not before:
        raise HTTPException(status_code=404, detail="الموديل غير موجود")
    patch = payload.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(status_code=400, detail="لا يوجد تعديل")
    if patch.get("active") is False or patch.get("status") == "retired":
        users = (await _models_in_use()).get(f"{before['provider']}|{before['model_name']}")
        if users:
            raise HTTPException(status_code=400,
                                detail=f"الموديل مستخدم دلوقتي في: {'، '.join(users)} — غيّره هناك الأول")
    patch["updated_at"] = _now()
    await db.model_catalog.update_one({"id": model_id}, {"$set": patch})
    await _audit(admin, "model_catalog", model_id, "catalog.update", f"تعديل {before.get('label')} في الكتالوج",
                 before={k: before.get(k) for k in patch if k != "updated_at"},
                 after={k: v for k, v in patch.items() if k != "updated_at"})
    return await db.model_catalog.find_one({"id": model_id}, {"_id": 0})


# ============================================================================
# PROMPT TEMPLATES (M5) — the user-message templates generation actually reads
# ============================================================================
# Only these three are read at run time (resolve_prompt); the other seeded
# templates are informational and stay out of the editor.
USED_TEMPLATES = {
    "scenario_generation": {
        "name_ar": "رسالة طلب السيناريوهات",
        "purpose_ar": "بيانات الطلب اللي بتتبعت مع برومبت النظام لما بنطلب الـ 3 سيناريوهات.",
    },
    "production_planning": {
        "name_ar": "رسالة طلب خطة الإنتاج",
        "purpose_ar": "بيانات الطلب والسيناريو المختار اللي بتتبعت لخطة الإنتاج (قبل قواعد اللقطات واللهجة اللي بتتضاف لوحدها).",
    },
    "child_character_i2i": {
        "name_ar": "برومبت شخصية الطفل من الصورة",
        "purpose_ar": "اللي بيتبعت مع صورة الطفل وصورة الستايل المرجعية عشان يطلع شيت الشخصية.",
    },
}

SAMPLE_ORDER_DATA = {  # used for previews when there is no real order yet (fictional child)
    "goal": {"context": "سليم بيخاف من الميّه ومش راضي ينزل حمام السباحة في النادي."},
    "child": {"name": "سليم", "age": 6, "gender": "male", "appearance_notes": "شعر أسود قصير ونضارة صغيرة"},
    "characters": [{"type": "father", "name": "خالد", "role": "visible"}],
    "personalization": {"favorites": {}, "custom_notes": ""},
    "style": {}, "duration": {"seconds": 60}, "audio_background": {"mode": "music"},
    "delivery": {"output_type": "both", "video_tier": "balanced"},
}


async def _template_contexts() -> tuple[dict[str, dict], dict[str, str], str | None]:
    """Variables each template can use (from the latest order with a scenario,
    else a fictional sample), and the text the code builds when no template is active."""
    from models import duration_meta
    from services import engine_config
    from services.child_character_service import _build_context
    from services.production_service import (_build_production_context, _build_user_prompt,
                                             target_scene_count)
    from services.scenario_service import _build_scenario_context, _user_prompt

    order = await db.orders.find_one({"selected_scenario_snapshot": {"$ne": None}}, {"_id": 0},
                                     sort=[("created_at", -1)])
    sample_id = order.get("id") if order else None
    if not order:
        order = {"id": "sample", "data": SAMPLE_ORDER_DATA, "duration": duration_meta(60), "enriched": {},
                 "selected_scenario_snapshot": {"title": "سرّ بابا خالد الصغير", "short_summary": "بابا يحكي لسليم سرّ.",
                                                "learning_goal": "الشجاع اللي بيجرّب", "emotional_angle": "warm"}}
    scenario = order.get("selected_scenario_snapshot") or {}
    target = target_scene_count(order, scenario)
    art_style = await engine_config.style_for_order(order)
    contexts = {
        "scenario_generation": _build_scenario_context(order),
        "production_planning": _build_production_context(order, scenario, target),
        "child_character_i2i": _build_context(order, None, "", art_style),
    }
    defaults = {
        "scenario_generation": _user_prompt(order),
        "production_planning": _build_user_prompt(order, scenario, target),
        "child_character_i2i": house_style.character_sheet_prompt(
            "the person in the photo", None, art_style.get("style_text"), art_style.get("sheet_rules")),
    }
    return contexts, defaults, sample_id


def _render(text: str, ctx: dict) -> tuple[str | None, list[str]]:
    from services.config_service import _extract_placeholders, render_prompt_template

    unknown = sorted(p for p in _extract_placeholders(text) if p not in ctx)
    if unknown:
        return None, unknown
    rendered, ok, _reason = render_prompt_template(text, ctx)
    return (rendered if ok else None), []


@router.get("/engine/prompt-templates")
async def list_prompt_templates_used():
    contexts, defaults, sample_id = await _template_contexts()
    out = []
    for stage, meta in USED_TEMPLATES.items():
        versions = await db.prompt_templates.find({"stage_key": stage}, {"_id": 0}).sort("version", -1).to_list(50)
        active = next((v for v in versions if v.get("active")), None)
        rendered, unknown = _render(active["template_text"], contexts[stage]) if active else (None, [])
        out.append({
            "stage": stage, **meta,
            "active": active, "versions": versions,
            "variables": sorted(contexts[stage]),
            "sample": {k: str(v)[:160] for k, v in contexts[stage].items()},
            "sample_order_id": sample_id,
            "code_default_preview": defaults[stage],
            "active_preview": rendered,
            # An active template with a variable the code doesn't provide is silently
            # skipped at run time (the code text is sent instead) — say so.
            "active_broken": bool(active) and rendered is None,
            "active_unknown_vars": unknown,
        })
    return out


class TemplateIn(BaseModel):
    template_text: str = Field(min_length=50, max_length=40000)
    activate: bool = True


@router.post("/engine/prompt-templates/{stage}/preview")
async def preview_prompt_template(stage: str, payload: TemplateIn):
    if stage not in USED_TEMPLATES:
        raise HTTPException(status_code=404, detail="قالب غير معروف")
    contexts, _defaults, _sid = await _template_contexts()
    rendered, unknown = _render(payload.template_text, contexts[stage])
    return {"rendered": rendered, "unknown_vars": unknown}


@router.post("/engine/prompt-templates/{stage}")
async def save_prompt_template(stage: str, payload: TemplateIn, admin: dict = Depends(require_admin)):
    from services.config_service import _extract_placeholders

    if stage not in USED_TEMPLATES:
        raise HTTPException(status_code=404, detail="قالب غير معروف")
    contexts, _defaults, _sid = await _template_contexts()
    rendered, unknown = _render(payload.template_text, contexts[stage])
    if unknown:
        raise HTTPException(status_code=400, detail=f"متغيرات مش موجودة: {', '.join('$' + u for u in unknown)}")
    if rendered is None:
        raise HTTPException(status_code=400, detail="القالب ما اتعرضش — راجع علامات $")
    last = await db.prompt_templates.find_one({"stage_key": stage}, {"_id": 0, "version": 1}, sort=[("version", -1)])
    doc = {"id": str(uuid.uuid4()), "stage_key": stage, "name": USED_TEMPLATES[stage]["name_ar"],
           "template_text": payload.template_text, "variables": sorted(_extract_placeholders(payload.template_text)),
           "version": (last["version"] + 1) if last else 1, "active": False,
           "created_at": _now(), "updated_at": _now(), "created_by": admin.get("email")}
    await db.prompt_templates.insert_one(doc)
    if payload.activate:
        await _activate_system_prompt(stage, doc["id"])
    await _audit(admin, "prompt_template", stage, "prompt_template.create",
                 f"نسخة {doc['version']} من {USED_TEMPLATES[stage]['name_ar']}" + (" (مفعّلة)" if payload.activate else ""))
    return await db.prompt_templates.find_one({"id": doc["id"]}, {"_id": 0})


@router.post("/engine/prompt-templates/{stage}/activate/{prompt_id}")
async def activate_prompt_template_version(stage: str, prompt_id: str, admin: dict = Depends(require_admin)):
    if stage not in USED_TEMPLATES:
        raise HTTPException(status_code=404, detail="قالب غير معروف")
    doc = await db.prompt_templates.find_one({"id": prompt_id, "stage_key": stage}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="النسخة غير موجودة")
    contexts, _defaults, _sid = await _template_contexts()
    if _render(doc["template_text"], contexts[stage])[0] is None:
        raise HTTPException(status_code=400, detail="النسخة دي فيها متغيرات مش موجودة، فهتتجاهل لو اتفعّلت")
    await _activate_system_prompt(stage, prompt_id)
    await _audit(admin, "prompt_template", stage, "prompt_template.activate",
                 f"تفعيل نسخة {doc.get('version')} من {USED_TEMPLATES[stage]['name_ar']}")
    return {"ok": True}


@router.post("/engine/prompt-templates/{stage}/reset")
async def reset_prompt_template(stage: str, admin: dict = Depends(require_admin)):
    if stage not in USED_TEMPLATES:
        raise HTTPException(status_code=404, detail="قالب غير معروف")
    await db.prompt_templates.update_many({"stage_key": stage, "active": True},
                                          {"$set": {"active": False, "updated_at": _now()}})
    await _audit(admin, "prompt_template", stage, "prompt_template.reset",
                 f"{USED_TEMPLATES[stage]['name_ar']} رجع للنص اللي بيبنيه الكود")
    return {"ok": True}


# ============================================================================
# OPERATIONS HOME (M5) — what needs attention, and how the business is doing
# ============================================================================
STUCK_HOURS = 3  # a generating/assembling order idle this long needs a look
WAITING_CUSTOMER_HOURS = 48


@router.get("/overview")
async def operations_overview():
    from datetime import timedelta

    from models import ORDER_STATUS_AR
    from services import model_catalog

    now = datetime.now(timezone.utc)
    stuck_before = (now - timedelta(hours=STUCK_HOURS)).isoformat()
    waiting_before = (now - timedelta(hours=WAITING_CUSTOMER_HOURS)).isoformat()
    fields = {"_id": 0, "id": 1, "status": 1, "created_at": 1, "updated_at": 1, "user_id": 1, "data.child.name": 1,
              "duration.seconds": 1, "price_quote": 1}

    async def queue(q: dict, reason: str, limit: int = 20) -> list[dict]:
        rows = await db.orders.find(q, fields).sort("updated_at", -1).to_list(limit)
        for r in rows:
            r["child_name"] = ((r.pop("data", {}) or {}).get("child") or {}).get("name")
            r["status_ar"] = ORDER_STATUS_AR.get(r.get("status"), r.get("status"))
            r["reason_ar"] = reason
        return rows

    attention = {
        "failed": await queue({"status": {"$in": ["media_failed", "failed"]}},
                              "الإنتاج فشل — افتح الطلب وشوف المرحلة اللي وقعت"),
        "stuck": await queue({"status": {"$in": ["scenarios_generating", "production_planning", "assets_generating",
                                                 "assembling", "generating"]},
                              "updated_at": {"$lt": stuck_before}},
                             f"شغّال من أكتر من {STUCK_HOURS} ساعات من غير تحديث"),
        "waiting_customer": await queue({"status": "scenarios_ready", "updated_at": {"$lt": waiting_before}},
                                        f"السيناريوهات جاهزة والعميل ما اختارش من أكتر من {WAITING_CUSTOMER_HOURS} ساعة"),
        "safety_review": await queue({"safety_flag": True, "safety_review": None, "status": "production_ready"},
                                     "الخطة فيها موضوع حسّاس — راجعها قبل ما العميل يعتمدها"),
    }

    async def count_since(days: int, q: dict | None = None) -> int:
        return await db.orders.count_documents({**(q or {}), "created_at": {"$gte": (now - timedelta(days=days)).isoformat()}})

    async def revenue_since(days: int) -> float:
        """Stories paid in the period (card, wallet or old bundle), before VAT.
        Wallet top-ups aren't revenue until the credit buys a story."""
        rows = await db.orders.find({"payment.status": "paid",
                                     "payment.paid_at": {"$gte": (now - timedelta(days=days)).isoformat()}},
                                    {"_id": 0, "payment.amount_sar": 1}).to_list(5000)
        return round(sum(float((r.get("payment") or {}).get("amount_sar") or 0) for r in rows), 2)

    stages = await model_catalog.stage_rows()
    missing_keys = sorted({s["key"]["env_key"] for s in stages if s["selectable"] and not s["key"]["configured"]})
    recent = await queue({}, "", limit=8)
    return {
        "attention": attention,
        "attention_count": sum(len(v) for v in attention.values()),
        "kpis": {
            "orders_7d": await count_since(7), "orders_30d": await count_since(30),
            "delivered_30d": await count_since(30, {"status": "delivered"}),
            "failed_30d": await count_since(30, {"status": {"$in": ["media_failed", "failed"]}}),
            "revenue_7d_sar": await revenue_since(7), "revenue_30d_sar": await revenue_since(30),
            "users_total": await db.users.count_documents({}),
        },
        "engine": {
            "stages_total": sum(1 for s in stages if s["selectable"]),
            "stages_off_catalog": [s["name_ar"] for s in stages if not s["in_catalog"]],
            "missing_keys": missing_keys,
            "disabled_optional": [s["name_ar"] for s in stages if s["toggleable"] and not s["enabled"]],
            "balance": await _engine_balance(),
            "disk": _disk_usage(),
        },
        "recent_orders": recent,
        "thresholds": {"stuck_hours": STUCK_HOURS, "waiting_customer_hours": WAITING_CUSTOMER_HOURS},
    }


def _disk_usage() -> dict | None:
    """Free space where the media lives (a full disk stopped MongoDB twice on the laptop)."""
    import shutil

    try:
        from storage import STORAGE_DIR
        u = shutil.disk_usage(STORAGE_DIR)
        return {"free_gb": round(u.free / 1024 ** 3, 1), "used_pct": round(u.used / u.total * 100)}
    except Exception:  # noqa: BLE001
        return None


async def _engine_balance() -> dict:
    """The providers' balance as last seen by a real call (locked = top-up needed)."""
    from services import engine_health

    st = await engine_health.status()
    return {"locked": st["locked"], "locked_at": st.get("locked_at"), "paused_orders": st.get("paused_orders", 0),
            "provider_label": st.get("provider_label")}
