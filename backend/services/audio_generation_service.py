"""Audio generation service — Phase K (TTS adapter).

Thin compatibility wrapper over `services.tts_service`. Existing callers
(`generation_orchestrator`) keep importing `generate_audio` /
`estimate_duration_seconds` unchanged; the real provider work happens in
`tts_service.generate_tts(...)`.

Provider selection rule (decided in tts_service):
  * read `model_registry` row for `narration_generation`
  * if provider is `elevenlabs` AND ELEVENLABS_API_KEY resolves → real call
  * otherwise → mock (no audio bytes; metadata + duration only).

This module never raises — failures degrade to mock so the pipeline stays alive.
"""
from __future__ import annotations

import logging

from services.tts_service import (
    generate_tts,
    estimate_duration_seconds,            # re-exported for legacy import path
    narration_real_call_available,        # re-exported for stage control UI
)

logger = logging.getLogger("audio_generation_service")

__all__ = [
    "generate_audio",
    "estimate_duration_seconds",
    "narration_real_call_available",
]


async def generate_audio(
    text: str,
    voice: str | None = None,
    language: str = "ar",
) -> tuple[bytes | None, str, dict]:
    """Provider-abstracted entry point used by the live orchestrator.

    Returns (audio_bytes|None, mime_type, meta_dict). When the resolved
    provider can't actually produce audio (mock OR real-call failed),
    `audio_bytes` is None and the meta makes the situation explicit.
    """
    return await generate_tts(text=text, voice=voice, language=language)
