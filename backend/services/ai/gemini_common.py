"""Shared Gemini call with retries on transient server errors.

Free-tier and preview models regularly answer 503 "high demand" for a few
seconds; without a retry a single blip fails a whole order stage. Quota errors
(429) are not retried here: on the free tier they usually mean "limit 0".
"""
import asyncio
import logging

from services.ai import AIError, classify_http_error

logger = logging.getLogger("ai.gemini")

RETRY_DELAYS = (3, 8, 20)  # seconds between attempts on 5xx


async def generate_content(client, *, stage: str, model: str, contents, config):
    from google import genai

    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            return await client.aio.models.generate_content(model=model, contents=contents, config=config)
        except genai.errors.ServerError as e:
            if attempt == len(RETRY_DELAYS):
                raise AIError(f"Gemini call failed ({stage}) after {attempt + 1} attempts: {type(e).__name__}: {e}") from e
            delay = RETRY_DELAYS[attempt]
            logger.warning(f"[ai.gemini] stage={stage} model={model} attempt={attempt + 1} {e.code} — retrying in {delay}s")
            await asyncio.sleep(delay)
        except genai.errors.APIError as e:
            raise classify_http_error(stage, "Gemini", getattr(e, "code", None), str(e)) from e
