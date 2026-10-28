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
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from db import db
from services.config_service import (
    get_pipeline_config,
    resolve_model,
    DEFAULT_MODELS,
)
from services import engine_config, head_views, house_style
from services.child_character_service import (
    _fetch_source_bytes,
    _generate_character,
    _save_generated_png,
)

logger = logging.getLogger("extra_characters_service")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                   provider: str, model_name: str, stage_cfg: dict, force: bool = False) -> dict:
    """Process a single character. Never raises. Returns a descriptor. A sheet
    already drawn for this plan from the same photo is reused unless `force`."""
    order_id = order["id"]
    source_url = character.get("image_url")
    extra_urls = [u for u in character.get("extra_image_urls") or [] if u][:2]
    if not source_url:
        return {"skipped": True, "reason": "no_image"}
    existing = await db.extra_character_assets.find_one({"order_id": order_id, "character_index": character_index},
                                                        {"_id": 0})
    if not force and existing and existing.get("status") == "completed" and existing.get("generated_image_url") \
            and existing.get("source_image_url") == source_url \
            and (existing.get("source_extra_urls") or []) == extra_urls \
            and existing.get("production_plan_id") == order.get("production_plan_id"):
        return {"skipped": False, "status": "completed", "reused": True, "asset": existing}

    await _upsert_asset(order_id, character_index, {
        "character_type":  character.get("type"),
        "character_name":  character.get("name") or "",
        "source_image_url": source_url,
        "status": "processing",
        "error_message": None,
    })

    # Same photo → cartoon sheet prompt as the child (house style + style reference),
    # with the outfit the story plan gives this relative ("same as in the photo" by default).
    outfit = None
    if order.get("production_plan_id"):
        keys = house_style.cast_keys((order.get("data") or {}).get("characters") or [])
        key = keys[character_index] if 0 <= character_index < len(keys) else character.get("type")
        profile = await db.character_profiles.find_one(
            {"production_plan_id": order["production_plan_id"], "type": key}, {"_id": 0, "clothing_style": 1})
        outfit = (profile or {}).get("clothing_style")
    who = (f"{character.get('name')}, the child's {character.get('type')}" if character.get("name")
           else f"the child's {character.get('type') or 'relative'}")
    art_style = await engine_config.style_for_order(order)
    prompt = house_style.character_sheet_prompt(who, outfit, art_style["style_text"], art_style["sheet_rules"],
                                                adult=house_style.is_adult(character.get("type")),
                                                photos=1 + len(extra_urls))
    prompt_src = "default"

    generated_url: str | None = None
    real_meta: dict[str, Any] = {}
    views: dict[str, Any] = {}
    error: str | None = None
    src_tuple = await _fetch_source_bytes(source_url, owner_id=order["user_id"])
    extra = [got[0] for got in [await _fetch_source_bytes(u, owner_id=order["user_id"]) for u in extra_urls] if got]
    if not src_tuple:
        error = "character photo could not be read from storage"
    else:
        try:
            result = await _generate_character(src_tuple[0], prompt, provider, model_name,
                                               await engine_config.style_reference_bytes(art_style), extra)
            generated_url = await _save_generated_png(order_id, order["user_id"], result["image_bytes"])
            real_meta = result.get("meta") or {}
            views = await head_views.for_asset(
                result["image_bytes"], lambda png: _save_generated_png(order_id, order["user_id"], png))
        except Exception as e:  # noqa: BLE001 — recorded on the asset; the book continues without this likeness
            error = f"{type(e).__name__}: {e}"
            logger.warning(f"[extra_character_i2i] failed order={order_id} char={character_index}: {error[:300]}")

    if generated_url:
        asset = await _upsert_asset(order_id, character_index, {
            "source_image_url":    source_url,
            "source_extra_urls":   extra_urls,
            "generated_image_url": generated_url,
            **views,
            "provider":            provider,
            "model_name":          model_name,
            "prompt_used":         prompt,
            "prompt_source":       "admin" if prompt_src == "admin" else "default",
            "status":              "completed",
            "fallback_used":       False,
            "mock":                False,
            "meta":                real_meta,
            "production_plan_id":  order.get("production_plan_id"),
        })
        logger.info(f"[extra_character_i2i] ok order={order_id} char={character_index}")
        return {"skipped": False, "status": "completed", "asset": asset}

    # No mock stand-in: scenes simply won't carry this character's likeness.
    asset = await _upsert_asset(order_id, character_index, {
        "status":        "failed",
        "fallback_used": False,
        "error_message": error,
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

    # Each character independently and at the same time (~1.5 min each at
    # high quality); one failure does not block the others.
    async def one(idx: int, c: dict) -> dict:
        try:
            r = await _run_one(order, idx, c, provider, model_name, stage_cfg)
        except Exception as e:  # noqa: BLE001
            logger.exception(f"[extra_character_i2i] unexpected error on idx={idx}: {e}")
            r = {"skipped": False, "status": "error", "reason": str(e)}
        return {"character_index": idx, **r}

    results = list(await asyncio.gather(*(one(idx, c) for idx, c in eligible)))
    return {"ran": True, "skipped": False, "count": len(results), "results": results}
