"""Phase C — child_character_i2i execution service.

Generates a reusable cartoon character reference from the uploaded child photo
(services.ai.image_client, reference-guided edit). Every scene then uses this
character as its visual reference, so it is what makes the child the hero.

Rules:
  1. If `pipeline_config.stages.child_character_i2i.enabled` is False → skip.
  2. If the order has no child photo (`order.data.child.image_url` missing) → skip.
  3. A provider failure is recorded on the asset (status "failed" + reason) and
     returned — never replaced by a mock. The orchestrator stops the order so
     no book is produced without the child's likeness.
  4. Prompt text comes from `resolve_prompt(...)` with a hardcoded default.
     No eval/f-strings on DB input.
  5. API keys are resolved by the adapter at call time — never logged or returned.
"""
import asyncio
import io
import logging
import os
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
from services import engine_config, head_views, house_style
from services.ai.image_client import generate_image as generate_provider_image
from storage import put_object, APP_NAME

logger = logging.getLogger("child_character_service")

# Default fallback prompt (used when no active admin template exists OR the
# template has missing/broken variables).
DEFAULT_PROMPT = house_style.character_sheet_prompt("the person in the photo")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_context(order: dict, plan: dict | None, outfit: str = "",
                   art_style: dict | None = None) -> dict[str, Any]:
    """Flat, string-safe context for $-Template substitution."""
    data = order.get("data", {}) or {}
    child = data.get("child", {}) or {}
    style = (plan or {}).get("style_guide") or {}
    art_style = art_style or engine_config.DEFAULT_STYLE
    gender = child.get("gender")
    gender_ar = "ولد" if gender == "male" else ("بنت" if gender == "female" else "طفل")
    return {
        "child_name":    child.get("name", "") or "",
        "child_age":     child.get("age", "") or "",
        "child_gender":  gender_ar,
        "art_direction": style.get("art_direction", "") or "warm children's storybook",
        "palette":       style.get("palette", "") or "soft pastels",
        "lighting":      style.get("lighting", "") or "soft natural light",
        # The photo's outfit unless the story needs specific clothes (pajamas...).
        "child_outfit":  outfit or "same as in the photo",
        "outfit_rule":   house_style.outfit_rule(outfit),
        # The parent's art style preset (admin-editable).
        "style_text":    art_style.get("style_text") or engine_config.DEFAULT_STYLE["style_text"],
        "sheet_rules":   art_style.get("sheet_rules") or house_style.SHEET_RULES,
    }


async def _resolve_prompt_safely(order: dict, plan: dict | None,
                                 art_style: dict | None = None) -> tuple[str, str]:
    """Return (rendered_prompt, source). `source` is 'admin' or 'default'."""
    art_style = art_style or engine_config.DEFAULT_STYLE
    outfit = ""
    if plan:
        profile = await db.character_profiles.find_one(
            {"production_plan_id": plan.get("id"), "type": "child"}, {"_id": 0, "clothing_style": 1})
        outfit = (profile or {}).get("clothing_style") or ""
    fallback = house_style.character_sheet_prompt(
        "the person in the photo", outfit, art_style.get("style_text"), art_style.get("sheet_rules"))
    try:
        ctx = _build_context(order, plan, outfit, art_style)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[child_character_i2i] context_error {type(e).__name__}: {e}")
        return fallback, "default"
    admin_prompt, source, reason = await resolve_prompt("child_character_i2i", ctx)
    if source == "admin" and admin_prompt:
        logger.info(f"[config] stage=child_character_i2i prompt_source=admin {reason}")
        return admin_prompt, "admin"
    logger.info(f"[config] stage=child_character_i2i prompt_source=default reason={reason}")
    return fallback, "default"


