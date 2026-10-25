"""fal.ai calls (narration, music, video clips, images) via the official client.

The queue's status/result URLs use only "owner/app" (e.g. fal-ai/elevenlabs),
not the full endpoint path — hand-built polling URLs with the full path get a
405 forever. fal_client handles submit/poll/result correctly, so every fal
stage goes through here.
"""
import asyncio
import logging

import httpx

from services import engine_health
from services.ai import AIConfigError, AIError, classify_http_error, fake_providers

logger = logging.getLogger("ai.fal")

# Files we upload (scene illustrations, character sheets) are only needed while
# the provider runs; keep them on fal's CDN for a day, not forever.
UPLOAD_TTL = "1d"


async def resolve_key(env_key: str) -> str:
    """Per-capability key (e.g. FAL_KEY_VIDEO), falling back to the shared FAL_KEY."""
    from services.secret_overrides_service import get_secret

    value = await get_secret(env_key) or await get_secret("FAL_KEY")
    if not value:
        # One fal account usually backs every capability key; use any of them.
        for other in ("FAL_KEY_SCENE", "FAL_KEY_VIDEO", "FAL_KEY_NARRATION", "FAL_KEY_MUSIC"):
            value = await get_secret(other)
            if value:
                break
    if not value:
        raise AIConfigError(f"{env_key} (or FAL_KEY) is not configured")
    return value


async def _http_error(stage: str, e) -> AIError:
    """Classify a fal HTTP error; an exhausted balance also pauses the engine."""
    await engine_health.note_error(stage, e.message)
    return classify_http_error(stage, "fal", e.status_code, e.message)


def _client(key: str, timeout: float):
    import fal_client

    return fal_client.AsyncClient(key=key, default_timeout=timeout)


async def submit(*, stage: str, env_key: str, model: str, arguments: dict) -> str:
    """Queue a request and return its request_id (persist it to resume later)."""
    import fal_client

    if fake_providers.enabled():
        return await fake_providers.fal_submit(stage, model, arguments)

    client = _client(await resolve_key(env_key), 60.0)
    try:
        handle = await client.submit(model, arguments)
    except fal_client.FalClientHTTPError as e:
        raise await _http_error(stage, e) from e
    except fal_client.FalClientError as e:
        raise AIError(f"fal submit failed ({stage}): {type(e).__name__}: {e}") from e
    logger.info(f"[ai.fal] stage={stage} model={model} submitted request_id={handle.request_id}")
    await engine_health.note_success()
    return handle.request_id


async def wait(*, stage: str, env_key: str, model: str, request_id: str,
               timeout: float = 900.0, poll_interval: float = 3.0) -> dict:
    """Wait for a queued request and return its result JSON."""
    import fal_client

    if fake_providers.enabled():
        return await fake_providers.fal_wait(stage, model, request_id)

    client = _client(await resolve_key(env_key), timeout)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while True:
            status = await client.status(model, request_id)
            if isinstance(status, fal_client.Completed):
                break
            if loop.time() > deadline:
                raise AIError(f"fal request timed out after {int(timeout)}s ({stage}, request_id={request_id})")
            await asyncio.sleep(poll_interval)
        result = await client.result(model, request_id)
    except fal_client.FalClientHTTPError as e:
        raise await _http_error(stage, e) from e
    except fal_client.FalClientError as e:
        raise AIError(f"fal request failed ({stage}): {type(e).__name__}: {e}") from e
    await engine_health.note_success()
    return result


async def run(*, stage: str, env_key: str, model: str, arguments: dict,
              timeout: float = 900.0, poll_interval: float = 3.0) -> dict:
    request_id = await submit(stage=stage, env_key=env_key, model=model, arguments=arguments)
    return await wait(stage=stage, env_key=env_key, model=model, request_id=request_id,
                      timeout=timeout, poll_interval=poll_interval)


async def upload(*, env_key: str, data: bytes, content_type: str, file_name: str) -> str:
    """Upload bytes to fal's CDN (1-day expiry) and return a URL models can fetch."""
    import fal_client
    from fal_client.client import StorageSettings

    if fake_providers.enabled():
        return await fake_providers.fal_upload(data, content_type)

    client = _client(await resolve_key(env_key), 120.0)
    try:
        return await client.upload(data, content_type, file_name,
                                   lifecycle=StorageSettings(expires_in=UPLOAD_TTL))
    except fal_client.FalClientHTTPError as e:
        raise await _http_error("upload", e) from e


async def download(url: str, timeout: float = 120.0) -> bytes:
    if url.startswith(fake_providers.PREFIX):
        return fake_providers.read(url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        r = await c.get(url)
    if r.status_code != 200:
        raise AIError(f"fal output download failed: HTTP {r.status_code}")
    return r.content
