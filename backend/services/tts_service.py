"""TTS Service — Phase K.

Provider-adapter for Text-To-Speech generation. Designed so a new provider
(OpenAI TTS, Google Cloud TTS, etc.) can be added by adding a single
`_tts_via_<provider>` async function and registering it in `PROVIDERS`.

Resolution rules (matches the rest of the platform):
  1. Provider for stage `narration_generation` is read from
     `model_registry` via `resolve_model(...)`. Default falls back to
     `mock` (current behavior).
  2. ElevenLabs API key is resolved via `secret_overrides_service.get_secret`
     so the secure encrypted override always wins over `.env`.
  3. If the chosen provider has no credentials, we degrade to mock and
     surface that fact in `meta`. We NEVER raise — the orchestrator must
     keep running.

Public entry point:
    generate_tts(text, voice=None, language="ar",
                 model_id=None, voice_settings=None,
                 provider_override=None) -> (bytes|None, mime, meta)

The meta dict is the source of truth for accountability:
    provider, model, voice, language, duration_seconds,
    secret_source ("override"|"env"|"missing"|"n/a"),
    fallback_to_mock (bool), error (str|None), real_call (bool).
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from services.secret_overrides_service import get_secret_with_source
from services.config_service import resolve_model

logger = logging.getLogger("tts_service")

# ---------------------------------------------------------------------------
# Tunables — admin-overridable via model_registry / preset stacks.
# ---------------------------------------------------------------------------
DEFAULT_ELEVENLABS_MODEL = "eleven_multilingual_v2"
DEFAULT_ELEVENLABS_VOICE = "fkqevZRU7Xj52dY1CTkq"     # Phase N — Arabic-friendly default voice

# Arabic narration speed heuristic (slightly slower than conversational).
WORDS_PER_SECOND_AR = 2.2

ELEVENLABS_TIMEOUT = httpx.Timeout(60.0, connect=10.0)


# ---------------------------------------------------------------------------
def estimate_duration_seconds(text: str) -> float:
    """Estimate duration in seconds from text word count."""
    words = [w for w in (text or "").split() if w.strip()]
    if not words:
        return 0.0
    return round(len(words) / WORDS_PER_SECOND_AR, 2)


def _default_voice_settings() -> dict:
    return {
        "stability":         0.55,
        "similarity_boost":  0.80,
        "style":             0.05,
        "use_speaker_boost": True,
    }


# ---------------------------------------------------------------------------
# ElevenLabs adapter — real-call.
# ---------------------------------------------------------------------------
async def _tts_via_elevenlabs(
    text: str,
    voice: Optional[str],
    language: str,
    model_id: Optional[str],
    voice_settings: Optional[dict],
) -> tuple[bytes | None, str, dict]:
    """Real call to ElevenLabs `/v1/text-to-speech/{voice_id}`.

    Returns (audio_bytes, "audio/mpeg", meta). On any failure returns
    (None, "audio/mpeg", meta_with_error) so the caller can fall back to mock.
    """
    secret, source = await get_secret_with_source("ELEVENLABS_API_KEY")
    if not secret:
        return None, "audio/mpeg", {
            "provider":          "elevenlabs",
            "model":             model_id or DEFAULT_ELEVENLABS_MODEL,
            "voice":             voice or DEFAULT_ELEVENLABS_VOICE,
            "language":          language,
            "duration_seconds":  estimate_duration_seconds(text),
            "secret_source":     "missing",
            "fallback_to_mock":  True,
            "real_call":         False,
            "error":             "ELEVENLABS_API_KEY not configured",
            "note":              "Add ELEVENLABS_API_KEY in /admin/secrets to enable real narration.",
        }

    voice_id = voice or DEFAULT_ELEVENLABS_VOICE
    model = model_id or DEFAULT_ELEVENLABS_MODEL
    settings = {**_default_voice_settings(), **(voice_settings or {})}

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key":   secret,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }
    payload = {
        "text":            text or "",
        "model_id":        model,
        "voice_settings":  settings,
    }

    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as client:
            r = await client.post(url, headers=headers, json=payload)
        latency_ms = int((time.monotonic() - started) * 1000)
        if r.status_code == 200 and r.content:
            return r.content, "audio/mpeg", {
                "provider":         "elevenlabs",
                "model":            model,
                "voice":            voice_id,
                "language":         language,
                "voice_settings":   settings,
                "duration_seconds": estimate_duration_seconds(text),
                "bytes":            len(r.content),
                "latency_ms":       latency_ms,
                "secret_source":    source,
                "fallback_to_mock": False,
                "real_call":        True,
                "error":            None,
            }
        # Non-200: try to extract a useful error.
        try:
            err = r.json().get("detail") or r.text[:300]
        except Exception:  # noqa: BLE001
            err = r.text[:300] if r.text else f"HTTP {r.status_code}"
        return None, "audio/mpeg", {
            "provider":         "elevenlabs",
            "model":            model,
            "voice":            voice_id,
            "language":         language,
            "duration_seconds": estimate_duration_seconds(text),
            "latency_ms":       latency_ms,
            "secret_source":    source,
            "fallback_to_mock": True,
            "real_call":        False,
            "error":            f"HTTP {r.status_code}: {err}",
        }
    except Exception as e:  # noqa: BLE001
        latency_ms = int((time.monotonic() - started) * 1000)
        logger.warning(f"[tts] elevenlabs failed: {type(e).__name__}: {e}")
        return None, "audio/mpeg", {
            "provider":         "elevenlabs",
            "model":            model,
            "voice":            voice_id,
            "language":         language,
            "duration_seconds": estimate_duration_seconds(text),
            "latency_ms":       latency_ms,
            "secret_source":    source,
            "fallback_to_mock": True,
            "real_call":        False,
            "error":            f"{type(e).__name__}: {e}",
        }


async def _get_fal_key_for_narration() -> tuple[str | None, str]:
    """Phase N — prefer FAL_KEY_NARRATION, fall back to legacy FAL_KEY."""
    secret, source = await get_secret_with_source("FAL_KEY_NARRATION")
    if secret:
        return secret, source
    return await get_secret_with_source("FAL_KEY")


async def _tts_via_fal_elevenlabs(
    text: str,
    voice: Optional[str],
    language: str,
    model_id: Optional[str],
    voice_settings: Optional[dict],
) -> tuple[bytes | None, str, dict]:
    """Phase N — fal.ai-hosted ElevenLabs TTS (narration).

    Bypasses direct ElevenLabs plan-gating entirely. Uses FAL_KEY_NARRATION.
    Endpoint: fal.ai queue `fal-ai/elevenlabs/tts/multilingual-v2`.
    """
    secret, source = await _get_fal_key_for_narration()
    if not secret:
        return None, "audio/mpeg", {
            "provider":         "fal_tts",
            "model":             model_id or "fal-ai/elevenlabs/tts/multilingual-v2",
            "voice":             voice or DEFAULT_ELEVENLABS_VOICE,
            "language":          language,
            "duration_seconds":  estimate_duration_seconds(text),
            "secret_source":     "missing",
            "env_key":           "FAL_KEY_NARRATION",
            "fallback_to_mock":  True,
            "real_call":         False,
            "error":             "FAL_KEY_NARRATION (or legacy FAL_KEY) not configured",
            "note":              "Add FAL_KEY_NARRATION in /admin/secrets to enable real narration.",
        }
    slug = model_id or "fal-ai/elevenlabs/tts/multilingual-v2"
    voice_id = voice or DEFAULT_ELEVENLABS_VOICE
    settings = {**_default_voice_settings(), **(voice_settings or {})}
    url = f"https://queue.fal.run/{slug}"
    payload = {
        "text":  (text or "")[:2500],
        "voice": voice_id,
        "stability":         settings.get("stability"),
        "similarity_boost":  settings.get("similarity_boost"),
        "style":             settings.get("style"),
        "use_speaker_boost": settings.get("use_speaker_boost"),
    }
    headers = {"Authorization": f"Key {secret}", "Content-Type": "application/json"}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as c:
            r = await c.post(url, headers=headers, json=payload)
        latency_ms = int((time.monotonic() - started) * 1000)
        if r.status_code in (200, 201, 202):
            data = r.json()
            # Submit response carries request_id. We need to poll.
            req_id = data.get("request_id") or data.get("id")
            if not req_id and data.get("audio", {}).get("url"):
                # Some fal endpoints return synchronously.
                audio_url = data["audio"]["url"]
                async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as c:
                    ar = await c.get(audio_url)
                if ar.status_code == 200:
                    return ar.content, "audio/mpeg", {
                        "provider":         "fal_tts",
                        "model":            slug,
                        "voice":            voice_id,
                        "language":         language,
                        "voice_settings":   settings,
                        "duration_seconds": estimate_duration_seconds(text),
                        "bytes":            len(ar.content),
                        "latency_ms":       latency_ms,
                        "secret_source":    source,
                        "env_key":          "FAL_KEY_NARRATION",
                        "fallback_to_mock": False,
                        "real_call":        True,
                        "error":            None,
                    }
            # Poll loop (up to 90s).
            for _ in range(30):
                await __import__("asyncio").sleep(3)
                async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as c:
                    pr = await c.get(
                        f"https://queue.fal.run/{slug}/requests/{req_id}",
                        headers={"Authorization": f"Key {secret}"},
                    )
                if pr.status_code != 200:
                    continue
                pd = pr.json()
                audio_url = (pd.get("audio") or {}).get("url")
                if audio_url:
                    async with httpx.AsyncClient(timeout=ELEVENLABS_TIMEOUT) as c:
                        ar = await c.get(audio_url)
                    if ar.status_code == 200:
                        return ar.content, "audio/mpeg", {
                            "provider":         "fal_tts",
                            "model":            slug,
                            "voice":            voice_id,
                            "language":         language,
                            "voice_settings":   settings,
                            "duration_seconds": estimate_duration_seconds(text),
                            "bytes":            len(ar.content),
                            "latency_ms":       latency_ms,
                            "secret_source":    source,
                            "env_key":          "FAL_KEY_NARRATION",
                            "fallback_to_mock": False,
                            "real_call":        True,
                            "error":            None,
                        }
            return None, "audio/mpeg", {
                "provider":         "fal_tts",
                "model":            slug,
                "secret_source":    source,
                "env_key":          "FAL_KEY_NARRATION",
                "fallback_to_mock": True,
                "real_call":        False,
                "error":            "poll_timeout",
            }
        if r.status_code in (401, 403):
            return None, "audio/mpeg", {
                "provider":         "fal_tts",
                "model":            slug,
                "secret_source":    source,
                "env_key":          "FAL_KEY_NARRATION",
                "fallback_to_mock": True,
                "real_call":        False,
                "error":            f"HTTP {r.status_code}: auth_failed",
            }
        return None, "audio/mpeg", {
            "provider":         "fal_tts",
            "model":            slug,
            "secret_source":    source,
            "env_key":          "FAL_KEY_NARRATION",
            "fallback_to_mock": True,
            "real_call":        False,
            "error":            f"HTTP {r.status_code}: {r.text[:200]}",
        }
    except Exception as e:  # noqa: BLE001
        return None, "audio/mpeg", {
            "provider":         "fal_tts",
            "model":            slug,
            "secret_source":    source,
            "env_key":          "FAL_KEY_NARRATION",
            "fallback_to_mock": True,
            "real_call":        False,
            "error":            f"{type(e).__name__}: {e}",
        }


# ---------------------------------------------------------------------------
# OpenAI TTS adapter — STUB. Wire actual call in a follow-up phase.
# Documented contract so the admin sees the same meta fields and the future
# wiring is a single function replacement.
# ---------------------------------------------------------------------------
async def _tts_via_openai(
    text: str,
    voice: Optional[str],
    language: str,
    model_id: Optional[str],
    voice_settings: Optional[dict],
) -> tuple[bytes | None, str, dict]:
    return None, "audio/mpeg", {
        "provider":         "openai",
        "model":            model_id or "tts-1",
        "voice":            voice or "alloy",
        "language":         language,
        "duration_seconds": estimate_duration_seconds(text),
        "secret_source":    "n/a",
        "fallback_to_mock": True,
        "real_call":        False,
        "error":            "openai_tts_not_yet_wired",
        "note":             "OpenAI TTS adapter is registered but not implemented yet.",
    }


# ---------------------------------------------------------------------------
# Mock — current pipeline behavior.
# ---------------------------------------------------------------------------
async def _tts_via_mock(
    text: str,
    voice: Optional[str],
    language: str,
    model_id: Optional[str],
    voice_settings: Optional[dict],
) -> tuple[bytes | None, str, dict]:
    return None, "audio/mpeg", {
        "provider":         "mock",
        "model":            model_id or "mock-tts-v1",
        "voice":            voice or "default-ar-male",
        "language":         language,
        "duration_seconds": estimate_duration_seconds(text),
        "secret_source":    "n/a",
        "fallback_to_mock": False,        # mock is the requested path
        "real_call":        False,
        "error":            None,
        "note":             "TTS is mocked — no audio bytes produced.",
    }


# ---------------------------------------------------------------------------
PROVIDERS = {
    "elevenlabs": _tts_via_elevenlabs,
    "fal_tts":    _tts_via_fal_elevenlabs,
    "openai":     _tts_via_openai,
    "mock":       _tts_via_mock,
}


async def _resolve_narration_provider() -> tuple[str, str]:
    """Resolve (provider, model_name) for `narration_generation` using the
    admin model_registry, falling back to mock defaults.
    """
    provider, model_name, _source = await resolve_model(
        "narration_generation", "mock", "mock-tts-v1",
    )
    # Normalize provider keys we recognize.
    if provider not in PROVIDERS:
        provider = "mock"
    return provider, model_name


async def generate_tts(
    text: str,
    voice: Optional[str] = None,
    language: str = "ar",
    model_id: Optional[str] = None,
    voice_settings: Optional[dict] = None,
    provider_override: Optional[str] = None,
) -> tuple[bytes | None, str, dict[str, Any]]:
    """Provider-abstracted TTS entry point.

    `provider_override` is for the admin Stage Lab — it lets a tester force
    a specific provider regardless of model_registry.
    """
    if provider_override and provider_override in PROVIDERS:
        provider = provider_override
        model_name = model_id
    else:
        provider, model_name = await _resolve_narration_provider()
        # If admin selected `elevenlabs` but model field is empty, default it.
        if provider == "elevenlabs" and not model_name:
            model_name = DEFAULT_ELEVENLABS_MODEL

    fn = PROVIDERS.get(provider, _tts_via_mock)
    audio, mime, meta = await fn(text, voice, language, model_id or model_name, voice_settings)

    # Real-call attempted but failed → fall back to mock so the pipeline
    # never hard-fails. The original error is preserved in meta for audit.
    if audio is None and meta.get("fallback_to_mock") and provider != "mock":
        m_audio, m_mime, m_meta = await _tts_via_mock(text, voice, language, model_name, voice_settings)
        m_meta["original_provider"] = provider
        m_meta["original_error"]    = meta.get("error")
        m_meta["fallback_to_mock"]  = True
        return m_audio, m_mime, m_meta
    return audio, mime, meta


async def narration_real_call_available() -> bool:
    """True if the configured narration provider has credentials."""
    provider, _ = await _resolve_narration_provider()
    if provider == "elevenlabs":
        secret, _src = await get_secret_with_source("ELEVENLABS_API_KEY")
        return bool(secret)
    if provider == "fal_tts":
        secret, _src = await _get_fal_key_for_narration()
        return bool(secret)
    if provider == "openai":
        return False
    return False
