"""Image generation service — Nano Banana (Gemini 3.1 Flash Image Preview).

Phase E — multi-provider safe path for visual reference injection:

Public contract:
  generate_image(scene_prompt, style_guide, character_note, session_hint,
                 references=None, support_true_refs=True)
    -> (image_bytes, mime_type, provider_meta)

`references` (optional) is a list of dicts:
    {"image_bytes": bytes, "mime_type": str, "kind": "child"|"extra"|"toy", "name": str}
The service:
  1. If `references` is provided AND `support_true_refs`, send them to Nano
     Banana via `ImageContent(base64_data=..., mime_type=...)`.
  2. On any failure during the multi-image call, retry WITHOUT references
     (text-only) and record `references_attempted=True, references_used=False,
     fallback_path="text-only", fallback_reason=<reason>`.
  3. If `support_true_refs=False`, the call is text-only from the start and
     meta records `fallback_path="provider-no-image-input"`.
  4. On total provider failure, returns the placeholder PNG.

`provider_meta` keys (Phase E):
    provider              "ai" | "fallback"
    model                 model name
    prompt_used           full prompt sent
    references_attempted  bool
    references_used       bool
    references_count      int          (count actually sent on the SUCCESSFUL call)
    fallback_path         None | "text-only" | "provider-no-image-input"
    fallback_reason       None | str
"""
import os
import base64
import logging
import uuid
from typing import Tuple
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent

logger = logging.getLogger("image_generation_service")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
IMAGE_MODEL_PROVIDER = "gemini"
IMAGE_MODEL_NAME = "gemini-3.1-flash-image-preview"

# Minimal 1x1 transparent PNG (safe, tiny, never breaks the UI)
_PLACEHOLDER_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def _build_image_prompt(scene_prompt: str, style_guide: dict, character_note: str,
                        prompt_augmentation: str = "") -> str:
    """Compose a rich, style-consistent English prompt."""
    style = style_guide or {}
    parts = [(scene_prompt or "").strip()]
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
        parts.append((character_note or "").strip())
    if prompt_augmentation:
        parts.append(prompt_augmentation.strip())
    parts.append("Children's storybook illustration, wholesome, safe for ages 3-8.")
    return " ".join(p for p in parts if p)


from services.config_service import resolve_model


def _build_image_contents(references: list[dict] | None) -> list[ImageContent]:
    """Convert internal reference descriptors to emergentintegrations ImageContent."""
    if not references:
        return []
    items: list[ImageContent] = []
    for ref in references:
        try:
            data = ref.get("image_bytes")
            mime = ref.get("mime_type") or "image/png"
            if not data:
                continue
            b64 = base64.b64encode(data).decode("ascii") if isinstance(data, (bytes, bytearray)) else str(data)
            # Embed MIME hint inline if not a plain PNG (Nano Banana auto-detects from the
            # decoded bytes; mime_type is informational only).
            _ = mime
            items.append(ImageContent(image_base64=b64))
        except Exception as e:  # noqa: BLE001
            logger.warning(f"reference build skipped ({ref.get('kind')}/{ref.get('name')}): {e}")
            continue
    return items


async def _call_nano_banana(prompt: str, session_id: str,
                             references: list[dict] | None) -> Tuple[bytes, str, dict]:
    """Single Nano Banana call. Raises on any failure (caller handles fallback)."""
    if not EMERGENT_LLM_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY missing")
    provider, model_name, model_src = await resolve_model(
        "scene_image_generation", IMAGE_MODEL_PROVIDER, IMAGE_MODEL_NAME
    )
    logger.info(f"[config] stage=scene_image_generation source={model_src} model={provider}/{model_name}")
    chat = (
        LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id,
                system_message="You are an expert children's book illustrator.")
        .with_model(provider, model_name)
        .with_params(modalities=["image", "text"])
    )
    file_contents = _build_image_contents(references)
    msg = UserMessage(text=prompt, file_contents=file_contents) if file_contents else UserMessage(text=prompt)
    text, images = await chat.send_message_multimodal_response(msg)
    if not images:
        raise ValueError("No images returned from Nano Banana")
    img = images[0]
    b64_data = img.get("data")
    mime = img.get("mime_type", "image/png")
    if not b64_data:
        raise ValueError("Empty image data")
    image_bytes = base64.b64decode(b64_data)
    logger.info(
        f"Nano Banana image generated: {len(image_bytes)} bytes, {mime}, "
        f"references_sent={len(file_contents)}"
    )
    return image_bytes, mime, {"references_count": len(file_contents), "model": model_name}


async def generate_image(
    scene_prompt: str,
    style_guide: dict | None = None,
    character_note: str = "",
    session_hint: str = "scene",
    references: list[dict] | None = None,
    support_true_refs: bool = True,
    prompt_augmentation: str = "",
) -> Tuple[bytes, str, dict]:
    """Try Nano Banana (with refs if any); fall back to text-only; finally placeholder."""
    session_id = f"img-{session_hint}-{uuid.uuid4().hex[:8]}"
    full_prompt = _build_image_prompt(scene_prompt, style_guide or {}, character_note, prompt_augmentation)

    refs_attempted = bool(references) and support_true_refs
    fallback_path: str | None = None
    fallback_reason: str | None = None

    # --- Path 1: text-only because provider doesn't support refs --------------
    if references and not support_true_refs:
        fallback_path = "provider-no-image-input"
        fallback_reason = "support_true_refs=False"

    if refs_attempted:
        # --- Path 2: with references -----------------------------------------
        try:
            image_bytes, mime, meta = await _call_nano_banana(full_prompt, session_id, references)
            return image_bytes, mime, {
                "provider": "ai",
                "model": meta.get("model"),
                "prompt_used": full_prompt,
                "references_attempted": True,
                "references_used": True,
                "references_count": meta.get("references_count", 0),
                "fallback_path": None,
                "fallback_reason": None,
            }
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Nano Banana with refs failed, retrying text-only: {e}")
            fallback_path = "text-only"
            fallback_reason = f"with_refs_failed:{type(e).__name__}"

    # --- Path 3: text-only (either by design or after refs failure) ----------
    try:
        image_bytes, mime, meta = await _call_nano_banana(full_prompt, session_id, None)
        return image_bytes, mime, {
            "provider": "ai",
            "model": meta.get("model"),
            "prompt_used": full_prompt,
            "references_attempted": refs_attempted,
            "references_used": False,
            "references_count": 0,
            "fallback_path": fallback_path or ("text-only" if references else None),
            "fallback_reason": fallback_reason,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Nano Banana failed, using fallback placeholder: {e}")
        return _PLACEHOLDER_PNG, "image/png", {
            "provider": "fallback",
            "model": "placeholder",
            "error": str(e),
            "prompt_used": full_prompt,
            "references_attempted": refs_attempted,
            "references_used": False,
            "references_count": 0,
            "fallback_path": "placeholder",
            "fallback_reason": f"provider_failed:{type(e).__name__}",
        }
