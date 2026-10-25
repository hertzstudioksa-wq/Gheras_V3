"""Model catalog (M4): the models a stage may use, with what they cost.

Only models this codebase can actually execute are listed (a provider with an
executor for the stage's capability), so picking one from the admin can never
leave a stage on a model nothing knows how to call. Prices come from fal's
invoices (2026-10-24), the providers' price lists, or the bake-offs, and say
which; they feed the customer price calculator.

  model_catalog   one doc per (provider, model_name): capability, label, status,
                  price, notes. Seeded once; the admin edits prices/status/notes
                  and can add models for providers that have an executor.
  engine_settings.video_premium   the model the "فاخر" video tier renders with.

The stage → model choice itself still lives in model_registry (read by
config_service.resolve_model everywhere); this module validates and writes it.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from db import db
from services.config_service import (
    DEFAULT_MODELS, DEFAULT_PIPELINE, PROVIDER_ENV_MAP, STAGE_DISPLAY_NAMES, VIDEO_TIERS, get_pipeline_config,
)

CAPABILITY_OF_STAGE = {
    "scenario_generation": "text",
    "production_planning": "text",
    "child_character_i2i": "image",
    "extra_character_i2i": "image",
    "scene_image_generation": "image",
    "book_page_image_generation": "image",
    "narration_generation": "tts",
    "music_generation": "music",
    "video_generation": "video",
}
CAPABILITY_LABELS = {"text": "نصوص", "image": "صور", "tts": "صوت السرد", "video": "فيديو", "music": "موسيقى"}

# Providers with an executor for each capability (services/ai, tts_service,
# music_generation_service, shot_pipeline). Anything else can't be selected.
EXECUTORS = {
    "text": {"fal_llm", "anthropic", "openai", "gemini"},
    "image": {"fal_image", "openai", "gemini", "comfy_image"},
    "tts": {"fal_gemini_tts", "gemini_tts", "fal_tts", "elevenlabs", "openai"},
    "video": {"kling", "comfy_video"},  # the shot engine: Kling (v2.x, v3) via fal, Wan 2.2 on Comfy
    "music": {"fal_music"},
}

# Providers that only fit some stages of their capability: Comfy's workflows draw
# shot keyframes and animate clips; the sheets stay on GPT Image 2.
STAGE_LIMITS = {"comfy_image": {"scene_image_generation"}, "comfy_video": {"video_generation"}}


def fits_stage(provider: str, stage: str) -> bool:
    return stage in STAGE_LIMITS.get(provider, {stage})


# Stages the owner may switch off; the rest are the product itself.
TOGGLEABLE_STAGES = {
    "extra_character_i2i": "لو اتقفلت، الأقارب بيترسموا من الوصف بدل صورهم.",
    "music_generation": "لو اتقفلت، الفيديو بيطلع بالسرد بس من غير موسيقى.",
}

STATUSES = {"recommended": "معتمد", "available": "متاح", "testing_only": "للتجربة بس", "retired": "متوقف"}
UNITS = {"1m_tokens": "مليون توكن", "image": "صورة", "second": "ثانية", "minute": "دقيقة"}

_INVOICE = "invoice"   # fal billing dashboard, 2026-10-24
_LIST = "list"         # provider price list
_ESTIMATE = "estimate"  # bake-off measurement / rough

CATALOG_SEED = [
    # ---- text
    {"capability": "text", "provider": "fal_llm", "model_name": "anthropic/claude-opus-5.5",
     "label": "Claude Opus 5.5 (عبر fal)", "status": "recommended",
     "price": {"unit": "1m_tokens", "input_usd": 4.0, "output_usd": 20.0, "source": _LIST},
     "notes_ar": "النموذج المعتمد للسيناريوهات والخطة. مقاس على قصة يمان: السيناريوهات ≈ $0.05 والخطة ≈ $0.27."},
    {"capability": "text", "provider": "anthropic", "model_name": "claude-opus-5-5",
     "label": "Claude Opus 5.5 (Anthropic مباشرة)", "status": "available",
     "price": {"unit": "1m_tokens", "input_usd": 4.0, "output_usd": 20.0, "source": _LIST},
     "notes_ar": "نفس الموديل من غير وسيط. محتاج ANTHROPIC_API_KEY."},
    # Text bake-off 2026-10-24 (same fictional order, real pipeline code; costs are fal's per story,
    # scenarios + plan): all three passed validation; scores are the owner-facing reading of the stories.
    {"capability": "text", "provider": "fal_llm", "model_name": "anthropic/claude-haiku-5.5",
     "label": "Claude Haiku 5.5 (عبر fal)", "status": "available",
     "price": {"unit": "1m_tokens", "input_usd": 0.10, "output_usd": 0.50, "source": _LIST},
     "notes_ar": "في المقارنة: ≈ $0.01 للقصة (تقييم 8/10). مصري طبيعي وحيوي ووصف صور قوي، بس كتب نص الكتاب بالعامية "
                 "بدل الفصحى، وخلّى اللعبة شخصية ليها شيت (صورة زيادة)."},
    {"capability": "text", "provider": "fal_llm", "model_name": "openai/gpt-6-luna",
     "label": "GPT-6 Luna (عبر fal)", "status": "available",
     "price": {"unit": "1m_tokens", "input_usd": 0.10, "output_usd": 0.50, "source": _LIST},
     "notes_ar": "في المقارنة: ≈ $0.005 للقصة (تقييم 8/10). قصة نضيفة ومترابطة ومصري سليم ونص الكتاب فصحى مظبوطة؛ "
                 "النهاية أهدى من Opus، ولبّس الأب بنطلون جنب البيسين."},
    {"capability": "text", "provider": "fal_llm", "model_name": "google/gemini-3.8-flash",
     "label": "Gemini 3.8 Flash (عبر fal)", "status": "available",
     "price": {"unit": "1m_tokens", "input_usd": 0.825, "output_usd": 4.125, "source": _LIST},
     "notes_ar": "في المقارنة: ≈ $0.05 للقصة (تقييم 7.5/10). Gemini المدفوع من غير حساب جوجل منفصل؛ بعض الكلمات "
                 "مش طبيعية لطفل وتشكيل متلخبط في العامية — أغلى من Haiku وLuna وأضعف منهم."},
    {"capability": "text", "provider": "gemini", "model_name": "gemini-3.5-flash",
     "label": "Gemini 3.5 Flash (مجاني)", "status": "testing_only",
     "price": {"unit": "1m_tokens", "input_usd": 0.0, "output_usd": 0.0, "source": _LIST},
     "notes_ar": "للتجربة بس: الطبقة المجانية بحدود يومية، وجوجل ممكن تستخدم بياناتها في التدريب — ممنوع مع بيانات أطفال "
                 "حقيقية. في المقارنة: تقييم 6.5/10، ورجّع «مشغول» (503) مرتين قبل ما يرد."},
    # ---- images
    {"capability": "image", "provider": "fal_image", "model_name": "openai/gpt-image-2",
     "label": "GPT Image 2 (عبر fal)", "status": "recommended",
     "price": {"unit": "image", "by_quality": {"low": 0.02, "medium": 0.06, "high": 0.17}, "source": _INVOICE},
     "notes_ar": "أحسن شبه للوشوش مع صورة الستايل المرجعية. الجودة لكل مرحلة من محرك الإنتاج ← الإيقاع والجودة "
                 "(سعر المنخفضة تقديري)."},
    {"capability": "image", "provider": "openai", "model_name": "gpt-image-2",
     "label": "GPT Image 2 (OpenAI مباشرة)", "status": "available",
     "price": {"unit": "image", "by_quality": {"low": 0.02, "medium": 0.06, "high": 0.17}, "source": _ESTIMATE},
     "notes_ar": "نفس الموديل من غير وسيط. محتاج رصيد في حساب OpenAI."},
    {"capability": "image", "provider": "fal_image", "model_name": "openai/gpt-image-1.5",
     "label": "GPT Image 1.5 (عبر fal)", "status": "available",
     "price": {"unit": "image", "usd": None, "source": None},
     "notes_ar": "شكله كرتوني لطيف بس الكبار بيطلعوا برؤوس كبيرة. OpenAI هتوقفه 2026-12-01."},
    {"capability": "image", "provider": "fal_image", "model_name": "fal-ai/nano-banana-pro",
     "label": "Nano Banana Pro (عبر fal)", "status": "available",
     "price": {"unit": "image", "usd": None, "source": None},
     "notes_ar": "أرخص، بس الوشوش في الشيتات طلعت عامة ومش شبه الصورة (اختبار الشبه 2026-10-24)."},
    {"capability": "image", "provider": "gemini", "model_name": "gemini-2.5-flash-image",
     "label": "Gemini 2.5 Flash Image", "status": "testing_only",
     "price": {"unit": "image", "usd": 0.04, "source": _LIST},
     "notes_ar": "للتجربة بس — المفتاح المجاني حده 0 صور، ومحتاج billing."},
    {"capability": "image", "provider": "comfy_image", "model_name": "comfy/keyframe_qwen21",
     "label": "Qwen Image 2.1 Edit (Comfy Cloud)", "status": "available", "stages": ["scene_image_generation"],
     "price": {"unit": "image", "usd": 0.04, "source": _ESTIMATE},
     "notes_ar": "صور اللقطات والغلاف بس (الشيتات بتفضل GPT Image 2). كل شيت مرجع لوحده + لعبة الطفل + اللقطة "
                 "اللي قبلها، ومن غير صورة الستايل. في المقارنة قريب من GPT Image 2 في الشبه بربع السعر تقريباً "
                 "(صورة حقيقية: 12 ث GPU ≈ $0.02). الرخصة لسه محتاجة تأكيد مكتوب من Comfy."},
    # ---- narration
    {"capability": "tts", "provider": "fal_gemini_tts", "model_name": "fal-ai/gemini-3.1-flash-tts",
     "label": "Gemini 3.1 Flash TTS (عبر fal)", "status": "recommended",
     "price": {"unit": "minute", "usd": 0.045, "source": "fal: $0.05 / 1000 حرف — دقيقة سرد ≈ 900 حرف مع التوجيه"},
     "notes_ar": "نفس أصوات Gemini العربية واللهجات (اللي اتختارت في الاختبار) بس مدفوعة على رصيد fal: "
                 "كلام ولي الأمر مش بيعدّي على الـ free tier بتاع جوجل."},
    {"capability": "tts", "provider": "gemini_tts", "model_name": "gemini-3.8-flash-tts",
     "label": "Gemini 3.8 Flash TTS", "status": "recommended",
     "price": {"unit": "minute", "usd": None, "source": None},
     "notes_ar": "أصوات عربية أصلية باللهجات (مصري 10/10 في الاختبار). المفتاح الحالي مجاني بحدود يومية — الإنتاج محتاج "
                 "مفتاح مدفوع، والسعر هيتقاس أول ما يتفعّل."},
    {"capability": "tts", "provider": "fal_tts", "model_name": "fal-ai/elevenlabs/tts/multilingual-v2",
     "label": "ElevenLabs Multilingual v2 (عبر fal)", "status": "available",
     "price": {"unit": "minute", "usd": None, "source": None},
     "notes_ar": "أصوات مش عربية أصلية — النطق بيبان مترجم. مفيش لهجات."},
    # ---- video
    {"capability": "video", "provider": "kling", "model_name": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
     "label": "Kling 2.5 Turbo Pro", "status": "recommended",
     "price": {"unit": "second", "usd": 0.07, "source": _LIST},
     "notes_ar": "الجودة المتوازنة: قريب من v3 pro في المقارنة بثلثين السعر. المقاطع 5 أو 10 ث بس، ومن غير عناصر شخصيات."},
    {"capability": "video", "provider": "kling", "model_name": "fal-ai/kling-video/v3/pro/image-to-video",
     "label": "Kling v3 Pro", "status": "recommended",
     "price": {"unit": "second", "usd": 0.112, "source": _INVOICE},
     "notes_ar": "الجودة الفاخرة: أحسن ثبات للشخصيات (عناصر الشخصيات من الشيتات) وأي طول من 3 لـ 15 ث."},
    {"capability": "video", "provider": "kling", "model_name": "fal-ai/kling-video/v3/standard/image-to-video",
     "label": "Kling v3 Standard", "status": "available",
     "price": {"unit": "second", "usd": 0.084, "source": _INVOICE},
     "notes_ar": "أرخص من v3 pro بالربع وحركة أقل شوية (اختبار M1)."},
    {"capability": "video", "provider": "comfy_video", "model_name": "comfy/clip_wan22",
     "label": "Wan 2.2 I2V (Comfy Cloud)", "status": "available", "stages": ["video_generation"],
     "price": {"unit": "second", "usd": 0.03, "source": _ESTIMATE},
     "notes_ar": "Wan 2.2 I2V 14B + lightx2v 4-step، 1280x720 24 fps، من 3 لـ 7 ث بالظبط على طول السطر. المالك: "
                 "«مقبولة جداً». ≈ 80 ث GPU للمقطع 5 ث (≈ $0.15). لو المقطع اتعلّم عليه مرتين أو فشل، اللقطة دي بس "
                 "بتترندر بـ Kling (إعداد comfy.kling_rescue). الفاخر بيفضل Kling."},
    # ---- music
    {"capability": "music", "provider": "fal_music", "model_name": "fal-ai/elevenlabs/music",
     "label": "ElevenLabs Music (عبر fal)", "status": "recommended",
     "price": {"unit": "minute", "usd": 0.60, "source": _INVOICE},
     "notes_ar": "الموسيقى الحالية: هادية ونضيفة تحت السرد."},
    {"capability": "music", "provider": "fal_music", "model_name": "cassetteai/music-generator",
     "label": "CassetteAI Music (عبر fal)", "status": "available",
     "price": {"unit": "minute", "usd": 0.02, "source": _ESTIMATE},
     "notes_ar": "أرخص بكتير (≈ 2 سنت للقصة) — اسمع عينة المقارنة قبل ما تعتمده."},
    {"capability": "music", "provider": "fal_music", "model_name": "fal-ai/stable-audio-25/text-to-audio",
     "label": "Stable Audio 2.5 (عبر fal)", "status": "available",
     "price": {"unit": "minute", "usd": 0.22, "source": _ESTIMATE},
     "notes_ar": "وسط في السعر — اسمع عينة المقارنة قبل ما تعتمده."},
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def env_key_for(provider: str) -> str | None:
    return (PROVIDER_ENV_MAP.get(provider) or {}).get("env_key")


async def seed_catalog() -> int:
    """Insert seed models that aren't in the catalog yet (admin edits are kept)."""
    n = 0
    for spec in CATALOG_SEED:
        if await db.model_catalog.find_one({"provider": spec["provider"], "model_name": spec["model_name"]}, {"_id": 1}):
            continue
        await db.model_catalog.insert_one({**spec, "id": str(uuid.uuid4()), "active": True, "seeded": True,
                                           "created_at": _now(), "updated_at": _now()})
        n += 1
    return n


