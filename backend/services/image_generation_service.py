"""Image generation service — Nano Banana (Gemini 3.1 Flash Image Preview).

Contract:
  generate_image(prompt, session_id) -> (image_bytes, mime_type, provider_meta)
  Falls back to a placeholder generator on any failure (returns 1x1 png, provider='fallback').
"""
import os
import base64
import logging
import uuid
from typing import Tuple

from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger("image_generation_service")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
IMAGE_MODEL_PROVIDER = "gemini"
IMAGE_MODEL_NAME = "gemini-3.1-flash-image-preview"

# Minimal 1x1 transparent PNG (safe, tiny, never breaks the UI)
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def _build_image_prompt(scene_prompt: str, style_guide: dict, character_note: str) -> str:
    """Compose a rich, style-consistent English prompt."""
    style = style_guide or {}
    parts = [scene_prompt.strip()]
    art_direction = style.get("art_direction")
    palette = style.get("palette")
    lighting = style.get("lighting")
    if art_direction:
        parts.append(f"Art direction: {art_direction}.")
    if palette:
        parts.append(f"Color palette: {palette}.")
    if lighting:
        parts.append(f"Lighting: {lighting}.")
    if character_note:
        parts.append(character_note.strip())
    parts.append("Children's storybook illustration, wholesome, safe for ages 3-8.")
    return " ".join(parts)


from services.config_service import resolve_model


async def _generate_via_nano_banana(prompt: str, session_id: str) -> Tuple[bytes, str]:
    if not EMERGENT_LLM_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY missing")
    provider, model_name, source = await resolve_model(
        "scene_image_generation", IMAGE_MODEL_PROVIDER, IMAGE_MODEL_NAME
    )
    logger.info(f"[config] stage=scene_image_generation source={source} model={provider}/{model_name}")
    chat = (
        LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id,
                system_message="You are an expert children's book illustrator.")
        .with_model(provider, model_name)
        .with_params(modalities=["image", "text"])
    )
    text, images = await chat.send_message_multimodal_response(UserMessage(text=prompt))
    if not images:
        raise ValueError("No images returned from Nano Banana")
    img = images[0]
    b64_data = img.get("data")
    mime = img.get("mime_type", "image/png")
    if not b64_data:
        raise ValueError("Empty image data")
    image_bytes = base64.b64decode(b64_data)
    logger.info(f"Nano Banana image generated: {len(image_bytes)} bytes, {mime}")
    return image_bytes, mime


async def generate_image(
    scene_prompt: str,
    style_guide: dict | None = None,
    character_note: str = "",
    session_hint: str = "scene",
) -> Tuple[bytes, str, dict]:
    """Try Nano Banana; fall back to placeholder on any error."""
    session_id = f"img-{session_hint}-{uuid.uuid4().hex[:8]}"
    full_prompt = _build_image_prompt(scene_prompt, style_guide or {}, character_note)
    try:
        image_bytes, mime = await _generate_via_nano_banana(full_prompt, session_id)
        return image_bytes, mime, {"provider": "ai", "model": IMAGE_MODEL_NAME, "prompt_used": full_prompt}
    except Exception as e:
        logger.warning(f"Nano Banana failed, using fallback placeholder: {e}")
        return _PLACEHOLDER_PNG, "image/png", {
            "provider": "fallback",
            "model": "placeholder",
            "error": str(e),
            "prompt_used": full_prompt,
        }
