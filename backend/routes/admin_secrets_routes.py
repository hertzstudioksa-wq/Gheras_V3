"""Admin secrets routes — Wave 2 + Phase H.

Phase H additions:
  * `PUT /admin/secrets/{env_key}`  — encrypted secure override (never echoes raw)
  * `DELETE /admin/secrets/{env_key}` — remove an override (falls back to .env)
  * `POST /admin/secrets/test/{provider}` — provider connectivity test
  * `POST /admin/secrets/test-all`        — test every supported provider in parallel

Security guarantees:
  * The frontend NEVER sees the raw secret value after save.
  * Overrides are stored in `secret_overrides` collection encrypted with
    Fernet. See services/secret_overrides_service.py.
  * Resolution precedence used everywhere: secure_override → process .env → None.
"""
import os
from fastapi import APIRouter, Depends, HTTPException

from auth import require_admin
from services.config_service import PROVIDER_ENV_MAP
from services.secret_overrides_service import (
    list_overrides_status, set_override, delete_override,
    secret_source, encryption_available,
)
from services.provider_test_service import test_provider, test_all_providers, PROVIDERS
from services.audit_service import record_audit

router = APIRouter(
    prefix="/admin/secrets",
    tags=["admin-secrets"],
    dependencies=[Depends(require_admin)],
)


