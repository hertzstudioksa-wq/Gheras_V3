"""Image generation: OpenAI GPT Image (generations + reference-guided edits)."""
import base64
import io
import logging
from typing import Optional

from services.ai import AIConfigError, AIError, require_key

logger = logging.getLogger("ai.image")

IMAGE_PROVIDERS = {"openai"}


def _as_png(data: bytes) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        if img.format == "PNG":
            return data
        out = io.BytesIO()
        img.convert("RGBA").save(out, format="PNG")
        return out.getvalue()


async def generate_image(
    *,
    stage: str,
    provider: str,
    model: str,
    prompt: str,
    references: Optional[list[bytes]] = None,
    size: str = "1024x1024",
    quality: str = "high",
    background: Optional[str] = None,
    timeout: float = 240.0,
) -> tuple[bytes, str, dict]:
    """Returns (image_bytes, mime_type, meta). With `references`, the images are
    sent as visual guides (e.g. the approved child character) via the edits
    endpoint with high input fidelity so the likeness carries across pages."""
    if provider not in IMAGE_PROVIDERS:
        raise AIConfigError(f"No image executor for provider '{provider}' (stage {stage})")

    from openai import AsyncOpenAI, OpenAIError

    client = AsyncOpenAI(api_key=await require_key("OPENAI_API_KEY"), timeout=timeout, max_retries=2)
    extra = {"background": background} if background else {}
    try:
        if references:
            files = [(f"ref{i}.png", _as_png(ref), "image/png") for i, ref in enumerate(references)]
            resp = await client.images.edit(
                model=model, image=files, prompt=prompt, size=size, quality=quality,
                input_fidelity="high", n=1, **extra,
            )
        else:
            resp = await client.images.generate(model=model, prompt=prompt, size=size, quality=quality, n=1, **extra)
    except OpenAIError as e:
        raise AIError(f"OpenAI image call failed ({stage}): {type(e).__name__}: {e}") from e

    b64 = resp.data[0].b64_json if resp and resp.data else None
    if not b64:
        raise AIError(f"OpenAI returned no image ({stage})")
    image_bytes = base64.b64decode(b64)
    usage = getattr(resp, "usage", None)
    logger.info(
        f"[ai.image] stage={stage} model={model} refs={len(references or [])} size={size} "
        f"quality={quality} bytes={len(image_bytes)} usage={usage.model_dump() if usage else None}"
    )
    return image_bytes, "image/png", {
        "provider": provider,
        "model": model,
        "references_count": len(references or []),
        "size": size,
        "quality": quality,
        "usage": usage.model_dump() if usage else None,
    }
