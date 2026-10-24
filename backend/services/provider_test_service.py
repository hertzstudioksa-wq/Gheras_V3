"""Provider Connectivity Tests — Phase H.

Backend-only checks that resolve secrets via secret_overrides_service and
make a *minimal* call to verify auth + reachability. No image generation,
no LLM tokens billed beyond the cheapest possible probe.

Each tester returns:
    {
      "provider": str,
      "ok": bool,
      "auth_ok": bool,
      "reachable": bool,
      "model_reachable": bool | None,
      "latency_ms": int,
      "secret_source": "env" | "override" | "missing",
      "secret_masked": "***1234" | None,
      "error": str | None,
    }
"""
from __future__ import annotations

import logging
import time
import asyncio
from typing import Optional

import httpx

from services.secret_overrides_service import get_secret_with_source

logger = logging.getLogger("provider_test_service")

TIMEOUT = httpx.Timeout(10.0)


def _mask(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    return f"***{v[-4:]}" if len(v) >= 4 else "***"


def _result(provider: str, ok: bool, auth_ok: bool, reachable: bool,
            latency_ms: int, secret: Optional[str], source: str,
            error: Optional[str] = None,
            model_reachable: Optional[bool] = None) -> dict:
    return {
        "provider": provider,
        "ok": ok,
        "auth_ok": auth_ok,
        "reachable": reachable,
        "model_reachable": model_reachable,
        "latency_ms": latency_ms,
        "secret_source": source,
        "secret_masked": _mask(secret),
        "error": error,
    }


# ---- OpenAI ---------------------------------------------------------------
async def test_openai() -> dict:
    from services.config_service import DEFAULT_MODELS

    secret, source = await get_secret_with_source("OPENAI_API_KEY")
    if not secret:
        return _result("openai", False, False, False, 0, None, "missing",
                       "OPENAI_API_KEY not configured")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            resp = await c.get("https://api.openai.com/v1/models",
                                headers={"Authorization": f"Bearer {secret}"})
        latency = int((time.monotonic() - started) * 1000)
        if resp.status_code == 200:
            data = resp.json()
            models = {m.get("id") for m in data.get("data", [])}
            mr = DEFAULT_MODELS["scene_image_generation"]["model_name"] in models
            return _result("openai", True, True, True, latency, secret, source,
                           model_reachable=mr)
        if resp.status_code in (401, 403):
            return _result("openai", False, False, True, latency, secret, source,
                           f"auth failed: HTTP {resp.status_code}")
        return _result("openai", False, True, True, latency, secret, source,
                       f"HTTP {resp.status_code}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("openai", False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


# ---- Anthropic (Claude) — text stages ------------------------------------
async def test_anthropic() -> dict:
    """Lists models (no tokens spent): validates the key and that the default
    text model is available to it."""
    secret, source = await get_secret_with_source("ANTHROPIC_API_KEY")
    if not secret:
        return _result("anthropic", False, False, False, 0, None, "missing",
                       "ANTHROPIC_API_KEY not configured")
    import anthropic
    from services.config_service import DEFAULT_MODELS

    started = time.monotonic()
    try:
        client = anthropic.AsyncAnthropic(api_key=secret, timeout=TIMEOUT, max_retries=0)
        page = await client.models.list(limit=100)
        latency = int((time.monotonic() - started) * 1000)
        wanted = DEFAULT_MODELS["scenario_generation"]["model_name"]
        return _result("anthropic", True, True, True, latency, secret, source,
                       model_reachable=wanted in {m.id for m in page.data})
    except anthropic.AuthenticationError as e:
        latency = int((time.monotonic() - started) * 1000)
        return _result("anthropic", False, False, True, latency, secret, source, f"auth failed: {e}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("anthropic", False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


# ---- Google Gemini — free-tier testing provider ----------------------------
async def test_gemini() -> dict:
    """Lists models (no generation spent): validates the key and whether the
    testing preset's image model is available to it."""
    secret, source = await get_secret_with_source("GEMINI_API_KEY")
    if not secret:
        return _result("gemini", False, False, False, 0, None, "missing",
                       "GEMINI_API_KEY not configured")
    from google import genai
    from services.preset_stacks_service import GEMINI_TEST_IMAGE_MODEL

    started = time.monotonic()
    try:
        client = genai.Client(api_key=secret)
        names = {m.name.removeprefix("models/") async for m in await client.aio.models.list()}
        latency = int((time.monotonic() - started) * 1000)
        return _result("gemini", True, True, True, latency, secret, source,
                       model_reachable=GEMINI_TEST_IMAGE_MODEL in names)
    except genai.errors.ClientError as e:
        latency = int((time.monotonic() - started) * 1000)
        return _result("gemini", False, False, True, latency, secret, source, f"auth/request failed: {e}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("gemini", False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


# ---- ElevenLabs -----------------------------------------------------------
async def test_elevenlabs() -> dict:
    secret, source = await get_secret_with_source("ELEVENLABS_API_KEY")
    if not secret:
        return _result("elevenlabs", False, False, False, 0, None, "missing",
                       "ELEVENLABS_API_KEY not configured")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get("https://api.elevenlabs.io/v1/user",
                             headers={"xi-api-key": secret})
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            return _result("elevenlabs", True, True, True, latency, secret, source,
                           model_reachable=True)
        if r.status_code in (401, 403):
            return _result("elevenlabs", False, False, True, latency, secret, source,
                           f"auth failed: HTTP {r.status_code}")
        return _result("elevenlabs", False, True, True, latency, secret, source,
                       f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("elevenlabs", False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


# ---- ElevenLabs Music ------------------------------------------------------
async def test_elevenlabs_music() -> dict:
    """Probes /v1/music with a minimal payload to detect plan availability.

    Distinguishes:
      * missing_key       → no key configured
      * auth_failed (401) → key invalid
      * plan_required (403)→ key valid but plan does not include Music API
      * ok (any 2xx)      → plan allows Music
    """
    secret, source = await get_secret_with_source("ELEVENLABS_API_KEY")
    if not secret:
        return _result("elevenlabs_music", False, False, False, 0, None,
                       "missing", "ELEVENLABS_API_KEY not configured")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            # Minimal payload — provider may still bill if successful, so we
            # use the smallest legal request and rely on auth failure first.
            r = await c.post(
                "https://api.elevenlabs.io/v1/music",
                headers={"xi-api-key": secret, "Content-Type": "application/json"},
                json={"prompt": "test", "music_length_ms": 10000,
                      "output_format": "mp3_44100_128"},
            )
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code in (200, 201, 202):
            return _result("elevenlabs_music", True, True, True, latency,
                           secret, source, model_reachable=True)
        if r.status_code == 401:
            return _result("elevenlabs_music", False, False, True, latency,
                           secret, source, "HTTP 401: invalid key")
        if r.status_code == 403:
            return _result("elevenlabs_music", False, True, True, latency,
                           secret, source,
                           "HTTP 403: plan does not include Music API (Creator+ required)")
        return _result("elevenlabs_music", False, True, True, latency,
                       secret, source, f"HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("elevenlabs_music", False, False, False, latency,
                       secret, source, f"{type(e).__name__}: {e}")


# ---- fal.ai (legacy shared key) ------------------------------------------
async def _test_fal_key(env_key: str, label: str) -> dict:
    secret, source = await get_secret_with_source(env_key)
    if not secret:
        return _result(label, False, False, False, 0, None, "missing",
                       f"{env_key} not configured")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get("https://fal.run/status",
                             headers={"Authorization": f"Key {secret}"})
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code in (200, 204):
            return _result(label, True, True, True, latency, secret, source,
                           model_reachable=True)
        if r.status_code in (401, 403):
            return _result(label, False, False, True, latency, secret, source,
                           f"auth failed: HTTP {r.status_code}")
        if r.status_code == 404:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                r2 = await c.get("https://queue.fal.run/",
                                  headers={"Authorization": f"Key {secret}"})
            latency = int((time.monotonic() - started) * 1000)
            ok = r2.status_code not in (401, 403)
            return _result(label, ok, ok, True, latency, secret, source,
                           model_reachable=r2.status_code in (200, 204, 404))
        return _result(label, False, True, True, latency, secret, source,
                       f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result(label, False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


async def test_fal() -> dict:
    return await _test_fal_key("FAL_KEY", "fal")


async def test_fal_scene() -> dict:
    out = await _test_fal_key("FAL_KEY_SCENE", "fal_scene")
    if not out["ok"]:
        # Fallback to legacy FAL_KEY if specific key missing.
        legacy = await _test_fal_key("FAL_KEY", "fal_scene")
        if legacy["ok"]:
            legacy["note"] = "FAL_KEY_SCENE missing; legacy FAL_KEY used as fallback."
            return legacy
    return out


async def test_fal_narration() -> dict:
    out = await _test_fal_key("FAL_KEY_NARRATION", "fal_narration")
    if not out["ok"]:
        legacy = await _test_fal_key("FAL_KEY", "fal_narration")
        if legacy["ok"]:
            legacy["note"] = "FAL_KEY_NARRATION missing; legacy FAL_KEY used as fallback."
            return legacy
    return out


async def test_fal_music() -> dict:
    out = await _test_fal_key("FAL_KEY_MUSIC", "fal_music")
    if not out["ok"]:
        legacy = await _test_fal_key("FAL_KEY", "fal_music")
        if legacy["ok"]:
            legacy["note"] = "FAL_KEY_MUSIC missing; legacy FAL_KEY used as fallback."
            return legacy
    return out


async def test_fal_video() -> dict:
    out = await _test_fal_key("FAL_KEY_VIDEO", "fal_video")
    if not out["ok"]:
        legacy = await _test_fal_key("FAL_KEY", "fal_video")
        if legacy["ok"]:
            legacy["note"] = "FAL_KEY_VIDEO missing; legacy FAL_KEY used as fallback."
            return legacy
    return out


# ---- Moyasar --------------------------------------------------------------
async def test_moyasar() -> dict:
    secret, source = await get_secret_with_source("MOYASAR_SECRET_KEY")
    if not secret:
        return _result("moyasar", False, False, False, 0, None, "missing",
                       "MOYASAR_SECRET_KEY not configured")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get("https://api.moyasar.com/v1/invoices", params={"page": 1}, auth=(secret, ""))
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            return _result("moyasar", True, True, True, latency, secret, source,
                           model_reachable=True)
        if r.status_code in (401, 403):
            return _result("moyasar", False, False, True, latency, secret, source,
                           f"auth failed: HTTP {r.status_code}")
        return _result("moyasar", False, True, True, latency, secret, source,
                       f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("moyasar", False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


PROVIDERS = {
    "openai":            test_openai,
    "anthropic":         test_anthropic,
    "gemini":            test_gemini,
    "elevenlabs":        test_elevenlabs,
    "elevenlabs_music":  test_elevenlabs_music,
    "fal":               test_fal,
    "fal_scene":         test_fal_scene,
    "fal_narration":     test_fal_narration,
    "fal_music":         test_fal_music,
    "fal_video":         test_fal_video,
    "moyasar":           test_moyasar,
}


async def test_provider(provider: str) -> dict:
    fn = PROVIDERS.get(provider)
    if not fn:
        return {"provider": provider, "ok": False, "error": "unknown_provider"}
    return await fn()


async def test_all_providers() -> list[dict]:
    return list(await asyncio.gather(*(fn() for fn in PROVIDERS.values())))