# Curated list — env keys the platform actually consults. Order matters for UI.
KNOWN_ENV_KEYS: list[dict] = [
    {
        "key": "OPENAI_API_KEY",
        "label": "OpenAI",
        "providers": ["openai"],
        "purpose": "صور الكتاب: شخصية الطفل + صور المشاهد + الغلاف (GPT Image)",
        "rotation_instructions": (
            "استخدم زرّ 'تحديث آمن' أعلاه — يُحفظ مشفّراً في DB ولا يحتاج إعادة تشغيل.\n"
            "أو يدوياً: ضع المفتاح في .env تحت OPENAI_API_KEY ثم: sudo supervisorctl restart backend."
        ),
        "test_provider_key": "openai",
    },
    {
        "key": "ANTHROPIC_API_KEY",
        "label": "Anthropic (Claude)",
        "providers": ["anthropic"],
        "purpose": "كتابة القصة: السيناريوهات + خطة الإنتاج (Claude)",
        "rotation_instructions": (
            "أنشئ مفتاحاً جديداً من console.anthropic.com → API Keys، "
            "ضعه في .env تحت ANTHROPIC_API_KEY ثم أعد تشغيل خدمة gheras، واحذف القديم من الكونسول."
        ),
        "test_provider_key": "anthropic",
    },
    {
        "key": "GEMINI_API_KEY",
        "label": "Google Gemini (اختبار)",
        "providers": ["gemini"],
        "purpose": "بديل مجاني للتجربة: نصوص + صور (preset \"Gemini Free (testing)\"). مش للإنتاج — الطبقة المجانية ممكن جوجل تستخدم بياناتها في التدريب، فممنوع صور أطفال حقيقيين.",
        "rotation_instructions": (
            "أنشئ مفتاحاً من aistudio.google.com → Get API key، ضعه في .env تحت GEMINI_API_KEY "
            "ثم أعد تشغيل خدمة gheras."
        ),
        "test_provider_key": "gemini",
    },
    {
        "key": "ELEVENLABS_API_KEY",
        "label": "ElevenLabs (TTS + Music)",
        "providers": ["elevenlabs"],
        "purpose": "Text-to-Speech للسرد العربي + Music API لخلفية الفيديو (Music API يحتاج خطّة Creator+).",
        "rotation_instructions": (
            "1) سجّل دخول إلى https://elevenlabs.io/app/settings/api-keys\n"
            "2) أنشئ مفتاحاً جديداً.\n"
            "3) استخدم زرّ 'تحديث آمن' هنا — لا يحتاج إعادة تشغيل.\n"
            "4) للـ Music API: تأكّد أنّ خطّتك Creator+ أو أعلى."
        ),
        "test_provider_key": "elevenlabs",
        "extra_test_keys": ["elevenlabs_music"],
        "optional": True,
    },
    {
        "key": "FAL_KEY",
        "label": "fal.ai (legacy shared — optional fallback)",
        "providers": ["kling", "luma", "fal_image", "fal_tts", "fal_music"],
        "purpose": "مفتاح fal.ai الافتراضي — يُستخدم كـ fallback فقط عند غياب المفاتيح المتخصّصة لكل قدرة (FAL_KEY_SCENE / FAL_KEY_NARRATION / FAL_KEY_MUSIC / FAL_KEY_VIDEO).",
        "rotation_instructions": (
            "استخدم مفاتيح متخصّصة لكل قدرة بدلاً من هذا. هذا المفتاح اختياري ويعمل كغطاء."
        ),
        "test_provider_key": "fal",
        "optional": True,
    },
    {
        "key": "FAL_KEY_SCENE",
        "label": "fal.ai — Images (Gemini Nano Banana)",
        "providers": ["fal_image"],
        "purpose": "يُستخدم لتوليد صور المشاهد + صفحات الكتاب (fal-ai/gemini-25-flash-image). عزل الفوترة لقدرة الصور فقط.",
        "rotation_instructions": (
            "1) https://fal.ai/dashboard/keys\n"
            "2) أنشئ مفتاحاً جديداً مخصَّصاً لقدرة Images فقط.\n"
            "3) ضعه هنا — لا يحتاج إعادة تشغيل."
        ),
        "test_provider_key": "fal_scene",
        "optional": True,
    },
    {
        "key": "FAL_KEY_NARRATION",
        "label": "fal.ai — ElevenLabs TTS (narration)",
        "providers": ["fal_tts"],
        "purpose": "يُستخدم لتوليد السرد الصوتي العربي (fal-ai/elevenlabs/tts/multilingual-v2). بديل أنظف من مفتاح ElevenLabs المباشر (لا يحتاج خطّة Creator+).",
        "rotation_instructions": "أنشئ مفتاحاً مخصَّصاً لقدرة TTS من لوحة fal.ai.",
        "test_provider_key": "fal_narration",
        "optional": True,
    },
    {
        "key": "FAL_KEY_MUSIC",
        "label": "fal.ai — ElevenLabs Music",
        "providers": ["fal_music"],
        "purpose": "يُستخدم لموسيقى خلفيّة الفيديو (fal-ai/elevenlabs/music). يتجنّب قيد خطّة ElevenLabs المباشر.",
        "rotation_instructions": "أنشئ مفتاحاً مخصَّصاً لقدرة Music من لوحة fal.ai.",
        "test_provider_key": "fal_music",
        "optional": True,
    },
    {
        "key": "FAL_KEY_VIDEO",
        "label": "fal.ai — Kling Video",
        "providers": ["kling", "luma"],
        "purpose": "يُستخدم لتوليد لقطات الفيديو per-scene (fal-ai/kling-video/v3/pro/image-to-video).",
        "rotation_instructions": "أنشئ مفتاحاً مخصَّصاً لقدرة Video من لوحة fal.ai.",
        "test_provider_key": "fal_video",
        "optional": True,
    },
    {
        "key": "MOYASAR_SECRET_KEY",
        "label": "Moyasar — ميسر",
        "providers": ["moyasar"],
        "test_provider_key": "moyasar",
        "purpose": "بوابة الدفع (مدى، فيزا/ماستركارد، Apple Pay). مفتاح sk_test للتجربة وsk_live للتشغيل الحقيقي.",
        "rotation_instructions": (
            "1) لوحة ميسر ← Settings ← API Keys\n"
            "2) انسخ Secret Key (sk_test_… للتجربة) واحفظه هنا بزرار التحديث الآمن.\n"
            "3) جرّبه من صفحة المدفوعات ← اختبار المفتاح."
        ),
        "optional": True,
    },
    {
        "key": "SMTP_URL",
        "label": "SMTP — إيميلات الإشعارات",
        "providers": ["smtp"],
        "purpose": "صندوق إيميل بيبعت منه غِراس إشعارات العملاء والتشغيل (أي مزوّد: Zoho، Google Workspace، Resend، Brevo…).",
        "rotation_instructions": (
            "اكتبه بالشكل ده: smtps://USER:PASSWORD@smtp.example.com:465\n"
            "أو smtp://USER:PASSWORD@smtp.example.com:587 (STARTTLS).\n"
            "لو كلمة السر فيها رموز زي @ أو / اكتبها مشفّرة (%40، %2F).\n"
            "بعد الحفظ جرّبه من إعدادات النظام ← جرّب الإيميل."
        ),
        "optional": True,
    },
    {
        "key": "MONGO_URL",
        "label": "MongoDB",
        "providers": ["mongo"],
        "purpose": "تخزين كل بيانات التطبيق (orders, scenarios, plans, …)",
        "rotation_instructions": (
            "MongoDB URL يُدار على مستوى البنية التحتية فقط.\n"
            "لا يمكن حفظه كـ override آمن. تواصل مع DevOps."
        ),
        "system": True,  # not user-rotatable via override
    },
]


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip()
    if len(v) <= 8:
        return "***"
    return f"***{v[-4:]}"


def _can_store_overrides() -> bool:
    """New overrides need a dedicated key; the MONGO_URL-derived fallback in
    secret_overrides_service is kept only so existing rows stay readable."""
    return bool(os.environ.get("SECRETS_ENCRYPTION_KEY")) and encryption_available()


