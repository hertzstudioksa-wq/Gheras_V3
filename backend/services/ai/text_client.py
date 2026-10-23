"""Text generation: Anthropic (Claude) primary; OpenAI and Gemini optional
(Gemini's free tier is used for low-cost end-to-end testing)."""
import logging
from typing import Optional

from services.ai import AIConfigError, AIError, classify_http_error, gemini_common, require_key

logger = logging.getLogger("ai.text")

TEXT_PROVIDERS = {"anthropic", "openai", "gemini"}


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
    if provider == "gemini":
        return await _gemini(stage, model, system, user, json_schema, max_tokens, timeout)
    raise AIConfigError(f"No text executor for provider '{provider}' (stage {stage})")


async def _gemini(stage, model, system, user, json_schema, max_tokens, timeout) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=await require_key("GEMINI_API_KEY"),
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),
    )
    config = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        response_mime_type="application/json" if json_schema else None,
        response_json_schema=json_schema,
    )
    resp = await gemini_common.generate_content(client, stage=stage, model=model, contents=user, config=config)

    candidate = resp.candidates[0] if resp.candidates else None
    finish = getattr(candidate, "finish_reason", None)
    usage = resp.usage_metadata
    logger.info(
        f"[ai.text] stage={stage} model={model} finish={finish} "
        f"in={getattr(usage, 'prompt_token_count', None)} out={getattr(usage, 'candidates_token_count', None)}"
    )
    if candidate is None:
        block = getattr(resp.prompt_feedback, "block_reason", None) if resp.prompt_feedback else None
        raise AIError(f"Gemini returned no candidates ({stage}, block_reason={block})")
    if finish and str(finish).endswith("MAX_TOKENS"):
        raise AIError(f"Response truncated at max_tokens={max_tokens} ({stage})")
    text = (resp.text or "").strip()
    if not text:
        raise AIError(f"Empty response ({stage}, finish={finish})")
    return text


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
    except anthropic.APIStatusError as e:
        raise classify_http_error(stage, "Anthropic", e.status_code, str(e)) from e
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
