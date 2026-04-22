"""Vision description helper — extracts a rich text description from an image.

Used to turn uploaded toy/object/character images into prompt-injectable
text so downstream text-only image models (Nano Banana) can render them
correctly. One-shot, cached on the order document.

Safe by design:
  * Never raises — returns None on any failure.
  * Never logs the API key.
  * Reads OPENAI_API_KEY from env only.
"""
import asyncio
import base64
import logging
import os

from db import db

logger = logging.getLogger("vision_describe")

VISION_MODEL = "gpt-4o-mini"  # cheapest vision-capable; quality is sufficient


async def _fetch_bytes_from_internal_url(url: str) -> bytes | None:
    """Resolve /api/uploads/file/{id} to bytes via the internal storage."""
    try:
        fid = url.rstrip("/").rsplit("/", 1)[-1]
        rec = await db.files.find_one({"id": fid, "is_deleted": False}, {"_id": 0})
        if not rec:
            return None
        from storage import get_object
        loop = asyncio.get_running_loop()
        payload = await loop.run_in_executor(None, lambda: get_object(rec["storage_path"]))
        data, _ctype = payload if isinstance(payload, tuple) else (payload, None)
        return data
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[vision_describe] fetch bytes failed: {type(e).__name__}: {e}")
        return None


async def describe_image(image_url: str, hint: str = "") -> str | None:
    """Generate a concise visual description (English, prompt-ready).

    Returns None if the key is missing, the image cannot be fetched, or the
    OpenAI call fails. Never raises.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not image_url:
        return None
    img_bytes = await _fetch_bytes_from_internal_url(image_url)
    if not img_bytes:
        return None
    try:
        from openai import AsyncOpenAI
        b64 = base64.b64encode(img_bytes).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        client = AsyncOpenAI(api_key=api_key, timeout=40.0)
        prompt = (
            "Describe this image in 2-3 concise English sentences, optimized for use "
            "as a reference inside a children's storybook illustration prompt. Focus "
            "only on objectively visible features: colors, shapes, materials, "
            "distinctive marks, approximate proportions, clothing/accessories. "
            "Do NOT invent details that aren't visible. Do NOT include artistic "
            "style commentary. Output ENGLISH only."
        )
        if hint:
            prompt += f" Context hint: {hint}."
        resp = await client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            max_completion_tokens=250,
        )
        out = (resp.choices[0].message.content or "").strip() if resp and resp.choices else ""
        if not out:
            return None
        logger.info(f"[vision_describe] ok ({len(out)} chars, hint={hint!r})")
        return out[:1000]
    except Exception as e:  # noqa: BLE001 — never leak
        logger.warning(f"[vision_describe] failed: {type(e).__name__}: {str(e)[:200]}")
        return None


async def ensure_vision_descriptions(order: dict) -> dict:
    """Populate auto-descriptions for all uploaded images that lack them.

    Idempotent — skips any item that already has a non-empty description.
    Persists updates to the `orders` document and returns the refreshed
    in-memory copy. On any failure, the order is returned unchanged.

    Fields written:
      * data.personalization.toy_description_auto  (string | missing)
      * data.characters[i].visual_description_auto (per-visible-character)
    """
    if not order or not isinstance(order, dict):
        return order
    data = order.get("data") or {}
    pers = data.get("personalization") or {}
    chars = data.get("characters") or []
    updates: dict[str, str] = {}

    # Toy / object image
    toy_url = (pers or {}).get("toy_image_url")
    toy_desc_existing = (pers or {}).get("toy_description_auto")
    if toy_url and not toy_desc_existing:
        toy_name = ((pers.get("favorites") or {}).get("toy") or {}).get("name") or ""
        hint = f"A favorite toy/object for a child. Name: {toy_name}" if toy_name else "A favorite toy/object for a child"
        desc = await describe_image(toy_url, hint=hint)
        if desc:
            updates["data.personalization.toy_description_auto"] = desc

    # Visible extra characters
    for i, c in enumerate(chars):
        if c.get("role") != "visible":
            continue
        cur_url = c.get("image_url")
        cur_desc = c.get("visual_description_auto")
        if cur_url and not cur_desc:
            char_type = c.get("type") or ""
            char_name = c.get("name") or ""
            hint = f"A {char_type} named {char_name}" if char_name else f"A {char_type}"
            desc = await describe_image(cur_url, hint=hint)
            if desc:
                updates[f"data.characters.{i}.visual_description_auto"] = desc

    if not updates:
        return order
    try:
        await db.orders.update_one({"id": order["id"]}, {"$set": updates})
        # Merge into the in-memory copy for the current call chain.
        for k, v in updates.items():
            # simple dotted-path set
            parts = k.split(".")
            ref = order
            for p in parts[:-1]:
                if p.isdigit():
                    ref = ref[int(p)]
                else:
                    ref = ref.setdefault(p, {})
            ref[parts[-1]] = v
        logger.info(f"[vision_describe] persisted {len(updates)} description(s) for order={order['id']}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[vision_describe] persist failed: {type(e).__name__}: {e}")
    return order
