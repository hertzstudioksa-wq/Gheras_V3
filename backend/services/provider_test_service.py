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
            mr = "gpt-image-1" in models or "gpt-4o" in models
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


# ---- Gemini / Emergent (probe via emergentintegrations) -------------------
async def test_emergent_llm() -> dict:
    """The Emergent Universal Key is used for both Gemini Nano Banana and
    Claude routes. We can't introspect Emergent's quota directly, so we just
    verify the SDK accepts the key shape and a minimal `LlmChat` instantiates
    without raising. Real provider test happens on Stage Lab runs."""
    secret, source = await get_secret_with_source("EMERGENT_LLM_KEY")
    if not secret:
        return _result("emergent", False, False, False, 0, None, "missing",
                       "EMERGENT_LLM_KEY not configured")
    started = time.monotonic()
    try:
        from emergentintegrations.llm.chat import LlmChat
        _ = LlmChat(api_key=secret, session_id="probe",
                    system_message="probe").with_model("gemini", "gemini-2.5-flash")
        latency = int((time.monotonic() - started) * 1000)
        # Light ping to Google Generative API to validate net path.
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as c:
            r = await c.get("https://generativelanguage.googleapis.com/", follow_redirects=False)
        return _result("emergent", True, True, r.status_code in (200, 301, 302, 404),
                       latency, secret, source,
                       error=None,
                       model_reachable=True)
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("emergent", False, False, False, latency, secret, source,
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


# ---- fal.ai (Kling) -------------------------------------------------------
async def test_fal() -> dict:
    secret, source = await get_secret_with_source("FAL_KEY")
    if not secret:
        return _result("fal", False, False, False, 0, None, "missing",
                       "FAL_KEY not configured")
    started = time.monotonic()
    try:
        # Lightweight reachability — fal.ai exposes a status endpoint.
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get("https://fal.run/status",
                             headers={"Authorization": f"Key {secret}"})
        latency = int((time.monotonic() - started) * 1000)
        # 200/204/401/403 all confirm reachability; only auth_failure fails auth_ok.
        if r.status_code in (200, 204):
            return _result("fal", True, True, True, latency, secret, source,
                           model_reachable=True)
        if r.status_code in (401, 403):
            return _result("fal", False, False, True, latency, secret, source,
                           f"auth failed: HTTP {r.status_code}")
        # Some endpoints return 404 for /status — try the queue base instead.
        if r.status_code == 404:
            async with httpx.AsyncClient(timeout=TIMEOUT) as c:
                r2 = await c.get("https://queue.fal.run/",
                                  headers={"Authorization": f"Key {secret}"})
            latency = int((time.monotonic() - started) * 1000)
            if r2.status_code in (200, 204, 401, 403, 404):
                return _result("fal", r2.status_code not in (401, 403),
                                r2.status_code not in (401, 403),
                                True, latency, secret, source,
                                model_reachable=r2.status_code in (200, 204, 404))
        return _result("fal", False, True, True, latency, secret, source,
                       f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("fal", False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


# ---- Stripe ---------------------------------------------------------------
async def test_stripe() -> dict:
    secret, source = await get_secret_with_source("STRIPE_API_KEY")
    if not secret:
        return _result("stripe", False, False, False, 0, None, "missing",
                       "STRIPE_API_KEY not configured")
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as c:
            r = await c.get("https://api.stripe.com/v1/balance",
                             headers={"Authorization": f"Bearer {secret}"})
        latency = int((time.monotonic() - started) * 1000)
        if r.status_code == 200:
            return _result("stripe", True, True, True, latency, secret, source,
                           model_reachable=True)
        if r.status_code in (401, 403):
            return _result("stripe", False, False, True, latency, secret, source,
                           f"auth failed: HTTP {r.status_code}")
        return _result("stripe", False, True, True, latency, secret, source,
                       f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        latency = int((time.monotonic() - started) * 1000)
        return _result("stripe", False, False, False, latency, secret, source,
                       f"{type(e).__name__}: {e}")


PROVIDERS = {
    "openai":            test_openai,
    "emergent":          test_emergent_llm,
    "elevenlabs":        test_elevenlabs,
    "elevenlabs_music":  test_elevenlabs_music,
    "fal":               test_fal,
    "stripe":            test_stripe,
}


async def test_provider(provider: str) -> dict:
    fn = PROVIDERS.get(provider)
    if not fn:
        return {"provider": provider, "ok": False, "error": "unknown_provider"}
    return await fn()


async def test_all_providers() -> list[dict]:
    return list(await asyncio.gather(*(fn() for fn in PROVIDERS.values())))