@router.get("/status")
async def get_secrets_status():
    """Per-key status with override-aware fields.

    Per item:
      key, label, providers, purpose,
      configured: bool        — true if EITHER override OR env is set
      source: "override"|"env"|"missing"
      masked: "***ABCD"|null
      override_present: bool
      override_updated_at: iso|null
      override_updated_by: id|null
      rotation_instructions, system, optional
    """
    overrides = {o["env_key"]: o for o in await list_overrides_status()}

    items = []
    for spec in KNOWN_ENV_KEYS:
        key = spec["key"]
        env_val = os.environ.get(key) or ""
        ov = overrides.get(key)
        # Source resolution
        source = await secret_source(key)
        if source == "override":
            masked = ov.get("masked")
        elif source == "env":
            masked = _mask(env_val)
        else:
            masked = None
        items.append({
            "key": key,
            "label": spec["label"],
            "providers": spec.get("providers") or [],
            "purpose": spec.get("purpose") or "",
            "configured": source != "missing",
            "source": source,
            "masked": masked,
            "override_present": bool(ov),
            "override_updated_at": (ov or {}).get("updated_at"),
            "override_updated_by": (ov or {}).get("updated_by"),
            "rotation_instructions": spec.get("rotation_instructions") or "",
            "system": bool(spec.get("system", False)),
            "optional": bool(spec.get("optional", False)),
            "test_provider_key": spec.get("test_provider_key"),
        })

    return {
        "items": items,
        "provider_env_map": dict(PROVIDER_ENV_MAP),
        "encryption_available": _can_store_overrides(),
        "supported_providers_for_test": list(PROVIDERS.keys()),
        "note_ar": (
            "تستطيع إضافة override آمن مشفّر في DB لأي مفتاح — لا يحتاج إعادة تشغيل ولا يكشف القيمة بعد الحفظ. "
            "ترتيب الأولوية: secure override → .env → غير موجود."
        ),
    }


# ---- Phase H — secure write/delete + provider tests -----------------------
@router.put("/{env_key}")
async def set_secret_override(env_key: str, payload: dict, admin=Depends(require_admin)):
    """Store an encrypted override for the given env_key. Raw value is
    encrypted with Fernet at rest and NEVER returned."""
    spec = next((s for s in KNOWN_ENV_KEYS if s["key"] == env_key), None)
    if not spec:
        raise HTTPException(status_code=404, detail="unknown env_key")
    if spec.get("system"):
        raise HTTPException(status_code=400, detail="system keys are not rotatable from admin")
    raw = (payload or {}).get("value")
    if not raw or not str(raw).strip():
        raise HTTPException(status_code=400, detail="value is required")
    if not _can_store_overrides():
        raise HTTPException(status_code=503,
                            detail="encryption not available — set SECRETS_ENCRYPTION_KEY in deployment")
    try:
        result = await set_override(env_key, str(raw), admin.get("id"))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"could not store override: {e}")

    await record_audit(
        entity_type="env_key",
        entity_id=env_key,
        action="secret_override.set",
        actor_id=admin.get("id"),
        actor_email=admin.get("email"),
        summary=f"Stored encrypted override for {env_key}",
        before={"override_present": False},
        after={"override_present": True, "masked": result.get("masked"),
               "rotated": result.get("rotated")},
    )
    return {"ok": True, "env_key": env_key, **result}


@router.delete("/{env_key}")
async def remove_secret_override(env_key: str, admin=Depends(require_admin)):
    """Remove an override. Resolution will fall back to .env."""
    spec = next((s for s in KNOWN_ENV_KEYS if s["key"] == env_key), None)
    if not spec:
        raise HTTPException(status_code=404, detail="unknown env_key")
    removed = await delete_override(env_key, admin.get("id"))
    if removed:
        await record_audit(
            entity_type="env_key",
            entity_id=env_key,
            action="secret_override.delete",
            actor_id=admin.get("id"),
            actor_email=admin.get("email"),
            summary=f"Deleted encrypted override for {env_key} (now resolves from .env)",
            before={"override_present": True},
            after={"override_present": False},
        )
    return {"ok": True, "env_key": env_key, "removed": removed}


@router.post("/test/{provider}")
async def test_one_provider(provider: str, admin=Depends(require_admin)):
    if provider not in PROVIDERS:
        raise HTTPException(status_code=400,
                             detail=f"unknown provider; supported: {list(PROVIDERS)}")
    res = await test_provider(provider)
    # Audit non-secretly.
    await record_audit(
        entity_type="provider",
        entity_id=provider,
        action="provider_test.run",
        actor_id=admin.get("id"),
        actor_email=admin.get("email"),
        summary=f"connectivity test {provider}: ok={res.get('ok')} latency={res.get('latency_ms')}ms",
        before=None,
        after={"ok": res.get("ok"), "auth_ok": res.get("auth_ok"),
               "secret_source": res.get("secret_source")},
    )
    return res


@router.post("/test-all")
async def test_all(admin=Depends(require_admin)):
    return {"results": await test_all_providers()}
