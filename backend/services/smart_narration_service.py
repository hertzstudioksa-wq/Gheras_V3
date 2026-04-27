"""Smart Narration — Phase N.

Analyzes a scene (narration text + emotional_tone + audio_background_mode)
via a cheap LLM call and returns dynamic voice settings for the TTS layer:
    {speed, stability, similarity_boost, style}

Design rules:
  * NEVER blocks or fails the pipeline. Any LLM/JSON error → returns the
    deterministic heuristic output. Caller always gets a usable dict.
  * Uses the EMERGENT_LLM_KEY (universal key) via emergentintegrations.
    Default model: `gpt-5-mini` (closest match to user-requested "gpt-5.2-mini"
    from the official available_models list).
  * Output values are clamped to safe ranges that the fal.ai ElevenLabs TTS
    wrapper accepts:
        speed            ∈ [0.85, 1.15]
        stability        ∈ [0.20, 0.80]
        similarity_boost ∈ [0.50, 0.95]
        style            ∈ [0.00, 0.40]
  * Every call records its `source` ("llm" | "heuristic" | "disabled" |
    "llm_failed") and `reason` for storyboard / lab transparency.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from services.secret_overrides_service import get_secret_with_source

logger = logging.getLogger("smart_narration")

# ---------------------------------------------------------------------------
DEFAULT_SMART_MODEL_PROVIDER = "openai"
DEFAULT_SMART_MODEL_NAME     = "gpt-5-mini"

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
_LLM_SYSTEM = (
    "You are an expert voice director for Arabic children's storytelling. "
    "Given a scene's narration text, emotional tone, and audio background mode, "
    "output ONLY a strict JSON object with these keys: "
    "speed (0.85..1.15), stability (0.2..0.8), similarity_boost (0.5..0.95), style (0.0..0.4). "
    "No prose, no comments, no markdown. Values are floats."
)


def _strip_to_json(text: str) -> str | None:
    """Extract the first `{...}` block from a possibly noisy LLM response."""
    if not text:
        return None
    m = re.search(r"\{[^{}]*\}", text, flags=re.DOTALL)
    return m.group(0) if m else None


async def _llm_compute(
    narration_text: str,
    emotional_tone: str | None,
    audio_background_mode: str | None,
    scene_index: int | None,
    duration_label: str | None,
) -> tuple[dict | None, str]:
    """Call EMERGENT_LLM_KEY via emergentintegrations. Returns (settings, reason).

    Returns (None, reason) when unavailable or JSON parse fails so the caller
    can gracefully fall back to heuristics.
    """
    secret, _src = await get_secret_with_source("EMERGENT_LLM_KEY")
    if not secret:
        return None, "missing_emergent_llm_key"

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage
    except Exception as e:  # noqa: BLE001
        return None, f"sdk_import_error:{type(e).__name__}"

    provider = os.environ.get("SMART_NARRATION_PROVIDER", DEFAULT_SMART_MODEL_PROVIDER)
    model    = os.environ.get("SMART_NARRATION_MODEL",    DEFAULT_SMART_MODEL_NAME)

    user_payload = {
        "scene_index":           scene_index,
        "emotional_tone":        emotional_tone or "neutral",
        "audio_background_mode": audio_background_mode or "music",
        "duration_label":        duration_label or "",
        "narration_text":        (narration_text or "")[:800],
    }

    prompt = (
        "Return ONLY JSON with keys speed, stability, similarity_boost, style. "
        "Scene payload:\n"
        f"{json.dumps(user_payload, ensure_ascii=False)}"
    )

    try:
        chat = LlmChat(
            api_key=secret,
            session_id=f"smart-narration-{scene_index or 0}",
            system_message=_LLM_SYSTEM,
        ).with_model(provider, model)
        reply = await chat.send_message(UserMessage(text=prompt))
    except Exception as e:  # noqa: BLE001
        return None, f"llm_error:{type(e).__name__}"

    raw = reply if isinstance(reply, str) else getattr(reply, "text", "") or str(reply)
    block = _strip_to_json(raw)
    if not block:
        return None, "no_json_in_reply"

    try:
        data = json.loads(block)
    except Exception:  # noqa: BLE001
        return None, "invalid_json"

    if not isinstance(data, dict):
        return None, "reply_not_object"

    result = {
        "speed":             _clamp("speed",            data.get("speed", 1.0)),
        "stability":         _clamp("stability",        data.get("stability", 0.55)),
        "similarity_boost":  _clamp("similarity_boost", data.get("similarity_boost", 0.80)),
        "style":             _clamp("style",            data.get("style", 0.05)),
    }
    return result, "ok"


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

    if not use_llm:
        return {**heur, "source": "disabled", "reason": "use_llm=False", "model": None}

    llm_out, reason = await _llm_compute(
        narration_text, emotional_tone, audio_background_mode,
        scene_index, duration_label,
    )
    if llm_out:
        return {
            **llm_out,
            "source": "llm",
            "reason": reason,
            "model":  f"{os.environ.get('SMART_NARRATION_PROVIDER', DEFAULT_SMART_MODEL_PROVIDER)}/"
                       f"{os.environ.get('SMART_NARRATION_MODEL',    DEFAULT_SMART_MODEL_NAME)}",
        }

    return {
        **heur,
        "source": "llm_failed" if reason not in ("missing_emergent_llm_key",) else "heuristic",
        "reason": reason,
        "model":  None,
    }
