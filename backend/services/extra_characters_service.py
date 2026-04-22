"""Phase D — extra_character_i2i execution service.

Runs the SAME identity-preserving I2I transformation as child_character_i2i
but for every extra character in `order.data.characters` that has:
  * role == "visible"
  * image_url  uploaded

Generated assets are stored in `extra_character_assets` collection
(one doc per character_index per order).

Safety contract (MUST NOT CHANGE):
  1. Zero regression — if no visible extra character with image, early return.
  2. If stage disabled in pipeline_config → skip all.
  3. Per-character try/except — one character failing does NOT stop others.
  4. NEVER raises — orchestrator continues scene generation regardless.
  5. Reuses child_character_service helpers (same prompt family, same provider).
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from db import db
from services.config_service import (
    get_pipeline_config,
    resolve_model,
    resolve_prompt,
    DEFAULT_MODELS,
)
from services.child_character_service import (
    _fetch_source_bytes,
    _openai_generate,
    _save_generated_png,
    _mock_generate,
    DEFAULT_PROMPT as CHILD_DEFAULT_PROMPT,
)

logger = logging.getLogger("extra_characters_service")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_character_prompt(character: dict, fallback_prompt: str) -> str:
    """Adapt the base child_character_i2i prompt for an extra character.

    We keep the storybook art direction IDENTICAL so all characters in the
    same story share a unified style. Only the identity hints change.
    """
    char_type = (character.get("type") or "person").strip()
    char_name = (character.get("name") or "").strip()
    char_role = (character.get("role") or "visible").strip()
    id_hint_parts = [f"type: {char_type}"]
    if char_name:
        id_hint_parts.append(f"name: {char_name}")
    id_hint_parts.append(f"role in story: {char_role}")
    id_hint = ", ".join(id_hint_parts)
    # Prepend a short identity banner, then the shared storybook prompt.
    return (
        f"This is a supporting character for a children's storybook ({id_hint}). "
        "Apply the same storybook transformation rules used for the main child "
        "character so all characters share one consistent visual style.\n\n"
        + fallback_prompt
    )


async def _upsert_asset(order_id: str, character_index: int, patch: dict) -> dict:
    existing = await db.extra_character_assets.find_one(
        {"order_id": order_id, "character_index": character_index}, {"_id": 0}
    )
    if existing:
        patch["updated_at"] = _now()
        await db.extra_character_assets.update_one(
            {"order_id": order_id, "character_index": character_index},
            {"$set": patch},
        )
        return await db.extra_character_assets.find_one(
            {"order_id": order_id, "character_index": character_index}, {"_id": 0}
        )
    doc = {
        "id": str(uuid.uuid4()),
        "order_id": order_id,
        "character_index": character_index,
        "character_type": None,
        "character_name": None,
        "source_image_url": None,
        "generated_image_url": None,
        "provider": None,
        "model_name": None,
        "prompt_used": None,
        "prompt_source": None,
        "status": "queued",
        "fallback_used": False,
        "mock": False,
        "error_message": None,
        "created_at": _now(),
        "updated_at": _now(),
        **patch,
    }
    await db.extra_character_assets.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def list_assets(order_id: str) -> list[dict]:
    return await db.extra_character_assets.find(
        {"order_id": order_id}, {"_id": 0}
    ).sort("character_index", 1).to_list(20)


async def _run_one(order: dict, character_index: int, character: dict,
                   provider: str, model_name: str, stage_cfg: dict) -> dict:
    """Process a single character. Never raises. Returns a descriptor."""
    order_id = order["id"]
    source_url = character.get("image_url")
    if not source_url:
        return {"skipped": True, "reason": "no_image"}

    await _upsert_asset(order_id, character_index, {
        "character_type":  character.get("type"),
        "character_name":  character.get("name") or "",
        "source_image_url": source_url,
        "status": "processing",
        "error_message": None,
    })

    # Prompt — adapted from the child's DEFAULT_PROMPT (or admin override).
    admin_prompt, prompt_src, _reason = await resolve_prompt(
        "child_character_i2i",  # deliberately reuse the same admin template
        {"child_name": character.get("name", ""), "child_age": "", "child_gender": character.get("type", "")},
    )
    base = admin_prompt if (prompt_src == "admin" and admin_prompt) else CHILD_DEFAULT_PROMPT
    prompt = _build_character_prompt(character, base)

    use_real = provider == "openai"
    real_ok = False
    generated_url: str | None = None
    real_meta: dict[str, Any] = {}

    if use_real:
        src_tuple = await _fetch_source_bytes(source_url)
        if src_tuple:
            src_bytes, src_mime = src_tuple
            result = await _openai_generate(src_bytes, src_mime, prompt, model_name)
            if result and result.get("image_bytes"):
                try:
                    generated_url = await _save_generated_png(
                        order_id, order["user_id"], result["image_bytes"]
                    )
                    real_meta = result.get("meta") or {}
                    real_ok = True
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[extra_character_i2i] save failed: {type(e).__name__}: {e}")

    if real_ok and generated_url:
        asset = await _upsert_asset(order_id, character_index, {
            "source_image_url":    source_url,
            "generated_image_url": generated_url,
            "provider":            "openai",
            "model_name":          model_name,
            "prompt_used":         prompt,
            "prompt_source":       "admin" if prompt_src == "admin" else "default",
            "status":              "completed",
            "fallback_used":       False,
            "mock":                False,
            "meta":                real_meta,
        })
        logger.info(f"[extra_character_i2i] REAL ok order={order_id} char={character_index}")
        return {"skipped": False, "status": "completed", "asset": asset}

    # Real failed. Fallback if allowed; else silent text-only.
    if bool(stage_cfg.get("fallback_allowed", True)):
        mock_meta = await _mock_generate(source_url, prompt)
        asset = await _upsert_asset(order_id, character_index, {
            "source_image_url":    source_url,
            "generated_image_url": mock_meta["generated_image_url"],
            "provider":            mock_meta["provider"],
            "model_name":          mock_meta["model_name"],
            "prompt_used":         prompt,
            "prompt_source":       "admin" if prompt_src == "admin" else "default",
            "status":              "completed",
            "fallback_used":       use_real,
            "mock":                True,
        })
        logger.info(f"[extra_character_i2i] mock fallback order={order_id} char={character_index}")
        return {"skipped": False, "status": "completed", "asset": asset, "fallback_used": True}

    asset = await _upsert_asset(order_id, character_index, {
        "status":        "failed",
        "fallback_used": False,
        "error_message": "real provider failed and fallback disabled",
    })
    return {"skipped": False, "status": "failed", "asset": asset}


async def safe_run(order: dict) -> dict:
    """Run extra_character_i2i for all eligible characters. Never raises."""
    order_id = order["id"]
    chars = ((order.get("data") or {}).get("characters") or [])
    # Fast-exit: nothing to do → preserves legacy behavior (zero cost).
    eligible = [(i, c) for i, c in enumerate(chars)
                if c.get("role") == "visible" and c.get("image_url")]
    if not eligible:
        return {"ran": False, "skipped": True, "reason": "no_visible_characters_with_image"}

    try:
        cfg = await get_pipeline_config()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[extra_character_i2i] cfg read failed: {e}")
        return {"ran": False, "skipped": True, "reason": "pipeline_config_error"}
    stage_cfg = ((cfg or {}).get("stages") or {}).get("extra_character_i2i") or {}
    if not stage_cfg.get("enabled"):
        logger.info(f"[extra_character_i2i] disabled — skipping for order={order_id}")
        return {"ran": False, "skipped": True, "reason": "stage_disabled"}

    # Resolve provider/model (admin override allowed; defaults to same as child).
    try:
        defaults = DEFAULT_MODELS.get("child_character_i2i", {})
        provider, model_name, src = await resolve_model(
            "extra_character_i2i",
            defaults.get("provider", "openai"),
            defaults.get("model_name", "gpt-image-1"),
        )
    except Exception:  # noqa: BLE001
        provider, model_name, src = "openai", "gpt-image-1", "fallback"
    logger.info(f"[config] stage=extra_character_i2i model_source={src} model={provider}/{model_name}")

    # Process each character independently. One failure does not block others.
    results = []
    for idx, c in eligible:
        try:
            r = await _run_one(order, idx, c, provider, model_name, stage_cfg)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[extra_character_i2i] unexpected error on idx={idx}: {e}")
            r = {"skipped": False, "status": "error", "reason": str(e)}
        results.append({"character_index": idx, **r})
    return {"ran": True, "skipped": False, "count": len(results), "results": results}