async def list_catalog(capability: str | None = None, include_inactive: bool = True) -> list[dict]:
    q: dict = {}
    if capability:
        q["capability"] = capability
    if not include_inactive:
        q["active"] = True
    return await db.model_catalog.find(q, {"_id": 0}).sort([("capability", 1), ("created_at", 1)]).to_list(200)


async def find_model(provider: str, model_name: str) -> dict | None:
    return await db.model_catalog.find_one({"provider": provider, "model_name": model_name}, {"_id": 0})


def unit_price(entry: dict | None, quality: str | None = None) -> float | None:
    """USD per unit (per image at `quality`, per second, per minute)."""
    price = (entry or {}).get("price") or {}
    if price.get("by_quality"):
        return price["by_quality"].get(quality or "high")
    return price.get("usd")


# ---------------------------------------------------------------- keys
async def key_status(env_key: str | None) -> dict:
    """Is the key a stage needs available? fal keys fall back to any other fal
    key, exactly as services.ai.fal.resolve_key does at call time."""
    from services.secret_overrides_service import secret_source

    if not env_key:
        return {"env_key": None, "configured": True, "source": "local"}
    src = await secret_source(env_key)
    if src != "missing":
        return {"env_key": env_key, "configured": True, "source": src}
    if env_key.startswith("FAL_KEY"):
        for other in ("FAL_KEY", "FAL_KEY_SCENE", "FAL_KEY_VIDEO", "FAL_KEY_NARRATION", "FAL_KEY_MUSIC", "FAL_KEY_TEXT"):
            if other != env_key and await secret_source(other) != "missing":
                return {"env_key": env_key, "configured": True, "source": "shared", "shared_from": other}
    return {"env_key": env_key, "configured": False, "source": "missing"}


