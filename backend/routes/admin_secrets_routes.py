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
        "purpose": "نصوص (gpt-5.2, gpt-5-mini) + صور (gpt-image-1) + رؤية (gpt-4o vision)",
        "rotation_instructions": (
            "استخدم زرّ 'تحديث آمن' أعلاه — يُحفظ مشفّراً في DB ولا يحتاج إعادة تشغيل.\n"
            "أو يدوياً: ضع المفتاح في .env تحت OPENAI_API_KEY ثم: sudo supervisorctl restart backend."
        ),
        "test_provider_key": "openai",
    },
    {
        "key": "EMERGENT_LLM_KEY",
        "label": "Emergent Universal Key",
        "providers": ["anthropic", "gemini", "openai-via-emergent"],
        "purpose": "Claude Sonnet 4.5 + Nano Banana + توليد الصور عبر بروكسي Emergent",
        "rotation_instructions": (
            "Profile → Universal Key على Emergent. ثم استخدم زرّ 'تحديث آمن' هنا."
        ),
        "test_provider_key": "emergent",
    },
    {
        "key": "ELEVENLABS_API_KEY",
        "label": "ElevenLabs (TTS)",
        "providers": ["elevenlabs"],
        "purpose": "Text-to-Speech للسرد العربي (يحلّ محلّ المحاكاة الحالية).",
        "rotation_instructions": (
            "1) سجّل دخول إلى https://elevenlabs.io/app/settings/api-keys\n"
            "2) أنشئ مفتاحاً جديداً.\n"
            "3) استخدم زرّ 'تحديث آمن' هنا — لا يحتاج إعادة تشغيل."
        ),
        "test_provider_key": "elevenlabs",
        "optional": True,
    },
    {
        "key": "FAL_KEY",
        "label": "fal.ai (Kling Video)",
        "providers": ["kling", "luma"],
        "purpose": "توليد فيديو حقيقي عبر fal.ai Kling (I2V/T2V). مفتاح واحد يدعم Kling و Luma على fal.ai.",
        "rotation_instructions": (
            "1) سجّل دخول إلى https://fal.ai/dashboard/keys\n"
            "2) أنشئ مفتاحاً جديداً (API scope كافٍ).\n"
            "3) استخدم زرّ 'تحديث آمن' هنا — لا يحتاج إعادة تشغيل."
        ),
        "test_provider_key": "fal",
        "optional": True,
    },
    {
        "key": "STRIPE_API_KEY",
        "label": "Stripe",
        "providers": ["stripe"],
        "purpose": "بوّابة الدفع (test/sandbox أو live).",
        "rotation_instructions": (
            "1) https://dashboard.stripe.com/apikeys\n"
            "2) Reveal sk_test أو sk_live → استخدم زرّ 'تحديث آمن' هنا."
        ),
        "test_provider_key": "stripe",
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
        "encryption_available": encryption_available(),
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
    if not encryption_available():
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