async def _fetch_source_bytes(source_image_url: str, owner_id: str | None = None) -> tuple[bytes, str] | None:
    """Fetch file bytes from internal storage (bypasses HTTP/auth). With
    `owner_id`, only a file that user uploaded is read (a parent's photo)."""
    try:
        fid = source_image_url.rstrip("/").rsplit("/", 1)[-1].split("?", 1)[0]
        rec = await db.files.find_one({"id": fid, "is_deleted": False}, {"_id": 0})
        if not rec:
            return None
        if owner_id and rec.get("user_id") != owner_id:
            logger.warning(f"[files] {fid} is not owned by {owner_id}; refusing to use it")
            return None
        from storage import get_object
        loop = asyncio.get_running_loop()
        payload = await loop.run_in_executor(None, lambda: get_object(rec["storage_path"]))
        if not payload:
            return None
        # get_object returns (bytes, content_type)
        data, ctype = payload if isinstance(payload, tuple) else (payload, None)
        if not data:
            return None
        mime = ctype or rec.get("content_type") or "image/png"
        return data, mime
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[child_character_i2i] source fetch failed: {type(e).__name__}: {e}")
        return None


async def _generate_character(source_bytes: bytes, prompt: str, provider: str, model_name: str,
                              style_ref: bytes | None = None, quality: str = "high") -> dict[str, Any]:
    """Identity-preserving photo → cartoon character via the image adapter. Raises AIError."""
    image_bytes, mime, meta = await generate_provider_image(
        stage="child_character_i2i",
        provider=provider,
        model=model_name,
        prompt=prompt,
        # The style preset's neutral reference image rides along so every character lands in that style.
        references=[source_bytes] + ([style_ref] if style_ref else []),
        size=house_style.SHEET_SIZE,
        quality=quality,
    )
    return {"image_bytes": image_bytes, "mime_type": mime, "meta": meta}


async def _save_generated_png(order_id: str, user_id: str, png_bytes: bytes) -> str:
    """Persist generated PNG to object storage + files collection; return served URL."""
    file_id = str(uuid.uuid4())
    storage_path = f"{APP_NAME}/orders/{order_id}/generated/child_character/{file_id}.png"
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, lambda: put_object(storage_path, png_bytes, "image/png")
    )
    await db.files.insert_one({
        "id": file_id,
        "user_id": user_id,
        "scope": "generated-child-character",
        "storage_path": result.get("path", storage_path),
        "original_filename": "child_character.png",
        "content_type": "image/png",
        "size": result.get("size", len(png_bytes)),
        "is_deleted": False,
        "created_at": _now(),
    })
    return f"/api/uploads/file/{file_id}"


async def _upsert_asset(order_id: str, patch: dict) -> dict:
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
        "mock": False,
        "error_message": None,
        "created_at": _now(),
        "updated_at": _now(),
        **patch,
    }
    await db.child_character_assets.insert_one(doc)
    return {k: v for k, v in doc.items() if k != "_id"}


async def get_asset(order_id: str) -> dict | None:
    return await db.child_character_assets.find_one({"order_id": order_id}, {"_id": 0})


