"""Phase C — child_character_i2i execution service.

Generates a reusable cartoon character reference from the uploaded child photo.
Real provider: OpenAI gpt-image-1 (image edits endpoint — identity-preserving I2I).
Falls back to MOCK/dry-run if OPENAI_API_KEY missing, provider not configured,
or any exception is raised inside the real provider call.

Safety rules (MUST NOT CHANGE):
  1. If `pipeline_config.stages.child_character_i2i.enabled` is False → skip.
  2. If the order has no child photo (`order.data.child.image_url` missing) → skip.
  3. If anything inside this service raises → the exception is swallowed,
     `scene_image_generation` continues unaffected. No regression possible.
  4. Prompt text comes from `resolve_prompt(...)` with a hardcoded default.
     No eval/f-strings on DB input.
  5. OPENAI_API_KEY is read from env only — never logged, never returned.
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
from storage import put_object, APP_NAME

logger = logging.getLogger("child_character_service")

# Default fallback prompt (used when no active admin template exists OR the
# template has missing/broken variables).
DEFAULT_PROMPT = (
    "Create a highly stylized 2D children's storybook character based on my uploaded "
    "child photo, making it more cartoonish than the reference image while preserving "
    "the child's exact recognizable identity. Keep the same unique facial features "
    "clearly visible: face shape, hairstyle, hair volume and flow, eyebrow shape, eye "
    "shape, nose, smile, cheeks, skin tone, and overall sweet expression. Use a premium "
    "children's book animation style with clean elegant linework, soft simplified "
    "painterly shading, warm appealing colors, charming proportions, and a cute "
    "expressive design that feels hand-crafted, emotional, and ready for an animated "
    "story world.\n\n"
    "Generate ONE single full-body standing version of the child only, centered in the "
    "frame, with transparent background. The child should be standing in a natural "
    "relaxed pose, front-facing or slight 3/4 view, with the full body clearly visible "
    "from head to toe, feet fully shown, arms and hands clearly separated from the "
    "body, legs clearly readable, clean silhouette, no overlapping limbs, no cropped "
    "parts, no props, no background, no scenery, no extra characters, no duplicate "
    "pose, no text.\n\n"
    "The result must feel like a professional animated children's story character "
    "design made for motion use, with strong identity preservation and animation-"
    "friendly structure for later rigging and video movement. Clean PNG look, "
    "transparent background, consistent character design, studio-quality 2D cartoon, "
    "expressive but simple enough for animation, adorable, polished, cinematic "
    "children's book feel."
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
    return DEFAULT_PROMPT, "default"


async def _fetch_source_bytes(source_image_url: str) -> tuple[bytes, str] | None:
    """Fetch the child photo bytes from internal storage (bypasses HTTP/auth)."""
    try:
        fid = source_image_url.rstrip("/").rsplit("/", 1)[-1]
        rec = await db.files.find_one({"id": fid, "is_deleted": False}, {"_id": 0})
        if not rec:
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


async def _openai_generate(
    source_bytes: bytes, source_mime: str, prompt: str, model_name: str,
) -> dict[str, Any] | None:
    """OpenAI gpt-image-1 images.edit — identity-preserving I2I.

    Returns {image_bytes, mime_type, meta} on success, or None on any failure.
    NEVER raises. Never logs the API key.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[child_character_i2i] OPENAI_API_KEY not set — skipping real call")
        return None
    try:
        from openai import AsyncOpenAI
        # gpt-image-1 edits require PNG input. Convert if needed.
        input_bytes = source_bytes
        if source_mime != "image/png":
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(source_bytes)).convert("RGBA")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                input_bytes = buf.getvalue()
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[child_character_i2i] PIL convert failed: {e}")
        file_arg = ("child.png", input_bytes, "image/png")
        client = AsyncOpenAI(api_key=api_key, timeout=90.0)
        resp = await client.images.edit(
            model=model_name,
            image=file_arg,
            prompt=prompt,
            size="1024x1024",
            background="transparent",
            n=1,
        )
        if not resp or not resp.data:
            return None
        b64 = getattr(resp.data[0], "b64_json", None)
        if b64:
            import base64
            img_bytes = base64.b64decode(b64)
            return {"image_bytes": img_bytes, "mime_type": "image/png",
                    "meta": {"response_kind": "b64_json", "openai_model": model_name,
                             "size": "1024x1024"}}
        url = getattr(resp.data[0], "url", None)
        if not url:
            return None
        import httpx
        async with httpx.AsyncClient(timeout=60.0) as hc:
            r = await hc.get(url)
            if r.status_code != 200:
                return None
            return {"image_bytes": r.content, "mime_type": "image/png",
                    "meta": {"response_kind": "url", "openai_model": model_name}}
    except Exception as e:  # noqa: BLE001 — never leak
        logger.warning(f"[child_character_i2i] OpenAI call failed: {type(e).__name__}: {str(e)[:300]}")
        return None


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


