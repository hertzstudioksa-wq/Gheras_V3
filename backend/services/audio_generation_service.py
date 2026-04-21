"""Audio generation service — MOCK in Phase 6A (no TTS provider in Emergent LLM Key).

Contract:
  generate_audio(text, voice, language) -> (audio_bytes | None, mime_type, provider_meta)
  On mock mode, returns (None, "audio/mpeg", {...}) — the orchestrator will persist a
  metadata-only record and we compute duration_seconds from word count.

Designed so swapping in ElevenLabs / OpenAI TTS later is a single function replacement.
"""
import os
import logging

logger = logging.getLogger("audio_generation_service")

AUDIO_PROVIDER = os.environ.get("AUDIO_PROVIDER", "mock")  # 'mock' | 'elevenlabs' | 'openai'

# Arabic narration speed heuristic (slightly slower than conversational)
WORDS_PER_SECOND_AR = 2.2


def estimate_duration_seconds(text: str) -> float:
    """Estimate duration in seconds from text word count."""
    words = [w for w in (text or "").split() if w.strip()]
    if not words:
        return 0.0
    return round(len(words) / WORDS_PER_SECOND_AR, 2)


async def _generate_via_mock(text: str, voice: str | None, language: str) -> tuple[bytes | None, str, dict]:
    """Pure metadata — no audio bytes produced."""
    duration = estimate_duration_seconds(text)
    return None, "audio/mpeg", {
        "provider": "mock",
        "voice": voice or "default-ar-male",
        "language": language,
        "duration_seconds": duration,
        "note": "Audio TTS is mocked in Phase 6A. Real provider integration in Phase 6B.",
    }


async def generate_audio(
    text: str,
    voice: str | None = None,
    language: str = "ar",
) -> tuple[bytes | None, str, dict]:
    """Provider-abstracted entry point. Returns (bytes|None, mime, meta)."""
    if AUDIO_PROVIDER == "mock":
        return await _generate_via_mock(text, voice, language)
    # Future: add elif AUDIO_PROVIDER == "elevenlabs": ...
    logger.warning(f"Unknown AUDIO_PROVIDER={AUDIO_PROVIDER}, falling back to mock")
    return await _generate_via_mock(text, voice, language)
