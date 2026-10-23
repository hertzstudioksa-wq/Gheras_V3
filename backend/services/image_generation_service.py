"""Scene / cover image generation.

Public contract (used by generation_orchestrator):
  generate_image(scene_prompt, style_guide, character_note, session_hint,
                 references=None, support_true_refs=True, prompt_augmentation="")
    -> (image_bytes, mime_type, provider_meta)

`references` is a list of {"image_bytes", "mime_type", "kind", "name"} dicts —
typically the approved cartoon character of the child (plus extra characters
or the favourite toy). They are sent to the image model as visual guides so the
child looks the same on every page.

Failures raise (services.ai.AIError). There is deliberately no placeholder
image and no silent retry without references: a missing likeness or a blank
page must surface as a failed job, never as a delivered book.
"""
import logging
from typing import Tuple

from services.ai.image_client import generate_image as _provider_generate
from services.config_service import resolve_model

logger = logging.getLogger("image_generation_service")

IMAGE_MODEL_PROVIDER = "openai"
IMAGE_MODEL_NAME = "gpt-image-2"


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
    parts.append("Full-bleed scene that fills the whole frame edge to edge: no border, frame, vignette, "
                 "white margin or checkerboard/transparency pattern.")
    parts.append("Do not draw any text, letters or words in the image.")
    return " ".join(p for p in parts if p)


async def generate_image(
    scene_prompt: str,
    style_guide: dict | None = None,
    character_note: str = "",
    session_hint: str = "scene",
    references: list[dict] | None = None,
    support_true_refs: bool = True,
    prompt_augmentation: str = "",
    stage: str = "scene_image_generation",
) -> Tuple[bytes, str, dict]:
    full_prompt = _build_image_prompt(scene_prompt, style_guide or {}, character_note, prompt_augmentation)
    provider, model_name, model_src = await resolve_model(stage, IMAGE_MODEL_PROVIDER, IMAGE_MODEL_NAME)
    ref_bytes = [r["image_bytes"] for r in (references or []) if r.get("image_bytes")] if support_true_refs else []
    logger.info(
        f"[config] stage={stage} source={model_src} model={provider}/{model_name} "
        f"refs={len(ref_bytes)} hint={session_hint}"
    )

    image_bytes, mime, meta = await _provider_generate(
        stage=stage,
        provider=provider,
        model=model_name,
        prompt=full_prompt,
        references=ref_bytes or None,
    )
    return image_bytes, mime, {
        "provider": "ai",
        "model": model_name,
        "provider_name": provider,
        "prompt_used": full_prompt,
        "references_attempted": bool(ref_bytes),
        "references_used": bool(ref_bytes),
        "references_count": len(ref_bytes),
        "fallback_path": "provider-no-image-input" if references and not support_true_refs else None,
        "fallback_reason": None,
        "usage": meta.get("usage"),
    }