async def _mock_generate(source_image_url: str, prompt: str) -> dict[str, Any]:
    """Fallback mock/dry-run — mirrors source URL. Predictable, non-breaking."""
    return {
        "provider": "mock",
        "model_name": "dry-run",
        "generated_image_url": source_image_url,
        "prompt_used": prompt,
        "mock": True,
    }


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


async def run_child_character_generation(order: dict, plan: dict | None) -> dict:
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

    source_image_url = ((order.get("data") or {}).get("child") or {}).get("image_url")
    if not source_image_url:
        logger.info(f"[child_character_i2i] no child image_url — skipping for order={order_id}")
        return {"ran": False, "skipped": True, "status": "skipped", "reason": "no_source_image"}

    await _upsert_asset(order_id, {
        "source_image_url": source_image_url,
        "status": "processing",
        "error_message": None,
    })

    prompt, prompt_source = await _resolve_prompt_safely(order, plan)

    try:
        defaults = DEFAULT_MODELS.get("child_character_i2i", {})
        provider, model_name, src = await resolve_model(
            "child_character_i2i",
            defaults.get("provider", "openai"),
            defaults.get("model_name", "gpt-image-1"),
        )
    except Exception:  # noqa: BLE001
        provider, model_name, src = "openai", "gpt-image-1", "fallback"
    logger.info(f"[config] stage=child_character_i2i model_source={src} model={provider}/{model_name}")

    real_ok = False
    real_meta: dict[str, Any] = {}
    generated_url: str | None = None
    use_real = provider == "openai" and bool(os.environ.get("OPENAI_API_KEY"))
    if use_real:
        src_tuple = await _fetch_source_bytes(source_image_url)
        if not src_tuple:
            logger.warning("[child_character_i2i] could not fetch source bytes; falling back to mock")
        else:
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
                    logger.warning(f"[child_character_i2i] save failed: {type(e).__name__}: {e}")

    try:
        if real_ok and generated_url:
            asset = await _upsert_asset(order_id, {
                "source_image_url":    source_image_url,
                "generated_image_url": generated_url,
                "provider":            "openai",
                "model_name":          model_name,
                "prompt_used":         prompt,
                "prompt_source":       prompt_source,
                "status":              "completed",
                "fallback_used":       False,
                "mock":                False,
                "error_message":       None,
                "meta":                real_meta,
            })
            logger.info(f"[child_character_i2i] REAL (openai) completed for order={order_id}")
            return {"ran": True, "skipped": False, "status": "completed", "asset": asset}

        fallback_allowed = bool(stage_cfg.get("fallback_allowed", False))
        if fallback_allowed:
            meta = await _mock_generate(source_image_url, prompt)
            asset = await _upsert_asset(order_id, {
                "source_image_url":    source_image_url,
                "generated_image_url": meta["generated_image_url"],
                "provider":            meta["provider"],
                "model_name":          meta["model_name"],
                "prompt_used":         prompt,
                "prompt_source":       prompt_source,
                "status":              "completed",
                "fallback_used":       use_real,  # true iff real attempted and failed
                "mock":                True,
                "error_message":       None,
            })
            logger.info(
                f"[child_character_i2i] MOCK fallback used for order={order_id} "
                f"(real_attempted={use_real})"
            )
            return {"ran": True, "skipped": False, "status": "completed",
                    "asset": asset, "fallback_used": True}

        asset = await _upsert_asset(order_id, {
            "status":        "failed",
            "fallback_used": False,
            "error_message": "real provider failed and fallback disabled",
        })
        return {"ran": True, "skipped": False, "status": "failed",
                "reason": "real_provider_failed_no_fallback", "asset": asset}
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
        logger.warning(f"[child_character_i2i] persist failed order={order_id} err={err}")
        asset = await _upsert_asset(order_id, {
            "status":        "failed",
            "error_message": err,
        })
        return {"ran": True, "skipped": False, "status": "failed",
                "reason": err, "asset": asset}


async def safe_run(order: dict, plan: dict | None) -> dict:
    try:
        return await run_child_character_generation(order, plan)
    except Exception as e:  # noqa: BLE001
        logger.exception(f"[child_character_i2i] unexpected crash: {e}")
        return {"ran": True, "skipped": False, "status": "error", "reason": str(e)}
