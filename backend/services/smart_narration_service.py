"""Smart Narration — Phase N.

Analyzes a scene (narration text + emotional_tone + audio_background_mode)
and returns voice settings for the TTS layer:
    {speed, stability, similarity_boost, style}

Design rules:
  * NEVER blocks or fails the pipeline; the caller always gets a usable dict.
  * Settings come from a deterministic heuristic (no API call).
  * Output values are clamped to safe ranges that the fal.ai ElevenLabs TTS
    wrapper accepts:
        speed            ∈ [0.85, 1.15]
        stability        ∈ [0.20, 0.80]
        similarity_boost ∈ [0.50, 0.95]
        style            ∈ [0.00, 0.40]
  * Every call records its `source` ("heuristic" | "disabled") and `reason`
    for storyboard / lab transparency.
"""
from __future__ import annotations

import logging
from typing import Any


logger = logging.getLogger("smart_narration")

# ---------------------------------------------------------------------------

# Clamp ranges (safe for fal.ai / ElevenLabs multilingual v2).
_CLAMP = {
    "speed":            (0.85, 1.15),
    "stability":        (0.20, 0.80),
    "similarity_boost": (0.50, 0.95),
    "style":            (0.00, 0.40),
}


def _clamp(key: str, value: Any) -> float:
    lo, hi = _CLAMP[key]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return (lo + hi) / 2.0
    return max(lo, min(hi, round(v, 3)))


def default_voice_settings() -> dict:
    """Neutral, studio-safe defaults — identical to tts_service baseline."""
    return {
        "speed":             1.00,
        "stability":         0.55,
        "similarity_boost":  0.80,
        "style":             0.05,
    }


# ---------------------------------------------------------------------------
# Deterministic heuristic — always available, no API cost.
# ---------------------------------------------------------------------------
_TONE_TABLE = {
    # emotional_tone (Arabic or English) → knobs
    "calm":         {"speed": 0.95, "stability": 0.70, "similarity_boost": 0.85, "style": 0.05},
    "هادئ":         {"speed": 0.95, "stability": 0.70, "similarity_boost": 0.85, "style": 0.05},
    "warm":         {"speed": 0.98, "stability": 0.65, "similarity_boost": 0.85, "style": 0.10},
    "دافئ":         {"speed": 0.98, "stability": 0.65, "similarity_boost": 0.85, "style": 0.10},
    "happy":        {"speed": 1.05, "stability": 0.50, "similarity_boost": 0.80, "style": 0.20},
    "سعيد":         {"speed": 1.05, "stability": 0.50, "similarity_boost": 0.80, "style": 0.20},
    "excited":      {"speed": 1.10, "stability": 0.40, "similarity_boost": 0.75, "style": 0.30},
    "متحمّس":        {"speed": 1.10, "stability": 0.40, "similarity_boost": 0.75, "style": 0.30},
    "curious":      {"speed": 1.02, "stability": 0.55, "similarity_boost": 0.80, "style": 0.15},
    "فضولي":        {"speed": 1.02, "stability": 0.55, "similarity_boost": 0.80, "style": 0.15},
    "sad":          {"speed": 0.90, "stability": 0.70, "similarity_boost": 0.85, "style": 0.10},
    "حزين":         {"speed": 0.90, "stability": 0.70, "similarity_boost": 0.85, "style": 0.10},
    "tense":        {"speed": 1.05, "stability": 0.45, "similarity_boost": 0.80, "style": 0.25},
    "متوتر":        {"speed": 1.05, "stability": 0.45, "similarity_boost": 0.80, "style": 0.25},
    "resolved":     {"speed": 0.95, "stability": 0.70, "similarity_boost": 0.90, "style": 0.10},
    "خاتمة":        {"speed": 0.95, "stability": 0.70, "similarity_boost": 0.90, "style": 0.10},
    "reflective":   {"speed": 0.92, "stability": 0.72, "similarity_boost": 0.88, "style": 0.08},
    "تأملي":        {"speed": 0.92, "stability": 0.72, "similarity_boost": 0.88, "style": 0.08},
    "mysterious":   {"speed": 0.93, "stability": 0.60, "similarity_boost": 0.82, "style": 0.20},
    "غامض":         {"speed": 0.93, "stability": 0.60, "similarity_boost": 0.82, "style": 0.20},
}


def heuristic_settings(
    narration_text: str,
    emotional_tone: str | None,
    audio_background_mode: str | None,
) -> dict:
    base = default_voice_settings()
    tone = (emotional_tone or "").strip().lower()
    if tone in _TONE_TABLE:
        base.update(_TONE_TABLE[tone])

    # Long narrations → slightly slow down and bump stability for clarity.
    words = [w for w in (narration_text or "").split() if w.strip()]
    if len(words) >= 50:
        base["speed"]     = min(base["speed"] - 0.03, 1.10)
        base["stability"] = min(base["stability"] + 0.05, 0.80)

    # 'music' background masks the voice slightly → bump similarity a touch.
    if (audio_background_mode or "music") == "music":
        base["similarity_boost"] = min(base["similarity_boost"] + 0.02, 0.95)
    elif audio_background_mode == "none":
        # No music → speak a touch slower for presence.
        base["speed"] = max(base["speed"] - 0.02, 0.85)

    return {k: _clamp(k, v) for k, v in base.items()}


# ---------------------------------------------------------------------------
# LLM layer — optional.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Public entry point.
# ---------------------------------------------------------------------------
async def compute_voice_settings(
    narration_text: str,
    emotional_tone: str | None = None,
    audio_background_mode: str | None = None,
    scene_index: int | None = None,
    duration_label: str | None = None,
    *,
    use_llm: bool = True,
) -> dict:
    """Return a settings dict suitable for tts_service.voice_settings.

    Shape:
        {
          "speed": 0.98, "stability": 0.65, "similarity_boost": 0.85, "style": 0.10,
          "source": "llm" | "heuristic" | "llm_failed" | "disabled",
          "reason": "ok" | "missing_emergent_llm_key" | "invalid_json" | ...,
          "model":  "openai/gpt-5-mini" | None,
        }
    """
    heur = heuristic_settings(narration_text, emotional_tone, audio_background_mode)
    # The per-scene LLM tuning call was removed with the Emergent proxy: it
    # added a paid call per scene for marginal gain. `use_llm` is kept so
    # existing callers (lab, orchestrator) don't change.
    return {**heur, "source": "heuristic" if use_llm else "disabled", "reason": "ok", "model": None}
