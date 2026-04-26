"""Preset Stacks — Phase H.

A Preset Stack is a named bundle that maps stage_key → {provider, model_name,
env_key, notes}. Applying a preset writes those mappings into `model_registry`.

Crucially:
  * Presets NEVER store raw API keys. They only reference `env_key` names
    that the secret system already manages.
  * Applying a preset only updates `model_registry` rows in the listed
    stage_map; unrelated stages are untouched.
  * For preview-only / not-yet-wired / local-binary / reuse-from-other-stage
    stages, the preset can still register a desired provider/model, but the
    stage won't suddenly become executable. The dry-run report surfaces this.

Collections:
  preset_stacks       — { id, name, slug, description, intended_use, is_seeded,
                          is_active, stage_map, created_at, updated_at,
                          created_by, updated_by }

Active preset:
  Only ONE preset can be marked is_active=True at a time. Activation does NOT
  imply auto-apply on every restart — admin still applies explicitly. The
  flag is purely a UI hint ("currently selected stack").
"""
from __future__ import annotations

import os
import re
import uuid
import logging
from datetime import datetime, timezone

from db import db
from services.config_service import DEFAULT_MODELS, STAGE_DISPLAY_NAMES
from services.stage_lab_service import EXECUTOR_STATUS, SUPPORTED_STAGES
from services.audit_service import record_audit
from services.secret_overrides_service import secret_source

logger = logging.getLogger("preset_stacks")

COLLECTION = "preset_stacks"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or f"preset-{uuid.uuid4().hex[:6]}"


# ---- CRUD ------------------------------------------------------------------
async def list_presets() -> list[dict]:
    rows = await db[COLLECTION].find({}, {"_id": 0}).sort("created_at", 1).to_list(100)
    return rows


async def get_preset(preset_id: str) -> dict | None:
    return await db[COLLECTION].find_one({"id": preset_id}, {"_id": 0})


async def create_preset(payload: dict, admin_id: str | None,
                         admin_email: str | None,
                         is_seeded: bool = False) -> dict:
    name = (payload.get("name") or "").strip()
    if not name:
        raise ValueError("name required")
    stage_map = payload.get("stage_map") or {}
    _validate_stage_map(stage_map)
    slug = (payload.get("slug") or _slug(name)).strip()

    # Slug uniqueness
    if await db[COLLECTION].find_one({"slug": slug}, {"_id": 1}):
        slug = f"{slug}-{uuid.uuid4().hex[:4]}"

    now = _now()
    doc = {
        "id":            str(uuid.uuid4()),
        "name":          name,
        "slug":          slug,
        "description":   payload.get("description") or "",
        "intended_use":  payload.get("intended_use") or "general",
        "is_seeded":     bool(is_seeded),
        "is_active":     False,
        "stage_map":     stage_map,
        "created_at":    now,
        "updated_at":    now,
        "created_by":    admin_id,
        "updated_by":    admin_id,
    }
    await db[COLLECTION].insert_one(doc)
    await record_audit(
        entity_type="preset_stack", entity_id=doc["id"],
        action="preset.create", actor_id=admin_id, actor_email=admin_email,
        summary=f"created preset '{name}' ({len(stage_map)} stages)",
        before=None, after={"name": name, "stages": list(stage_map.keys())},
    )
    return doc


async def update_preset(preset_id: str, payload: dict, admin_id: str | None,
                         admin_email: str | None) -> dict | None:
    cur = await get_preset(preset_id)
    if not cur:
        return None
    patch = {k: v for k, v in payload.items()
             if k in ("name", "description", "intended_use", "stage_map") and v is not None}
    if "stage_map" in patch:
        _validate_stage_map(patch["stage_map"])
    patch["updated_at"] = _now()
    patch["updated_by"] = admin_id
    await db[COLLECTION].update_one({"id": preset_id}, {"$set": patch})
    after = await get_preset(preset_id)
    await record_audit(
        entity_type="preset_stack", entity_id=preset_id,
        action="preset.update", actor_id=admin_id, actor_email=admin_email,
        summary=f"updated preset '{cur.get('name')}'",
        before={"name": cur.get("name"), "stages": list((cur.get("stage_map") or {}).keys())},
        after={"name": after.get("name"), "stages": list((after.get("stage_map") or {}).keys())},
    )
    return after


