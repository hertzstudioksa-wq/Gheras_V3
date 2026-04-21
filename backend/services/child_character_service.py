"""Phase C — child_character_i2i execution service (MOCK-only for now).

This service is responsible for generating a reusable "cartoon character"
reference asset from the uploaded real child photo. The generated asset is
persisted in the `child_character_assets` collection so downstream stages
(e.g. scene_image_generation in Phase D) can optionally use it to lock
face consistency across scenes.

Current status: **mock / dry-run only**.
  * No external provider is called.
  * `generated_image_url` is set to the source image URL itself so downstream
    pipelines and admin UI have a predictable, non-breaking result.
  * Real providers (Gemini Nano Banana I2I, etc.) will be wired in the next
    phase through `services.config_service.resolve_model(...)`.

Safety rules (MUST NOT CHANGE):
  1. If `pipeline_config.stages.child_character_i2i.enabled` is False → skip.
  2. If the order has no child photo (`order.data.child.image_url` missing) → skip.
  3. If anything inside this service raises → the exception is swallowed,
     `scene_image_generation` continues unaffected. No regression possible.
  4. Prompt text for the stage comes from `resolve_prompt(...)` with a
     hardcoded Arabic-English default fallback. No eval/f-string on DB input.
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from db import db
from services.config_service import (
    resolve_model,
    resolve_prompt,
    get_pipeline_config,
    DEFAULT_MODELS,
)

logger = logging.getLogger("child_character_service")

# Hardcoded default prompt. Admin can override via /admin/prompt-templates
# (stage_key="child_character_i2i"). Uses $-Template style (string.Template).
DEFAULT_PROMPT = (
    "Transform the provided real photo of a child into a consistent, friendly "
    "cartoon character suitable for a children's storybook. "
    "Preserve the child's distinctive traits (skin tone, hair color, hair style, "
    "eye color) but render in a warm, soft, storybook illustration style. "
    "Child name (for internal reference only): $child_name. "
    "Approximate age: $child_age. Gender: $child_gender. "
    "Full body, neutral pose, plain background, friendly smile. "
    "Art direction: $art_direction. Palette: $palette."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_context(order: dict, plan: dict | None) -> dict[str, Any]:
    """Flat, string-safe context for $-Template substitution."""
    data = order.get("data", {}) or {}
    child = data.get("child", {}) or {}
    style = (plan or {}).get("style_guide") or {}
    gender = child.get("gender")
    gender_ar = "ولد" if gender == "male" else ("بنت" if gender == "female" else "طفل")
    return {
        "child_name":    child.get("name", "") or "",
        "child_age":     child.get("age", "") or "",
        "child_gender":  gender_ar,
        "art_direction": style.get("art_direction", "") or "warm children's storybook",
        "palette":       style.get("palette", "") or "soft pastels",
        "lighting":      style.get("lighting", "") or "soft natural light",
    }


async def _resolve_prompt_safely(order: dict, plan: dict | None) -> tuple[str, str]:
    """Return (rendered_prompt, source). `source` is 'admin' or 'default'."""
    try:
        ctx = _build_context(order, plan)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[child_character_i2i] context_error {type(e).__name__}: {e}")
        return DEFAULT_PROMPT, "default"
    admin_prompt, source, reason = await resolve_prompt("child_character_i2i", ctx)
    if source == "admin" and admin_prompt:
        logger.info(f"[config] stage=child_character_i2i prompt_source=admin {reason}")
        return admin_prompt, "admin"
    logger.info(f"[config] stage=child_character_i2i prompt_source=default reason={reason}")
    # Manually render the hardcoded default with the same safe substitution.
    from string import Template
    try:
        return Template(DEFAULT_PROMPT).safe_substitute({k: str(v) for k, v in ctx.items()}), "default"
    except Exception:  # noqa: BLE001
        return DEFAULT_PROMPT, "default"


async def _mock_generate(source_image_url: str, prompt: str) -> dict[str, Any]:
    """Mock / dry-run I2I provider.

    Returns a predictable metadata dict. `generated_image_url` mirrors the
    source so downstream consumers never break. Real providers plug in here.
    """
    return {
        "provider": "mock",
        "model_name": "dry-run",
        "generated_image_url": source_image_url,  # mirror source for now
        "prompt_used": prompt,
        "mock": True,
    }


async def _upsert_asset(order_id: str, patch: dict) -> dict:
    """Upsert the child_character_assets record for this order (one per order)."""
    existing = await db.child_character_assets.find_one({"order_id": order_id}, {"_id": 0})
    if existing:
        patch["updated_at"] = _now()
        await db.child_character_assets.update_one({"order_id": order_id}, {"$set": patch})
        return await db.child_character_assets.find_one({"order_id": order_id}, {"_id": 0})
    doc = {
        "id": str(uuid.uuid4()),
        "order_id": order_id,
        "child_id": None,
        "source_image_url": None,
        "generated_image_url": None,
        "provider": None,
        "model_name": None,
        "prompt_used": None,
        "status": "queued",
        "fallback_used": False,
        "error_message": None,
        "created_at": _now(),
        "updated_at": _now(),
        **patch,
    }
    await db.child_character_assets.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def get_asset(order_id: str) -> dict | None:
    return await db.child_character_assets.find_one({"order_id": order_id}, {"_id": 0})


async def run_child_character_generation(order: dict, plan: dict | None) -> dict:
    """Execute the I2I stage for a given order.

    Returns a descriptor dict: {ran, skipped, status, reason, asset}
      * ran=False, skipped=True  → stage was disabled or prerequisites missing
      * ran=True,  status="completed" | "failed"
    Never raises. Caller can ignore the return and proceed downstream safely.
    """
    order_id = order["id"]
    # 1) Check the pipeline config flag (disabled by default).
    try:
        cfg = await get_pipeline_config()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[child_character_i2i] pipeline config read failed: {e}")
        return {"ran": False, "skipped": True, "status": "skipped", "reason": "pipeline_config_error"}
    stage_cfg = ((cfg or {}).get("stages") or {}).get("child_character_i2i") or {}
    if not stage_cfg.get("enabled"):
        logger.info(f"[child_character_i2i] disabled — skipping for order={order_id}")
        return {"ran": False, "skipped": True, "status": "skipped", "reason": "stage_disabled"}

    # 2) Need a source photo.
    source_image_url = ((order.get("data") or {}).get("child") or {}).get("image_url")
    if not source_image_url:
        logger.info(f"[child_character_i2i] no child image_url — skipping for order={order_id}")
        return {"ran": False, "skipped": True, "status": "skipped", "reason": "no_source_image"}

    # 3) Mark processing.
    await _upsert_asset(order_id, {
        "source_image_url": source_image_url,
        "status": "processing",
        "error_message": None,
    })

    prompt, prompt_source = await _resolve_prompt_safely(order, plan)

    # 4) Resolve provider (even though MOCK-only now, log which would be used).
    try:
        defaults = DEFAULT_MODELS.get("child_character_i2i", {})
        provider, model_name, src = await resolve_model(
            "child_character_i2i",
            defaults.get("provider", "gemini"),
            defaults.get("model_name", "gemini-2.5-flash-image-preview"),
        )
    except Exception:  # noqa: BLE001
        provider, model_name, src = "gemini", "gemini-2.5-flash-image-preview", "fallback"
    logger.info(f"[config] stage=child_character_i2i model_source={src} model={provider}/{model_name}")

    # 5) MOCK execution. Real provider will replace this block.
    try:
        meta = await _mock_generate(source_image_url, prompt)
        asset = await _upsert_asset(order_id, {
            "source_image_url":    source_image_url,
            "generated_image_url": meta["generated_image_url"],
            "provider":            meta["provider"],
            "model_name":          meta["model_name"],
            "prompt_used":         meta["prompt_used"],
            "prompt_source":       prompt_source,
            "status":              "completed",
            "fallback_used":       False,
            "error_message":       None,
            "mock":                True,
        })
        logger.info(f"[child_character_i2i] MOCK completed for order={order_id}")
        return {"ran": True, "skipped": False, "status": "completed", "asset": asset}
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        logger.warning(f"[child_character_i2i] execution failed order={order_id} err={err}")
        fallback_allowed = bool(stage_cfg.get("fallback_allowed", False))
        asset = await _upsert_asset(order_id, {
            "status":        "failed",
            "error_message": err,
            "fallback_used": fallback_allowed,
        })
        return {
            "ran": True, "skipped": False, "status": "failed",
            "reason": err, "asset": asset, "fallback_allowed": fallback_allowed,
        }


async def safe_run(order: dict, plan: dict | None) -> dict:
    """Wrapper that guarantees the caller (orchestrator) never crashes.

    Any exception inside run_child_character_generation is logged and
    converted into a `{status: error}` descriptor. Downstream pipeline
    MUST continue regardless of what's returned here.
    """
    try:
        return await run_child_character_generation(order, plan)
    except Exception as e:  # noqa: BLE001 — defensive, must never leak
        logger.exception(f"[child_character_i2i] unexpected crash: {e}")
        return {"ran": True, "skipped": False, "status": "error", "reason": str(e)}