# ---------------------------------------------------------------- premium video tier
async def premium_video_model() -> str:
    """Model the "فاخر" tier renders with (admin-chosen, default Kling v3 pro)."""
    doc = await db.engine_settings.find_one({"id": "default"}, {"_id": 0, "video_premium": 1}) or {}
    return (doc.get("video_premium") or {}).get("model_name") or VIDEO_TIERS["premium"]["model_name"]


async def video_model_for_tier(tier: str) -> tuple[str, str]:
    """(provider, model) the shot engine uses for an order's video tier."""
    from services.config_service import resolve_model

    if tier == "premium":
        return "kling", await premium_video_model()
    provider, model, _src = await resolve_model("video_generation", "kling", DEFAULT_MODELS["video_generation"]["model_name"])
    return provider, model


# ---------------------------------------------------------------- stages
async def stage_rows() -> list[dict]:
    """Every pipeline stage with its model, price, key and switch, for the admin."""
    cfg = await get_pipeline_config()
    stages_cfg = cfg.get("stages") or {}
    registry = {r["stage_key"]: r for r in await db.model_registry.find({}, {"_id": 0}).to_list(50)}
    catalog = await list_catalog()
    order = [s for s in (cfg.get("order") or DEFAULT_PIPELINE["order"]) if s in DEFAULT_MODELS]
    rows = []
    for stage in order:
        cap = CAPABILITY_OF_STAGE.get(stage)
        reg = registry.get(stage) or {}
        default = DEFAULT_MODELS[stage]
        provider = reg.get("provider") or default["provider"]
        model = reg.get("model_name") or default["model_name"]
        entry = next((c for c in catalog if c["provider"] == provider and c["model_name"] == model), None)
        env_key = env_key_for(provider) or default.get("env_key")
        rows.append({
            "stage_key": stage,
            "name_ar": (STAGE_DISPLAY_NAMES.get(stage) or {}).get("ar") or stage,
            "capability": cap,
            "capability_ar": CAPABILITY_LABELS.get(cap) if cap else "محلي",
            "provider": provider,
            "model_name": model,
            "source": "admin" if reg else "default",
            "is_default": provider == default["provider"] and model == default["model_name"],
            "default_label": next((c["label"] for c in catalog if c["provider"] == default["provider"]
                                   and c["model_name"] == default["model_name"]), default["model_name"]),
            "catalog_entry": entry,
            "in_catalog": bool(entry) or cap is None,
            "key": await key_status(env_key),
            "enabled": bool((stages_cfg.get(stage) or {}).get("enabled", False)),
            "toggleable": stage in TOGGLEABLE_STAGES,
            "toggle_note_ar": TOGGLEABLE_STAGES.get(stage),
            "selectable": cap is not None,
        })
    return rows


