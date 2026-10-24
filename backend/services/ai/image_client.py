"""Image generation: OpenAI GPT Image (generations + reference-guided edits);
Gemini image models as a low-cost option for end-to-end testing."""
import base64
import io
import logging
from typing import Optional

from services.ai import AIConfigError, AIError, classify_http_error, gemini_common, require_key

logger = logging.getLogger("ai.image")

IMAGE_PROVIDERS = {"openai", "gemini", "fal_image"}
# 16:9 video keyframes / character sheets.
WIDE = "1536x864"
_GEMINI_ASPECT = {"1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3", WIDE: "16:9"}
# GPT Image has no 16:9 size; 3:2 is the closest and assembly crops the centre.
_OPENAI_SIZE = {WIDE: "1536x1024"}


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
    endpoint so the likeness carries across pages."""
    if provider not in IMAGE_PROVIDERS:
        raise AIConfigError(f"No image executor for provider '{provider}' (stage {stage})")
    if provider == "gemini":
        return await _gemini(stage, model, prompt, references, size, timeout)
    if provider == "fal_image":
        return await _fal_image(stage, model, prompt, references, size, timeout, quality)

    from openai import APIStatusError, AsyncOpenAI, OpenAIError

    client = AsyncOpenAI(api_key=await require_key("OPENAI_API_KEY"), timeout=timeout, max_retries=2)
    extra = {"background": background} if background else {}
    try:
        if references:
            files = [(f"ref{i}.png", _as_png(ref), "image/png") for i, ref in enumerate(references)]
            # Only gpt-image-1 models take input_fidelity; gpt-image-2 rejects it
            # (400 invalid_input_fidelity_model) and keeps likeness by default.
            if model.startswith("gpt-image-1"):
                extra["input_fidelity"] = "high"
            resp = await client.images.edit(
                model=model, image=files, prompt=prompt, size=_OPENAI_SIZE.get(size, size), quality=quality, n=1, **extra,
            )
        else:
            resp = await client.images.generate(model=model, prompt=prompt, size=_OPENAI_SIZE.get(size, size), quality=quality, n=1, **extra)
    except APIStatusError as e:
        raise classify_http_error(stage, "OpenAI image", e.status_code, str(e)) from e
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


async def _gemini(stage, model, prompt, references, size, timeout) -> tuple[bytes, str, dict]:
    """Gemini image models: reference images go in as parts next to the prompt."""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=await require_key("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),
    )
    contents = [types.Part.from_bytes(data=_as_png(ref), mime_type="image/png") for ref in references or []]
    contents.append(prompt)
    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio=_GEMINI_ASPECT.get(size, "1:1")),
    )
    resp = await gemini_common.generate_content(client, stage=stage, model=model, contents=contents, config=config)

    candidate = resp.candidates[0] if resp.candidates else None
    parts =(candidate.content.parts or []) if candidate and candidate.content else []
    image = next((p.inline_data for p in parts if p.inline_data and p.inline_data.data), None)
    if image is None:
        finish = getattr(candidate, "finish_reason", None)
        block = getattr(resp.prompt_feedback, "block_reason", None) if resp.prompt_feedback else None
        raise AIError(f"Gemini returned no image ({stage}, finish={finish}, block_reason={block})")
    usage = resp.usage_metadata
    logger.info(
        f"[ai.image] stage={stage} model={model} refs={len(references or [])} bytes={len(image.data)} "
        f"tokens_in={getattr(usage, 'prompt_token_count', None)} tokens_out={getattr(usage, 'candidates_token_count', None)}"
    )
    return image.data, image.mime_type or "image/png", {
        "provider": "gemini",
        "model": model,
        "references_count": len(references or []),
        "size": size,
        "usage": usage.model_dump() if usage else None,
    }


async def _fal_image(stage, model, prompt, references, size, timeout, quality="high") -> tuple[bytes, str, dict]:
    """fal-hosted image models (default fal-ai/gemini-25-flash-image). With
    references the "/edit" endpoint is used and the images are first uploaded
    to fal's CDN (1-day expiry) — models fetch inputs by URL."""
    from services.ai import fal

    arguments = {"prompt": prompt, "num_images": 1, "output_format": "png"}
    if "gpt-image" in model:
        # OpenAI's models on fal: explicit pixel size, opaque background (a
        # "transparent" request draws a fake checkerboard), high quality.
        w, h = (int(x) for x in size.split("x"))
        arguments.update({"quality": quality, "background": "opaque",
                          "image_size": {"width": w, "height": h} if "gpt-image-2" in model
                          else _OPENAI_SIZE.get(size, size)})
        if "gpt-image-1" in model and references:
            arguments["input_fidelity"] = "high"
    else:
        arguments["aspect_ratio"] = _GEMINI_ASPECT.get(size, "1:1")
        if "nano-banana-pro" in model:
            arguments["resolution"] = "1K"
    endpoint = model.removesuffix("/edit")
    if references:
        arguments["image_urls"] = [
            await fal.upload(env_key="FAL_KEY_SCENE", data=_as_png(ref), content_type="image/png", file_name=f"ref{i}.png")
            for i, ref in enumerate(references)
        ]
        endpoint = f"{endpoint}/edit"
    result = await fal.run(stage=stage, env_key="FAL_KEY_SCENE", model=endpoint, arguments=arguments,
                           timeout=timeout, poll_interval=2.0)
    images = result.get("images") or []
    if not images or not images[0].get("url"):
        raise AIError(f"fal returned no image ({stage})")
    data = await fal.download(images[0]["url"])
    logger.info(f"[ai.image] stage={stage} model={endpoint} refs={len(references or [])} bytes={len(data)}")
    return data, images[0].get("content_type") or "image/png", {
        "provider": "fal_image",
        "model": endpoint,
        "references_count": len(references or []),
        "size": size,
        "usage": None,
    }