async def clone_preset(preset_id: str, new_name: str | None,
                        admin_id: str | None, admin_email: str | None) -> dict | None:
    cur = await get_preset(preset_id)
    if not cur:
        return None
    name = (new_name or f"{cur.get('name')} (clone)").strip()
    return await create_preset(
        {
            "name": name,
            "description": cur.get("description"),
            "intended_use": cur.get("intended_use"),
            "stage_map": cur.get("stage_map", {}),
        },
        admin_id, admin_email, is_seeded=False,
    )


async def delete_preset(preset_id: str, admin_id: str | None,
                         admin_email: str | None) -> bool:
    cur = await get_preset(preset_id)
    if not cur:
        return False
    if cur.get("is_seeded"):
        # Soft-delete: archive but keep the row. This protects the seed set.
        await db[COLLECTION].update_one(
            {"id": preset_id},
            {"$set": {"is_archived": True, "is_active": False,
                      "updated_at": _now(), "updated_by": admin_id}},
        )
        archived = True
    else:
        await db[COLLECTION].delete_one({"id": preset_id})
        archived = False
    await record_audit(
        entity_type="preset_stack", entity_id=preset_id,
        action="preset.delete", actor_id=admin_id, actor_email=admin_email,
        summary=f"{'archived' if archived else 'deleted'} preset '{cur.get('name')}'",
        before={"name": cur.get("name")}, after=None,
    )
    return True


# ---- Dry-run + Apply -------------------------------------------------------
async def dry_run(preset_id: str) -> dict:
    """Compute what WOULD change if this preset were applied right now."""
    p = await get_preset(preset_id)
    if not p:
        raise ValueError("preset not found")

    diff: list[dict] = []
    warnings: list[str] = []

    for stage_key, target in (p.get("stage_map") or {}).items():
        cur_doc = await db.model_registry.find_one(
            {"stage_key": stage_key, "active": True}, {"_id": 0},
        )
        cur = cur_doc or DEFAULT_MODELS.get(stage_key, {})
        new = {
            "provider":    target.get("provider")    or cur.get("provider"),
            "model_name":  target.get("model_name")  or cur.get("model_name"),
            "env_key":     target.get("env_key")     or cur.get("env_key"),
        }
        changed = (new["provider"] != cur.get("provider")
                    or new["model_name"] != cur.get("model_name")
                    or new["env_key"] != cur.get("env_key"))
        env_key = new["env_key"]
        secret_status = await secret_source(env_key) if env_key else "n/a"
        executor_status = EXECUTOR_STATUS.get(stage_key, "preview-only")

        diff.append({
            "stage_key": stage_key,
            "stage_name_ar": (STAGE_DISPLAY_NAMES.get(stage_key) or {}).get("ar") or stage_key,
            "current": {"provider": cur.get("provider"), "model_name": cur.get("model_name"),
                        "env_key": cur.get("env_key")},
            "new": new,
            "changed": changed,
            "executor_status": executor_status,
            "executor_warning": _executor_warning(executor_status),
            "secret_status": secret_status,        # override | env | missing | n/a
            "secret_warning": (secret_status == "missing" and env_key is not None),
            "notes": target.get("notes") or "",
        })
        if env_key and secret_status == "missing":
            warnings.append(f"{stage_key}: السرّ {env_key} غير موجود (override أو env)")
        if executor_status in ("not-yet-wired", "preview-only"):
            warnings.append(f"{stage_key}: لن يصبح قابلاً للتشغيل بمجرّد التطبيق "
                            f"(executor_status={executor_status})")

    unchanged_count = sum(1 for d in diff if not d["changed"])
    changed_count = len(diff) - unchanged_count
    return {
        "preset_id": preset_id,
        "preset_name": p.get("name"),
        "diff": diff,
        "summary": {
            "stages_in_preset": len(diff),
            "stages_changed": changed_count,
            "stages_unchanged": unchanged_count,
            "missing_secrets": [d["stage_key"] for d in diff if d["secret_warning"]],
            "non_executable_stages": [d["stage_key"] for d in diff
                                       if d["executor_status"] in ("not-yet-wired",
                                                                    "preview-only",
                                                                    "local-binary",
                                                                    "reuse-from-other-stage")],
        },
        "warnings": warnings,
    }


