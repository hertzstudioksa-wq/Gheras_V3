"""Text generation: Anthropic (Claude) primary, OpenAI optional."""
import logging
from typing import Optional

from services.ai import AIConfigError, AIError, require_key

logger = logging.getLogger("ai.text")

TEXT_PROVIDERS = {"anthropic", "openai"}


async def generate_text(
    *,
    stage: str,
    provider: str,
    model: str,
    system: str,
    user: str,
    json_schema: Optional[dict] = None,
    effort: str = "medium",
    max_tokens: int = 32000,
    timeout: float = 600.0,
) -> str:
    """Single-turn generation. Returns the response text (valid JSON when
    `json_schema` is given and the provider supports structured output)."""
    if provider == "anthropic":
        return await _anthropic(stage, model, system, user, json_schema, effort, max_tokens, timeout)
    if provider == "openai":
        from services.llm_direct import direct_openai_chat

        await require_key("OPENAI_API_KEY")
        return await direct_openai_chat(system, user, model, timeout=timeout)
    raise AIConfigError(f"No text executor for provider '{provider}' (stage {stage})")


async def _anthropic(stage, model, system, user, json_schema, effort, max_tokens, timeout) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=await require_key("ANTHROPIC_API_KEY"), timeout=timeout, max_retries=2)
    output_config: dict = {"effort": effort}
    if json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    try:
        # Streamed so long plans never hit HTTP timeouts; the final message is
        # all we use. Caching covers the stable system prompt across orders;
        # "default" fallbacks re-run a classifier refusal on Anthropic's
        # recommended model instead of failing the order.
        async with client.beta.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            cache_control={"type": "ephemeral"},
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            message = await stream.get_final_message()
    except anthropic.APIError as e:
        raise AIError(f"Anthropic call failed ({stage}): {type(e).__name__}: {e}") from e

    usage = message.usage
    logger.info(
        f"[ai.text] stage={stage} model={message.model} stop={message.stop_reason} "
        f"in={usage.input_tokens} out={usage.output_tokens} "
        f"cache_read={getattr(usage, 'cache_read_input_tokens', 0)} request_id={message._request_id}"
    )
    if message.stop_reason == "refusal":
        category = getattr(message.stop_details, "category", None) if message.stop_details else None
        raise AIError(f"Model declined the request ({stage}, category={category})")
    if message.stop_reason == "max_tokens":
        raise AIError(f"Response truncated at max_tokens={max_tokens} ({stage})")
    text = "".join(block.text for block in message.content if block.type == "text").strip()
    if not text:
        raise AIError(f"Empty response ({stage})")
    return text