async def set_stage_model(stage: str, provider: str, model_name: str, admin: dict) -> dict:
    """Point a stage at a catalog model. Raises ValueError with an Arabic reason."""
    from services.audit_service import record_audit

    cap = CAPABILITY_OF_STAGE.get(stage)
    if not cap:
        raise ValueError("المرحلة دي محلية ومفيهاش اختيار موديل")
    entry = await find_model(provider, model_name)
    if not entry:
        raise ValueError("الموديل مش في الكتالوج — ضيفه في الكتالوج الأول")
    if entry["capability"] != cap:
        raise ValueError(f"الموديل ده {CAPABILITY_LABELS[entry['capability']]} والمرحلة محتاجة {CAPABILITY_LABELS[cap]}")
    if not entry.get("active") or entry.get("status") == "retired":
        raise ValueError("الموديل ده متوقف في الكتالوج")
    if provider not in EXECUTORS[cap] or not fits_stage(provider, stage):
        raise ValueError("مفيش كود بيشغّل المزوّد ده للمرحلة دي")
    env_key = env_key_for(provider)
    key = await key_status(env_key)
    if not key["configured"]:
        raise ValueError(f"المفتاح {env_key} مش متظبط — ضيفه من صفحة المفاتيح والمزوّدين الأول")

    before = await db.model_registry.find_one({"stage_key": stage}, {"_id": 0})
    now = _now()
    patch = {"provider": provider, "model_name": model_name, "env_key": env_key, "active": True,
             "updated_at": now, "applied_by_preset_id": None, "applied_by_preset_name": None,
             # Nothing reads a fallback model at run time; keep the row honest.
             "fallback_provider": None, "fallback_model": None}
    await db.model_registry.update_one(
        {"stage_key": stage},
        {"$set": patch, "$setOnInsert": {
            "id": str(uuid.uuid4()), "stage_key": stage, "created_at": now, "notes": "",
            "stage_name_ar": (STAGE_DISPLAY_NAMES.get(stage) or {}).get("ar"),
            "stage_name_en": (STAGE_DISPLAY_NAMES.get(stage) or {}).get("en")}},
        upsert=True)
    await record_audit(entity_type="stage_model", entity_id=stage, action="stage.model",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"{stage} → {entry['label']}",
                       before={k: (before or {}).get(k) for k in ("provider", "model_name")},
                       after={"provider": provider, "model_name": model_name})
    return entry


