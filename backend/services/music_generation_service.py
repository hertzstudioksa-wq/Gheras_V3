"""Music Generation Service — Phase M.

Provider-adapter for music/background-audio generation. ElevenLabs Music
(`/v1/music`) is the primary provider. Suno + AudioCraft slots reserved.

Honest behaviour:
  * `audio_background_mode == "none"`  → never call this service.
  * `audio_background_mode == "music"` → cinematic instrumental prompt.
  * `audio_background_mode == "human_rhythm"` → vocal-percussion biased prompt.
    There is NO native ElevenLabs flag for "no instruments"; we bias the
    prompt and label the implementation honestly in meta.
  * Missing key OR plan-blocked (HTTP 403)  → graceful skip, NOT failure.

Resolution rules (matches tts_service / video_generation_service):
  1. Provider/model resolved from `model_registry` row for `music_generation`.
  2. ELEVENLABS_API_KEY resolved via secret_overrides_service.
  3. We NEVER raise — failure paths return None bytes + meta.skip_reason.

Public API:
    music_real_call_available()    -> bool   (key present AND we don't yet know plan is blocked)
    generate_music(audio_background_mode, prompt, duration_seconds=None)
        -> (audio_bytes|None, mime, meta)
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

import httpx

from services.secret_overrides_service import get_secret_with_source
from services.config_service import resolve_model

logger = logging.getLogger("music_generation_service")

DEFAULT_ELEVENLABS_MUSIC_MODEL = "fal-ai/elevenlabs/music"
ELEVENLABS_MUSIC_URL = "https://api.elevenlabs.io/v1/music"
DEFAULT_DURATION_SEC = 60
MAX_DURATION_SEC = 300       # ElevenLabs cap
MUSIC_TIMEOUT = httpx.Timeout(180.0, connect=15.0)


def _clip_duration(seconds: int | float | None) -> int:
    """Normalise duration to a sane [10..300] range."""
    if not seconds:
        return DEFAULT_DURATION_SEC
    try:
        v = int(seconds)
    except Exception:  # noqa: BLE001
        v = DEFAULT_DURATION_SEC
    return max(10, min(MAX_DURATION_SEC, v))


def build_music_prompt(
    audio_background_mode: str,
    base_prompt: str | None,
    story_keywords: list[str] | None = None,
    emotional_arc: str | None = None,
) -> tuple[str, str]:
    """Produce a (prompt, mode_implementation_label) pair.

    `mode_implementation_label` documents how faithfully the requested mode
    is being honored, e.g. 'native_music' vs 'prompt_biased_no_native_support'.
    """
    base = (base_prompt or "").strip()
    keywords = ", ".join((story_keywords or [])[:5])

    if audio_background_mode == "human_rhythm":
        body = (
            "Background audio for a children's story video. "
            "ONLY human-vocal percussion: hand claps, mouth-percussion, soft beatbox, "
            "gentle finger snaps, layered humming. "
            "NO instruments, NO synth, NO orchestra, NO drums machines. "
            "Warm, child-safe, family-friendly, gentle pulse, light tempo (~80 BPM). "
            f"{('Themes: ' + keywords + '. ') if keywords else ''}"
            f"{('Emotional arc: ' + emotional_arc + '. ') if emotional_arc else ''}"
            f"{base}"
        )
        return body, "prompt_biased_no_native_support"

    # default: music
    body = (
        "Cinematic instrumental score for a children's storybook. "
        "Warm, gentle, family-friendly, hopeful. "
        "Soft piano, light strings, optional warm woodwinds. "
        "NO vocals, NO lyrics, NO scary or intense passages, "
        "low-mid dynamic range so narration sits above the music in the mix. "
        f"{('Themes: ' + keywords + '. ') if keywords else ''}"
        f"{('Emotional arc: ' + emotional_arc + '. ') if emotional_arc else ''}"
        f"{base}"
    )
    return body, "native_music"


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------
async def _music_via_elevenlabs(
    prompt: str,
    duration_seconds: int,
    model_id: Optional[str],
) -> tuple[bytes | None, str, dict]:
    secret, source = await get_secret_with_source("ELEVENLABS_API_KEY")
    if not secret:
        return None, "audio/mpeg", {
            "provider":     "elevenlabs",
            "model":        model_id or DEFAULT_ELEVENLABS_MUSIC_MODEL,
            "secret_source": "missing",
            "real_call":    False,
            "skip_reason":  "missing_key",
            "duration_seconds": duration_seconds,
            "error":        "ELEVENLABS_API_KEY not configured",
        }

    payload = {
        "prompt":          prompt[:1500],
        "music_length_ms": duration_seconds * 1000,
        "output_format":   "mp3_44100_128",
    }
    headers = {
        "xi-api-key":   secret,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=MUSIC_TIMEOUT) as c:
            r = await c.post(ELEVENLABS_MUSIC_URL, headers=headers, json=payload)
        latency_ms = int((time.monotonic() - started) * 1000)
        if r.status_code == 200 and r.content:
            return r.content, "audio/mpeg", {
                "provider":         "elevenlabs",
                "model":            model_id or DEFAULT_ELEVENLABS_MUSIC_MODEL,
                "secret_source":    source,
                "real_call":        True,
                "duration_seconds": duration_seconds,
                "bytes":            len(r.content),
                "latency_ms":       latency_ms,
                "skip_reason":      None,
                "error":            None,
            }
        # HTTP 401 → bad key. 403 → plan blocked. Both produce honest skip.
        if r.status_code in (401, 403):
            try:
                err_detail = r.json().get("detail") or r.text[:200]
            except Exception:  # noqa: BLE001
                err_detail = r.text[:200]
            return None, "audio/mpeg", {
                "provider":         "elevenlabs",
                "model":            model_id or DEFAULT_ELEVENLABS_MUSIC_MODEL,
                "secret_source":    source,
                "real_call":        False,
                "duration_seconds": duration_seconds,
                "latency_ms":       latency_ms,
                "skip_reason":      "plan_required" if r.status_code == 403 else "auth_failed",
                "error":            f"HTTP {r.status_code}: {err_detail}",
            }
        # Any other non-200 → generic provider failure (NOT plan).
        try:
            err_detail = r.json()
        except Exception:  # noqa: BLE001
            err_detail = r.text[:300]
        return None, "audio/mpeg", {
            "provider":         "elevenlabs",
            "model":            model_id or DEFAULT_ELEVENLABS_MUSIC_MODEL,
            "secret_source":    source,
            "real_call":        False,
            "duration_seconds": duration_seconds,
            "latency_ms":       latency_ms,
            "skip_reason":      "provider_unavailable",
            "error":            f"HTTP {r.status_code}: {err_detail}",
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[music] elevenlabs failed: {type(e).__name__}: {e}")
        return None, "audio/mpeg", {
            "provider":         "elevenlabs",
            "model":            model_id or DEFAULT_ELEVENLABS_MUSIC_MODEL,
            "secret_source":    source,
            "real_call":        False,
            "duration_seconds": duration_seconds,
            "skip_reason":      "provider_unavailable",
            "error":            f"{type(e).__name__}: {e}",
        }


async def _get_fal_key_for_music() -> tuple[str | None, str]:
    """Phase N — prefer FAL_KEY_MUSIC, fall back to legacy FAL_KEY."""
    secret, source = await get_secret_with_source("FAL_KEY_MUSIC")
    if secret:
        return secret, source
    return await get_secret_with_source("FAL_KEY")


async def _music_via_fal_elevenlabs(
    prompt: str,
    duration_seconds: int,
    model_id: Optional[str],
) -> tuple[bytes | None, str, dict]:
    """Phase N — fal.ai-hosted ElevenLabs Music (bypasses Creator+ plan gate).

    Endpoint: fal.ai queue `fal-ai/elevenlabs/music` (submit → poll → download).
    """
    secret, source = await _get_fal_key_for_music()
    if not secret:
        return None, "audio/mpeg", {
            "provider":         "fal_music",
            "model":             model_id or "fal-ai/elevenlabs/music",
            "secret_source":     "missing",
            "env_key":           "FAL_KEY_MUSIC",
            "real_call":         False,
            "duration_seconds":  duration_seconds,
            "skip_reason":       "missing_key",
            "error":             "FAL_KEY_MUSIC (or legacy FAL_KEY) not configured",
        }
    slug = model_id or "fal-ai/elevenlabs/music"
    url = f"https://queue.fal.run/{slug}"
    payload = {
        "prompt":          prompt[:1500],
        "music_length_ms": duration_seconds * 1000,
        "output_format":   "mp3_44100_128",
    }
    headers = {"Authorization": f"Key {secret}", "Content-Type": "application/json"}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=MUSIC_TIMEOUT) as c:
            r = await c.post(url, headers=headers, json=payload)
        latency_ms = int((time.monotonic() - started) * 1000)
        if r.status_code in (200, 201, 202):
            data = r.json()
            req_id = data.get("request_id") or data.get("id")
            # Poll until done (max 180s).
            import asyncio as _asyncio
            for _ in range(60):
                await _asyncio.sleep(3)
                async with httpx.AsyncClient(timeout=MUSIC_TIMEOUT) as c:
                    pr = await c.get(
                        f"https://queue.fal.run/{slug}/requests/{req_id}",
                        headers={"Authorization": f"Key {secret}"},
                    )
                if pr.status_code != 200:
                    continue
                pd = pr.json()
                audio_url = (pd.get("audio") or {}).get("url") or (pd.get("audio_url") or None)
                if audio_url:
                    async with httpx.AsyncClient(timeout=MUSIC_TIMEOUT) as c:
                        ar = await c.get(audio_url)
                    if ar.status_code == 200:
                        return ar.content, "audio/mpeg", {
                            "provider":         "fal_music",
                            "model":            slug,
                            "secret_source":    source,
                            "env_key":          "FAL_KEY_MUSIC",
                            "real_call":        True,
                            "duration_seconds": duration_seconds,
                            "bytes":            len(ar.content),
                            "latency_ms":       latency_ms,
                            "skip_reason":      None,
                            "error":            None,
                        }
            return None, "audio/mpeg", {
                "provider":         "fal_music",
                "model":            slug,
                "secret_source":    source,
                "env_key":          "FAL_KEY_MUSIC",
                "real_call":        False,
                "duration_seconds": duration_seconds,
                "skip_reason":      "poll_timeout",
                "error":            "poll_timeout",
            }
        if r.status_code in (401, 403):
            return None, "audio/mpeg", {
                "provider":         "fal_music",
                "model":            slug,
                "secret_source":    source,
                "env_key":          "FAL_KEY_MUSIC",
                "real_call":        False,
                "duration_seconds": duration_seconds,
                "skip_reason":      "auth_failed",
                "error":            f"HTTP {r.status_code}",
            }
        return None, "audio/mpeg", {
            "provider":         "fal_music",
            "model":            slug,
            "secret_source":    source,
            "env_key":          "FAL_KEY_MUSIC",
            "real_call":        False,
            "duration_seconds": duration_seconds,
            "skip_reason":      "provider_unavailable",
            "error":            f"HTTP {r.status_code}: {r.text[:200]}",
        }
    except Exception as e:  # noqa: BLE001
        return None, "audio/mpeg", {
            "provider":         "fal_music",
            "model":            slug,
            "secret_source":    source,
            "env_key":          "FAL_KEY_MUSIC",
            "real_call":        False,
            "duration_seconds": duration_seconds,
            "skip_reason":      "provider_unavailable",
            "error":            f"{type(e).__name__}: {e}",
        }


async def _music_via_suno(prompt: str, duration_seconds: int, model_id: Optional[str]) -> tuple[bytes | None, str, dict]:
    return None, "audio/mpeg", {
        "provider":         "suno",
        "model":            model_id or "suno-v3",
        "secret_source":    "n/a",
        "real_call":        False,
        "duration_seconds": duration_seconds,
        "skip_reason":      "provider_not_yet_wired",
        "error":            "suno_not_yet_wired",
    }


async def _music_via_mock(prompt: str, duration_seconds: int, model_id: Optional[str]) -> tuple[bytes | None, str, dict]:
    return None, "audio/mpeg", {
        "provider":         "mock",
        "model":            model_id or "mock-music-v1",
        "secret_source":    "n/a",
        "real_call":        False,
        "duration_seconds": duration_seconds,
        "skip_reason":      "mock_provider",
        "error":            None,
        "note":             "Music is mocked — no audio bytes produced.",
    }


PROVIDERS = {
    "elevenlabs": _music_via_elevenlabs,
    "fal_music":  _music_via_fal_elevenlabs,
    "suno":       _music_via_suno,
    "mock":       _music_via_mock,
}


async def _resolve_music_provider() -> tuple[str, str]:
    provider, model_name, _src = await resolve_model(
        "music_generation", "fal_music", "fal-ai/elevenlabs/music",
    )
    if provider not in PROVIDERS:
        provider = "mock"
    return provider, (model_name or "fal-ai/elevenlabs/music")


async def music_real_call_available() -> bool:
    """True if the configured music provider has credentials."""
    provider, _ = await _resolve_music_provider()
    if provider == "elevenlabs":
        secret, _ = await get_secret_with_source("ELEVENLABS_API_KEY")
        return bool(secret)
    if provider == "fal_music":
        secret, _ = await _get_fal_key_for_music()
        return bool(secret)
    return False


async def generate_music(
    audio_background_mode: str,
    base_prompt: Optional[str] = None,
    duration_seconds: Optional[int] = None,
    story_keywords: Optional[list[str]] = None,
    emotional_arc: Optional[str] = None,
    provider_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> tuple[bytes | None, str, dict[str, Any]]:
    """Provider-abstracted music generation.

    `audio_background_mode == 'none'` is rejected here — callers MUST gate.
    """
    if audio_background_mode == "none":
        return None, "audio/mpeg", {
            "provider":             "skipped",
            "real_call":            False,
            "audio_background_mode": "none",
            "duration_seconds":     0,
            "skip_reason":          "mode_none",
            "mode_implementation":  "skipped_by_request",
        }

    duration = _clip_duration(duration_seconds)
    prompt, mode_impl = build_music_prompt(
        audio_background_mode, base_prompt, story_keywords, emotional_arc,
    )

    if provider_override and provider_override in PROVIDERS:
        provider = provider_override
        model_id = model_override
    else:
        provider, resolved_model = await _resolve_music_provider()
        model_id = model_override or resolved_model

    fn = PROVIDERS.get(provider, _music_via_mock)
    audio, mime, meta = await fn(prompt, duration, model_id)
    meta["audio_background_mode"] = audio_background_mode
    meta["mode_implementation"]   = mode_impl
    meta["prompt_used"]           = prompt
    return audio, mime, meta
