"""Direct OpenAI text path — bypasses emergentintegrations proxy.

Used when the admin model_registry row has env_key="OPENAI_API_KEY" AND the
OPENAI_API_KEY env var is set. The resulting call hits api.openai.com
directly, billed to the user's own OpenAI quota (not Emergent).

This module is intentionally small: one async helper per call type. The
caller is still responsible for prompt building, JSON parsing, fallback,
and all business logic. Swapping providers is purely a transport concern.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger("llm_direct")


def direct_openai_available() -> bool:
    """True iff OPENAI_API_KEY is set — cheap, no network call."""
    return bool(os.environ.get("OPENAI_API_KEY"))


async def direct_openai_chat(
    system_message: str,
    user_message: str,
    model: str,
    *,
    timeout: float = 120.0,
    max_output_tokens: Optional[int] = None,
) -> str:
    """Send a single-turn chat completion via OpenAI directly.

    Returns assistant text on success. Raises on failure — caller decides
    whether to fallback. Never logs the API key.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    try:
        from openai import AsyncOpenAI
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(f"openai SDK not installed: {e}")

    client = AsyncOpenAI(api_key=api_key, timeout=timeout)
    params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user",   "content": user_message},
        ],
    }
    # Only GPT-5.x / o-series consistently accept max_completion_tokens; older
    # ones use max_tokens. Skip it entirely when None to let the server decide.
    if max_output_tokens is not None:
        params["max_completion_tokens"] = max_output_tokens

    logger.info(f"[direct-openai] calling model={model} (text)")
    resp = await client.chat.completions.create(**params)
    if not resp or not resp.choices:
        raise RuntimeError("empty OpenAI response")
    content = resp.choices[0].message.content or ""
    if not content.strip():
        raise RuntimeError("OpenAI returned empty content")
    return content