async def set_stage_enabled(stage: str, enabled: bool, admin: dict) -> None:
    from services.audit_service import record_audit

    if stage not in TOGGLEABLE_STAGES:
        raise ValueError("المرحلة دي أساسية وشغّالة دايماً")
    cfg = await db.pipeline_config.find_one({"id": "default"}, {"_id": 0}) or {}
    stages = cfg.get("stages") or {k: dict(v) for k, v in DEFAULT_PIPELINE["stages"].items()}
    before = bool((stages.get(stage) or {}).get("enabled"))
    stages.setdefault(stage, dict(DEFAULT_PIPELINE["stages"].get(stage) or {}))["enabled"] = enabled
    await db.pipeline_config.update_one({"id": "default"},
                                        {"$set": {"stages": stages, "updated_at": _now()},
                                         "$setOnInsert": {"order": DEFAULT_PIPELINE["order"]}},
                                        upsert=True)
    await record_audit(entity_type="stage_model", entity_id=stage, action="stage.enabled",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"{stage} {'شغّالة' if enabled else 'مقفولة'}",
                       before={"enabled": before}, after={"enabled": enabled})


async def set_premium_video_model(model_name: str, admin: dict) -> dict:
    from services.audit_service import record_audit

    entry = await find_model("kling", model_name)
    if not entry or entry["capability"] != "video" or not entry.get("active"):
        raise ValueError("اختار موديل فيديو مفعّل من الكتالوج")
    before = await premium_video_model()
    await db.engine_settings.update_one({"id": "default"},
                                        {"$set": {"video_premium": {"provider": "kling", "model_name": model_name},
                                                  "updated_at": _now()}}, upsert=True)
    from services import engine_config
    engine_config.invalidate()
    await record_audit(entity_type="stage_model", entity_id="video_premium", action="video.premium",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"الجودة الفاخرة → {entry['label']}",
                       before={"model_name": before}, after={"model_name": model_name})
    return entry


# ---------------------------------------------------------------- presets
async def preset_is_valid(preset: dict) -> bool:
    """Every model the preset would set is an active, executable catalog model."""
    for stage, m in (preset.get("stage_map") or {}).items():
        cap = CAPABILITY_OF_STAGE.get(stage)
        entry = await find_model(m.get("provider"), m.get("model_name"))
        if not cap or not entry or not entry.get("active") or entry["capability"] != cap \
                or m.get("provider") not in EXECUTORS[cap] or not fits_stage(m.get("provider"), stage):
            return False
    return True
