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
  3. A real provider that fails (no key, no credits, bad request, timeout)
     raises services.ai.AIError. It never silently degrades to mock: a
     story "with narration" must not be delivered without audio. Only an
     explicitly configured `mock` provider returns no bytes.

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

import asyncio
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
DEFAULT_ELEVENLABS_VOICE = "fkqevZRU7Xj52dY1CTkq"     # Phase N — Arabic-friendly default voice (direct API)

# fal's ElevenLabs endpoint takes premade voice *names*. Keys are the
# narrator options parents pick in step 5 (story_options kind=voice).
FAL_VOICE_BY_OPTION = {"girl": "Matilda", "boy": "Will"}
FAL_DEFAULT_VOICE = "Matilda"

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
    """fal.ai-hosted ElevenLabs TTS (narration), key FAL_KEY_NARRATION.

    `voice` is a fal voice name (see FAL_VOICE_BY_OPTION); anything else
    (e.g. an Arabic label) falls back to FAL_DEFAULT_VOICE. Raises AIError.
    """
    from services.ai import fal

    slug = model_id or "fal-ai/elevenlabs/tts/multilingual-v2"
    voice_name = voice if voice in FAL_VOICE_BY_OPTION.values() else FAL_DEFAULT_VOICE
    settings = {**_default_voice_settings(), **(voice_settings or {})}
    arguments = {
        "text": (text or "")[:2500],
        "voice": voice_name,
        "stability": settings.get("stability"),
        "similarity_boost": settings.get("similarity_boost"),
        "style": settings.get("style"),
        "speed": settings.get("speed"),
        "language_code": "ar" if (language or "ar").startswith("ar") or "عرب" in (language or "") else None,
    }
    arguments = {k: v for k, v in arguments.items() if v is not None}
    started = time.monotonic()
    result = await fal.run(stage="narration_generation", env_key="FAL_KEY_NARRATION",
                           model=slug, arguments=arguments, timeout=240.0, poll_interval=2.0)
    audio_url = (result.get("audio") or {}).get("url")
    if not audio_url:
        from services.ai import AIError
        raise AIError("fal narration returned no audio")
    audio = await fal.download(audio_url)
    return audio, (result.get("audio") or {}).get("content_type") or "audio/mpeg", {
        "provider":         "fal_tts",
        "model":            slug,
        "voice":            voice_name,
        "language":         language,
        "voice_settings":   settings,
        "duration_seconds": estimate_duration_seconds(text),
        "bytes":            len(audio),
        "latency_ms":       int((time.monotonic() - started) * 1000),
        "env_key":          "FAL_KEY_NARRATION",
        "fallback_to_mock": False,
        "real_call":        True,
        "error":            None,
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
# ---------------------------------------------------------------------------
# Gemini TTS — natural native-dialect narration steered by a direction prompt.
# ---------------------------------------------------------------------------
# Tried in order when a model is rate limited / unavailable (free-tier quotas
# are per model). Voice names are shared across these models.
GEMINI_TTS_MODELS = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview", "gemini-2.5-flash-preview-tts"]
GEMINI_TTS_RATE = 24000  # Gemini returns 16-bit mono PCM at 24 kHz


def _pcm_to_wav(pcm: bytes, rate: int = GEMINI_TTS_RATE) -> bytes:
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


async def synthesize_gemini(text: str, voice: str, direction: str, model: Optional[str] = None) -> tuple[bytes, dict]:
    """One Gemini TTS take of `text` read as `direction` asks. Returns (wav_bytes, meta).
    Raises services.ai.AIError when every model fails."""
    from google import genai
    from google.genai import types
    from services.ai import AIError, classify_http_error, require_key

    client = genai.Client(api_key=await require_key("GEMINI_API_KEY"))
    models = [model] + [m for m in GEMINI_TTS_MODELS if m != model] if model else list(GEMINI_TTS_MODELS)
    # Two passes: per-minute limits clear quickly, so wait once before giving up.
    attempts = [(m, 0) for m in models] + [(models[0], 35)] + [(m, 0) for m in models[1:]]
    last_error = None
    for m, wait_s in attempts:
        if wait_s:
            logger.warning(f"[tts.gemini] every model rate limited; waiting {wait_s}s before one more pass")
            await asyncio.sleep(wait_s)
        started = time.monotonic()
        try:
            resp = await client.aio.models.generate_content(
                model=m,
                contents=f"{direction}\n{text}",
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
                ),
            )
            parts = resp.candidates[0].content.parts if resp.candidates and resp.candidates[0].content else []
            audio = next((p.inline_data.data for p in parts if p.inline_data and p.inline_data.data), None)
            if not audio:
                raise AIError(f"Gemini TTS returned no audio (model {m})")
            return _pcm_to_wav(audio), {
                "provider": "gemini_tts", "model": m, "voice": voice,
                "latency_ms": int((time.monotonic() - started) * 1000), "real_call": True,
            }
        except genai.errors.APIError as e:
            last_error = classify_http_error("narration", "gemini", e.code, str(e))
            # Rate limits / unknown model are per model: try the next one.
            if e.code in (404, 429) or (e.code or 0) >= 500:
                logger.warning(f"[tts.gemini] {m} unavailable ({e.code}); trying next model")
                continue
            raise last_error from e
    raise last_error or AIError("Gemini TTS: no model available")


async def _tts_via_gemini(text, voice, language, model_id, voice_settings):
    """Generic entry (Stage Lab / single lines): MSA storyteller unless told otherwise."""
    from services.house_style import DIALECTS, DEFAULT_DIALECT

    dialect = DIALECTS[DEFAULT_DIALECT]
    voice = voice if voice and voice not in FAL_VOICE_BY_OPTION.values() else dialect["voices"]["male"]
    audio, meta = await synthesize_gemini(text, voice, dialect["tts_direction"], model_id)
    return audio, "audio/wav", {**meta, "language": language, "error": None, "fallback_to_mock": False}


PROVIDERS = {
    "gemini_tts": _tts_via_gemini,
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
    if provider not in PROVIDERS:
        from services.ai import AIConfigError
        raise AIConfigError(f"No narration executor for provider '{provider}'")
    return provider, model_name


async def narration_voice_for_order(order: dict) -> str:
    """fal voice name for an order: the parent's narrator choice (boy/girl),
    or — for "auto"/none — a voice matching the child's gender."""
    from db import db

    data = order.get("data") or {}
    option_id = (data.get("style") or {}).get("voice_id")
    option = await db.story_options.find_one({"id": option_id}, {"_id": 0, "value": 1}) if option_id else None
    value = (option or {}).get("value")
    if value not in FAL_VOICE_BY_OPTION:
        value = "boy" if (data.get("child") or {}).get("gender") == "male" else "girl"
    return FAL_VOICE_BY_OPTION[value]


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

    # A real provider that produced no audio is a failure, not a mock success.
    if audio is None and provider != "mock":
        from services.ai import AIError
        raise AIError(f"narration via {provider} produced no audio: {meta.get('error')}")
    return audio, mime, meta


async def narration_real_call_available() -> bool:
    """True if the configured narration provider has credentials."""
    provider, _ = await _resolve_narration_provider()
    if provider == "gemini_tts":
        secret, _src = await get_secret_with_source("GEMINI_API_KEY")
        return bool(secret)
    if provider == "elevenlabs":
        secret, _src = await get_secret_with_source("ELEVENLABS_API_KEY")
        return bool(secret)
    if provider == "fal_tts":
        secret, _src = await _get_fal_key_for_narration()
        return bool(secret)
    if provider == "openai":
        return False
    return False