async def run_child_character_generation(order: dict, plan: dict | None, force: bool = False) -> dict:
    """Draw the child's character sheet. A sheet already drawn for this plan
    from the same photo is reused (a resumed pipeline must not redraw the cast
    under keyframes that already exist); `force` redraws (admin button)."""
    order_id = order["id"]
    try:
        cfg = await get_pipeline_config()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[child_character_i2i] pipeline config read failed: {e}")
        return {"ran": False, "skipped": True, "status": "skipped", "reason": "pipeline_config_error"}
    stage_cfg = ((cfg or {}).get("stages") or {}).get("child_character_i2i") or {}
    if not stage_cfg.get("enabled"):
        logger.info(f"[child_character_i2i] disabled — skipping for order={order_id}")
        return {"ran": False, "skipped": True, "status": "skipped", "reason": "stage_disabled"}

    child = (order.get("data") or {}).get("child") or {}
    source_image_url = child.get("image_url")
    extra_urls = [u for u in child.get("extra_image_urls") or [] if u][:2]
    if not source_image_url:
        logger.info(f"[child_character_i2i] no child image_url — skipping for order={order_id}")
        return {"ran": False, "skipped": True, "status": "skipped", "reason": "no_source_image"}

    existing = await get_asset(order_id)
    if not force and existing and existing.get("status") == "completed" and existing.get("generated_image_url") \
            and existing.get("source_image_url") == source_image_url \
            and (existing.get("source_extra_urls") or []) == extra_urls \
            and existing.get("production_plan_id") == (plan or {}).get("id"):
        logger.info(f"[child_character_i2i] reusing the sheet drawn for this plan (order={order_id})")
        return {"ran": True, "skipped": False, "status": "completed", "reused": True, "asset": existing}

    await _upsert_asset(order_id, {
        "source_image_url": source_image_url,
        "status": "processing",
        "error_message": None,
    })

    art_style = await engine_config.style_for_order(order)
    prompt, prompt_source = await _resolve_prompt_safely(order, plan, art_style)

    try:
        defaults = DEFAULT_MODELS.get("child_character_i2i", {})
        provider, model_name, src = await resolve_model(
            "child_character_i2i",
            defaults.get("provider", "openai"),
            defaults.get("model_name", "gpt-image-2"),
        )
    except Exception:  # noqa: BLE001
        provider, model_name, src = "openai", "gpt-image-2", "fallback"
    logger.info(f"[config] stage=child_character_i2i model_source={src} model={provider}/{model_name}")

    generated_url: str | None = None
    real_meta: dict[str, Any] = {}
    views: dict[str, Any] = {}
    error: str | None = None
    src_tuple = await _fetch_source_bytes(source_image_url, owner_id=order["user_id"])
    if not src_tuple:
        error = "child photo could not be read from storage"
    else:
        try:
            style_ref = await engine_config.style_reference_bytes(art_style)
            result = await _generate_character(src_tuple[0], prompt, provider, model_name, style_ref)
            generated_url = await _save_generated_png(order_id, order["user_id"], result["image_bytes"])
            real_meta = result.get("meta") or {}
            views = dict(head_views.NONE)  # the heads are for grown-ups only (services/head_views.py)
        except Exception as e:  # noqa: BLE001 — recorded on the asset and surfaced to the orchestrator
            error = f"{type(e).__name__}: {e}"
            logger.warning(f"[child_character_i2i] generation failed order={order_id}: {error[:300]}")

    try:
        if generated_url:
            asset = await _upsert_asset(order_id, {
                "source_image_url":    source_image_url,
                "source_extra_urls":   extra_urls,
                "generated_image_url": generated_url,
                **views,
                "provider":            provider,
                "model_name":          model_name,
                "prompt_used":         prompt,
                "prompt_source":       prompt_source,
                "status":              "completed",
                "fallback_used":       False,
                "mock":                False,
                "error_message":       None,
                "meta":                real_meta,
                "production_plan_id":  (plan or {}).get("id"),
            })
            logger.info(f"[child_character_i2i] completed ({provider}/{model_name}) for order={order_id}")
            return {"ran": True, "skipped": False, "status": "completed", "asset": asset}

        asset = await _upsert_asset(order_id, {
            "status":        "failed",
            "fallback_used": False,
            "error_message": error,
        })
        return {"ran": True, "skipped": False, "status": "failed", "reason": error, "asset": asset}
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        logger.warning(f"[child_character_i2i] persist failed order={order_id} err={err}")
        asset = await _upsert_asset(order_id, {
            "status":        "failed",
            "error_message": err,
        })
        return {"ran": True, "skipped": False, "status": "failed",
                "reason": err, "asset": asset}


async def safe_run(order: dict, plan: dict | None, force: bool = False) -> dict:
    try:
        return await run_child_character_generation(order, plan, force)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[child_character_i2i] unexpected crash: {e}")
        return {"ran": True, "skipped": False, "status": "error", "reason": str(e)}
