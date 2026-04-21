"""Seed Phase A admin config collections:
  * model_registry       — one entry per stage
  * prompt_templates     — default templates for prompt-bearing stages
  * pipeline_config      — default ordering + per-stage flags

Idempotent: safe to re-run. Existing docs with `id`/`stage_key` are left alone
unless explicitly replaced. Running this on a fresh DB is the recommended way
to bootstrap the admin UI so it has something to display.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import db  # noqa: E402
from services.config_service import (  # noqa: E402
    DEFAULT_MODELS,
    DEFAULT_PIPELINE,
    STAGE_DISPLAY_NAMES,
)


CHILD_CHARACTER_I2I_PROMPT = """Create a highly stylized 2D children's storybook character based on my uploaded child photo, making it more cartoonish than the reference image while preserving the child's exact recognizable identity. Keep the same unique facial features clearly visible: face shape, hairstyle, hair volume and flow, eyebrow shape, eye shape, nose, smile, cheeks, skin tone, and overall sweet expression. Use a premium children's book animation style with clean elegant linework, soft simplified painterly shading, warm appealing colors, charming proportions, and a cute expressive design that feels hand-crafted, emotional, and ready for an animated story world.

Generate ONE single full-body standing version of the child only, centered in the frame, with transparent background. The child should be standing in a natural relaxed pose, front-facing or slight 3/4 view, with the full body clearly visible from head to toe, feet fully shown, arms and hands clearly separated from the body, legs clearly readable, clean silhouette, no overlapping limbs, no cropped parts, no props, no background, no scenery, no extra characters, no duplicate pose, no text.

The result must feel like a professional animated children's story character design made for motion use, with strong identity preservation and animation-friendly structure for later rigging and video movement. Clean PNG look, transparent background, consistent character design, studio-quality 2D cartoon, expressive but simple enough for animation, adorable, polished, cinematic children's book feel."""


DEFAULT_PROMPTS = {
    "scenario_generation": {
        "name": "توليد 3 سيناريوهات عربية للطفل — قالب فارغ",
        "description": "قالب فارغ افتراضي (غير مُفعّل). الخدمة تستخدم القالب الـhardcoded. أنشئ v2 من الأدمن لتخصيص القالب.",
        "template_text": "",
        "variables": [],
        "active_by_default": False,
    },
    "production_planning": {
        "name": "خطة إنتاج كاملة (mega-JSON) — قالب فارغ",
        "description": "قالب فارغ افتراضي (غير مُفعّل). الخدمة تستخدم القالب الـhardcoded. أنشئ v2 من الأدمن لتخصيص القالب.",
        "template_text": "",
        "variables": [],
        "active_by_default": False,
    },
    "child_character_i2i": {
        "name": "تحويل صورة الطفل لشخصية كرتونية كاملة الجسم",
        "description": "القالب الافتراضي لخطوة I2I — تحويل صورة حقيقية إلى character sheet قابل لإعادة الاستخدام",
        "template_text": CHILD_CHARACTER_I2I_PROMPT,
        "variables": [],
        "active_by_default": True,
    },
    "scene_image_generation": {
        "name": "توليد صور المشاهد بـNano Banana — قالب فارغ",
        "description": "قالب فارغ افتراضي (غير مُفعّل). الخدمة تُولّد البرومبت ديناميكياً لكل مشهد.",
        "template_text": "",
        "variables": [],
        "active_by_default": False,
    },
}


def _now():
    return datetime.now(timezone.utc).isoformat()


async def seed_model_registry():
    for stage_key, defaults in DEFAULT_MODELS.items():
        existing = await db.model_registry.find_one({"stage_key": stage_key})
        if existing:
            print(f"  [skip] model_registry[{stage_key}] already exists")
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "stage_key": stage_key,
            "stage_name_ar": STAGE_DISPLAY_NAMES[stage_key]["ar"],
            "stage_name_en": STAGE_DISPLAY_NAMES[stage_key]["en"],
            "provider": defaults["provider"],
            "model_name": defaults["model_name"],
            "fallback_provider": defaults.get("fallback_provider"),
            "fallback_model": defaults.get("fallback_model"),
            "env_key": defaults.get("env_key"),
            "active": True,
            "notes": "",
            "last_test_status": None,
            "last_test_at": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.model_registry.insert_one(doc)
        print(f"  [added] model_registry[{stage_key}] → {defaults['provider']}/{defaults['model_name']}")


async def seed_prompt_templates():
    for stage_key, meta in DEFAULT_PROMPTS.items():
        existing = await db.prompt_templates.find_one({"stage_key": stage_key, "version": 1})
        if existing:
            print(f"  [skip] prompt_templates[{stage_key} v1] already exists")
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "stage_key": stage_key,
            "name": meta["name"],
            "description": meta["description"],
            "template_text": meta["template_text"],
            "variables": meta["variables"],
            "version": 1,
            "active": meta.get("active_by_default", False),
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.prompt_templates.insert_one(doc)
        print(f"  [added] prompt_templates[{stage_key} v1 active={doc['active']}]")


async def seed_pipeline_config():
    existing = await db.pipeline_config.find_one({"id": "default"})
    if existing:
        print("  [skip] pipeline_config[default] already exists")
        return
    doc = {
        "id": "default",
        **DEFAULT_PIPELINE,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.pipeline_config.insert_one(doc)
    print("  [added] pipeline_config[default]")


async def main():
    print("=== Seeding model_registry ===")
    await seed_model_registry()
    print("\n=== Seeding prompt_templates ===")
    await seed_prompt_templates()
    print("\n=== Seeding pipeline_config ===")
    await seed_pipeline_config()
    print("\n✅ Done. Admin UI will now reflect these defaults.")


if __name__ == "__main__":
    asyncio.run(main())