def _executor_warning(status: str) -> str | None:
    return {
        "not-yet-wired":          "لا يوجد executor فعلي بعد — التطبيق لا يجعل المرحلة قابلة للتشغيل.",
        "preview-only":           "lab يقدّم معاينة فقط — التشغيل الحقيقي يحدث داخل خط الإنتاج.",
        "local-binary":           "يعمل محلّياً بـ ffmpeg/reportlab — لا تأثير لـ provider/model.",
        "reuse-from-other-stage": "يُعيد استخدام مخرَج مرحلة أخرى (مثل book_page → scene_image).",
    }.get(status)


async def apply_preset(preset_id: str, admin_id: str | None,
                        admin_email: str | None) -> dict:
    """Apply: write preset stage_map into model_registry. Mark preset as the
    one is_active=True (deactivating others). Audit each stage diff."""
    p = await get_preset(preset_id)
    if not p:
        raise ValueError("preset not found")

    dry = await dry_run(preset_id)
    now = _now()

    applied = []
    for d in dry["diff"]:
        if not d["changed"]:
            continue
        stage_key = d["stage_key"]
        new = d["new"]
        existing = await db.model_registry.find_one({"stage_key": stage_key})
        patch = {
            "provider":   new["provider"],
            "model_name": new["model_name"],
            "env_key":    new["env_key"],
            "active":     True,
            "updated_at": now,
            "applied_by_preset_id": p["id"],
            "applied_by_preset_name": p["name"],
        }
        if existing:
            await db.model_registry.update_one(
                {"stage_key": stage_key}, {"$set": patch},
            )
        else:
            base = DEFAULT_MODELS.get(stage_key, {})
            await db.model_registry.insert_one({
                "id": str(uuid.uuid4()),
                "stage_key": stage_key,
                "stage_name_ar": (STAGE_DISPLAY_NAMES.get(stage_key) or {}).get("ar") or stage_key,
                "stage_name_en": (STAGE_DISPLAY_NAMES.get(stage_key) or {}).get("en") or stage_key,
                "fallback_provider": base.get("fallback_provider"),
                "fallback_model":    base.get("fallback_model"),
                "notes": "",
                "created_at": now,
                **patch,
            })
        applied.append(stage_key)

    # Activate this preset, deactivate others.
    await db[COLLECTION].update_many({"id": {"$ne": p["id"]}}, {"$set": {"is_active": False}})
    await db[COLLECTION].update_one(
        {"id": p["id"]},
        {"$set": {"is_active": True, "applied_at": now,
                  "applied_by": admin_id, "updated_at": now}},
    )

    await record_audit(
        entity_type="preset_stack", entity_id=p["id"],
        action="preset.apply", actor_id=admin_id, actor_email=admin_email,
        summary=f"applied preset '{p.get('name')}' to {len(applied)} stages",
        before=None,
        after={"applied_stages": applied,
               "warnings_count": len(dry.get("warnings") or [])},
    )

    return {
        "ok": True,
        "preset_id": p["id"],
        "preset_name": p["name"],
        "applied_stages": applied,
        "warnings": dry.get("warnings") or [],
        "dry_run": dry,
    }


