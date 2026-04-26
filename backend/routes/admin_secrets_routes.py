"""Admin secrets routes — Wave 2.

READ-ONLY. The admin can:
  * see WHICH provider env keys are configured (boolean) and their masked tail
  * read static rotation instructions per provider

The admin CANNOT:
  * read full secret values
  * write/edit/delete secrets from the dashboard

This is by design — secrets live in the deployment's `.env` and are rotated
through the deployment pipeline, not through the user-facing admin UI.
"""
import os
from fastapi import APIRouter, Depends

from auth import require_admin
from services.config_service import PROVIDER_ENV_MAP

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
            "1) سجّل دخول إلى https://platform.openai.com/api-keys\n"
            "2) أنشئ مفتاحاً جديداً (Create new secret key)\n"
            "3) ضعه في deployment .env تحت OPENAI_API_KEY\n"
            "4) أعد تشغيل الـ backend: sudo supervisorctl restart backend\n"
            "5) عُد لهنا للتأكد من حالة Configured."
        ),
    },
    {
        "key": "EMERGENT_LLM_KEY",
        "label": "Emergent Universal Key",
        "providers": ["anthropic", "gemini", "openai-via-emergent"],
        "purpose": "Claude Sonnet 4.5 + Nano Banana + توليد الصور عبر بروكسي Emergent",
        "rotation_instructions": (
            "1) افتح Emergent Profile → Universal Key.\n"
            "2) أنشئ مفتاحاً جديداً أو زِد الرصيد عبر Add Balance.\n"
            "3) ضع المفتاح في deployment .env تحت EMERGENT_LLM_KEY.\n"
            "4) أعد تشغيل الـ backend.\n"
            "Note: لو الرصيد قارب الانتهاء فعّل Auto top-up من نفس الصفحة."
        ),
    },
    {
        "key": "MONGO_URL",
        "label": "MongoDB",
        "providers": ["mongo"],
        "purpose": "تخزين كل بيانات التطبيق (orders, scenarios, plans, …)",
        "rotation_instructions": (
            "MongoDB URL يُدار على مستوى البنية التحتية فقط.\n"
            "لا تغيّره من هذه اللوحة. إن احتجت تغيير URL تواصل مع DevOps."
        ),
        "system": True,  # not user-rotatable
    },
]


def _mask(value: str | None) -> str | None:
    """Return a masked tail for safe display. None for empty values."""
    if not value:
        return None
    v = value.strip()
    if len(v) <= 8:
        return "***"
    return f"***{v[-4:]}"


@router.get("/status")
async def get_secrets_status():
    """Return read-only status for all known env keys.

    Response shape (per key):
      {
        key, label, providers, purpose,
        configured: bool,
        masked: "***ABCD" | null,
        last_modified: null,           # not tracked — env-managed
        rotation_instructions: "...",
        system: bool                   # true for non-user-rotatable
      }
    """
    items = []
    for spec in KNOWN_ENV_KEYS:
        raw = os.environ.get(spec["key"]) or ""
        items.append({
            "key": spec["key"],
            "label": spec["label"],
            "providers": spec.get("providers") or [],
            "purpose": spec.get("purpose") or "",
            "configured": bool(raw.strip()),
            "masked": _mask(raw),
            "last_modified": None,
            "rotation_instructions": spec.get("rotation_instructions") or "",
            "system": bool(spec.get("system", False)),
        })

    # Provide the provider→env map so the UI can mark which Admin model rows
    # are missing their credential.
    provider_env_map = dict(PROVIDER_ENV_MAP)

    return {
        "items": items,
        "provider_env_map": provider_env_map,
        "note_ar": (
            "هذه اللوحة للقراءة فقط لأسباب أمنية. "
            "لتدوير أي مفتاح اتبع تعليمات الـ rotation أدناه ثم أعد تشغيل الخدمة."
        ),
    }