async def get_active_preset() -> dict | None:
    return await db[COLLECTION].find_one(
        {"is_active": True, "is_archived": {"$ne": True}}, {"_id": 0},
    )


# ---- Validation -----------------------------------------------------------
def _validate_stage_map(sm: dict) -> None:
    if not isinstance(sm, dict):
        raise ValueError("stage_map must be a dict")
    for k, v in sm.items():
        if k not in SUPPORTED_STAGES:
            raise ValueError(f"unknown stage_key: {k}")
        if not isinstance(v, dict):
            raise ValueError(f"stage_map[{k}] must be a dict")
        # Reject anything that smells like a raw secret.
        for sus in ("api_key", "secret", "value", "raw"):
            if sus in v:
                raise ValueError(f"stage_map[{k}] must not contain raw secret field '{sus}'")


# ---- Seeded presets --------------------------------------------------------
SEEDED_PRESETS = [
    {
        "name": "OpenAI Full Stack",
        "slug": "openai-full",
        "description": "Text via GPT-5.2/5-mini, all images via gpt-image-1, downstream stages stay as-is until executors are wired.",
        "intended_use": "production",
        "stage_map": {
            "scenario_generation":      {"provider": "openai",   "model_name": "gpt-5-mini",   "env_key": "OPENAI_API_KEY"},
            "production_planning":      {"provider": "openai",   "model_name": "gpt-5.2",      "env_key": "OPENAI_API_KEY"},
            "child_character_i2i":      {"provider": "openai",   "model_name": "gpt-image-1",  "env_key": "OPENAI_API_KEY"},
            "extra_character_i2i":      {"provider": "openai",   "model_name": "gpt-image-1",  "env_key": "OPENAI_API_KEY"},
            "scene_image_generation":   {"provider": "openai",   "model_name": "gpt-image-1",  "env_key": "OPENAI_API_KEY"},
            "book_page_image_generation": {"provider": "openai", "model_name": "gpt-image-1",  "env_key": "OPENAI_API_KEY",
                                            "notes": "stage reuses scene_image today; preset registers intended provider for future."},
            "narration_generation":     {"provider": "openai",   "model_name": "tts-1-hd",     "env_key": "OPENAI_API_KEY",
                                            "notes": "executor not wired yet — preview only."},
        },
    },
    {
        "name": "Gemini Visual Stack",
        "slug": "gemini-visual",
        "description": "Text on Claude Sonnet (stable). All visuals on Gemini Nano Banana.",
        "intended_use": "production",
        "stage_map": {
            "scenario_generation":      {"provider": "anthropic", "model_name": "claude-sonnet-4-5-20250929", "env_key": "EMERGENT_LLM_KEY"},
            "production_planning":      {"provider": "anthropic", "model_name": "claude-sonnet-4-5-20250929", "env_key": "EMERGENT_LLM_KEY"},
            "scene_image_generation":   {"provider": "gemini",    "model_name": "gemini-3.1-flash-image-preview", "env_key": "EMERGENT_LLM_KEY"},
            "book_page_image_generation": {"provider": "gemini",  "model_name": "gemini-3.1-flash-image-preview", "env_key": "EMERGENT_LLM_KEY",
                                            "notes": "reuses scene image today."},
            # Keep i2i on OpenAI (Gemini doesn't have a direct i2i analogue).
            "child_character_i2i":      {"provider": "openai",    "model_name": "gpt-image-1", "env_key": "OPENAI_API_KEY"},
            "extra_character_i2i":      {"provider": "openai",    "model_name": "gpt-image-1", "env_key": "OPENAI_API_KEY"},
        },
    },
    {
        "name": "Low-Cost Stack",
        "slug": "low-cost",
        "description": "Cheapest viable models. Quality may drop. Useful for QA/regression sweeps.",
        "intended_use": "low_cost",
        "stage_map": {
            "scenario_generation":      {"provider": "openai",   "model_name": "gpt-5-mini",  "env_key": "OPENAI_API_KEY"},
            "production_planning":      {"provider": "openai",   "model_name": "gpt-5-mini",  "env_key": "OPENAI_API_KEY"},
            "scene_image_generation":   {"provider": "gemini",   "model_name": "gemini-3.1-flash-image-preview", "env_key": "EMERGENT_LLM_KEY"},
            "book_page_image_generation": {"provider": "gemini", "model_name": "gemini-3.1-flash-image-preview", "env_key": "EMERGENT_LLM_KEY"},
            "child_character_i2i":      {"provider": "openai",   "model_name": "gpt-image-1", "env_key": "OPENAI_API_KEY"},
            "extra_character_i2i":      {"provider": "openai",   "model_name": "gpt-image-1", "env_key": "OPENAI_API_KEY"},
        },
    },
    {
        "name": "High-Fidelity Stack",
        "slug": "high-fidelity",
        "description": "Premium models everywhere. Higher cost. Use for hero customer orders.",
        "intended_use": "high_fidelity",
        "stage_map": {
            "scenario_generation":      {"provider": "openai",    "model_name": "gpt-5.2",      "env_key": "OPENAI_API_KEY"},
            "production_planning":      {"provider": "openai",    "model_name": "gpt-5.2",      "env_key": "OPENAI_API_KEY"},
            "scene_image_generation":   {"provider": "openai",    "model_name": "gpt-image-1.5","env_key": "OPENAI_API_KEY"},
            "book_page_image_generation": {"provider": "openai",  "model_name": "gpt-image-1.5","env_key": "OPENAI_API_KEY"},
            "child_character_i2i":      {"provider": "openai",    "model_name": "gpt-image-1.5","env_key": "OPENAI_API_KEY"},
            "extra_character_i2i":      {"provider": "openai",    "model_name": "gpt-image-1.5","env_key": "OPENAI_API_KEY"},
        },
    },
    {
        "name": "Safe Production Stack",
        "slug": "safe-production",
        "description": "Currently stable mappings (Anthropic text + Gemini image + OpenAI i2i). Default for trusted customer orders.",
        "intended_use": "production",
        "stage_map": {
            "scenario_generation":      {"provider": "anthropic", "model_name": "claude-sonnet-4-5-20250929", "env_key": "EMERGENT_LLM_KEY"},
            "production_planning":      {"provider": "anthropic", "model_name": "claude-sonnet-4-5-20250929", "env_key": "EMERGENT_LLM_KEY"},
            "scene_image_generation":   {"provider": "gemini",    "model_name": "gemini-3.1-flash-image-preview", "env_key": "EMERGENT_LLM_KEY"},
            "child_character_i2i":      {"provider": "openai",    "model_name": "gpt-image-1", "env_key": "OPENAI_API_KEY"},
            "extra_character_i2i":      {"provider": "openai",    "model_name": "gpt-image-1", "env_key": "OPENAI_API_KEY"},
        },
    },
]


async def seed_default_presets() -> int:
    """Idempotent — only inserts presets that don't already exist by slug."""
    inserted = 0
    for spec in SEEDED_PRESETS:
        if await db[COLLECTION].find_one({"slug": spec["slug"]}, {"_id": 1}):
            continue
        now = _now()
        await db[COLLECTION].insert_one({
            "id":            str(uuid.uuid4()),
            "name":          spec["name"],
            "slug":          spec["slug"],
            "description":   spec["description"],
            "intended_use":  spec["intended_use"],
            "is_seeded":     True,
            "is_active":     False,
            "is_archived":   False,
            "stage_map":     spec["stage_map"],
            "created_at":    now,
            "updated_at":    now,
            "created_by":    None,
            "updated_by":    None,
        })
        inserted += 1
    if inserted:
        logger.info(f"[presets] seeded {inserted} default preset stacks")
    return inserted
