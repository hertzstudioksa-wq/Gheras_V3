"""Admin-managed configuration layer (Phase A — Foundation only).

This module provides READ access to admin-managed config:
  * model_registry      — which provider/model is active per stage
  * prompt_templates    — active prompt template per stage (+ versioning)
  * pipeline_config     — whether/which stages run, order, retries

CRITICAL design rules:
  1. Every lookup falls back to a HARDCODED default when no DB entry exists.
     This guarantees existing pipelines keep working unchanged during Phase A.
  2. Nothing here mutates existing services. Services still use their own
     hardcoded values until Phase B wires them to `get_model_for_stage(...)`.
  3. API keys are NEVER read from this module — they always come from
     `os.environ` directly in the service that uses them.
"""
import os
from typing import Any

from db import db


# --- HARDCODED DEFAULTS ------------------------------------------------------
# Used whenever the admin hasn't overridden config in the DB yet. Matches the
# existing service implementations exactly so behavior is unchanged.
DEFAULT_MODELS: dict[str, dict[str, Any]] = {
    "scenario_generation": {
        "provider": "anthropic",
        "model_name": "claude-sonnet-4-5-20250929",
        "fallback_provider": "internal",
        "fallback_model": "deterministic_fallback",
        "env_key": "EMERGENT_LLM_KEY",
    },
    "production_planning": {
        "provider": "anthropic",
        "model_name": "claude-sonnet-4-5-20250929",
        "fallback_provider": "internal",
        "fallback_model": "deterministic_fallback",
        "env_key": "EMERGENT_LLM_KEY",
    },
    "child_character_i2i": {
        "provider": "gemini",
        "model_name": "gemini-2.5-flash-image-preview",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "EMERGENT_LLM_KEY",
    },
    "scene_image_generation": {
        "provider": "gemini",
        "model_name": "gemini-2.5-flash-image-preview",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "EMERGENT_LLM_KEY",
    },
    "narration_generation": {
        "provider": "mock",
        "model_name": "mock-tts-v1",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "EMERGENT_LLM_KEY",
    },
    "video_generation": {
        "provider": "ffmpeg",
        "model_name": "local-slideshow",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": None,  # local binary, no API key
    },
    "final_assembly": {
        "provider": "ffmpeg",
        "model_name": "local-assembly",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": None,
    },
    "pdf_generation": {
        "provider": "reportlab",
        "model_name": "local-reportlab",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": None,
    },
}

STAGE_DISPLAY_NAMES = {
    "scenario_generation":   {"ar": "توليد السيناريوهات",        "en": "Scenario Generation"},
    "production_planning":   {"ar": "إعداد خطة الإنتاج",         "en": "Production Planning"},
    "child_character_i2i":   {"ar": "تحويل صورة الطفل لشخصية",   "en": "Child Character I2I"},
    "scene_image_generation":{"ar": "توليد صور المشاهد",         "en": "Scene Image Generation"},
    "narration_generation":  {"ar": "توليد السرد الصوتي",         "en": "Narration Generation"},
    "video_generation":      {"ar": "توليد الفيديو",               "en": "Video Generation"},
    "final_assembly":        {"ar": "التجميع النهائي",             "en": "Final Assembly"},
    "pdf_generation":        {"ar": "توليد الكتاب PDF",            "en": "PDF Generation"},
}

# Default pipeline ordering + flags. child_character_i2i is DISABLED by default
# in Phase A (data-only; no runtime effect) — admin must explicitly enable it
# in Phase B when the execution code lands.
DEFAULT_PIPELINE = {
    "order": [
        "scenario_generation",
        "production_planning",
        "child_character_i2i",      # placeholder — disabled
        "scene_image_generation",
        "narration_generation",
        "final_assembly",
    ],
    "stages": {
        "scenario_generation":    {"enabled": True,  "max_retries": 2, "fallback_allowed": True},
        "production_planning":    {"enabled": True,  "max_retries": 2, "fallback_allowed": True},
        "child_character_i2i":    {"enabled": False, "max_retries": 2, "fallback_allowed": False, "runs_before_scene_generation": True},
        "scene_image_generation": {"enabled": True,  "max_retries": 3, "fallback_allowed": True,  "uses_child_reference_asset": False},
        "narration_generation":   {"enabled": True,  "max_retries": 2, "fallback_allowed": True},
        "final_assembly":         {"enabled": True,  "max_retries": 2, "fallback_allowed": True},
    },
}

# Env-var mapping for admin API Status page (keys stored in .env, never in DB).
PROVIDER_ENV_MAP = {
    "anthropic":  {"env_key": "EMERGENT_LLM_KEY",  "label": "Claude (via Emergent)"},
    "gemini":     {"env_key": "EMERGENT_LLM_KEY",  "label": "Gemini / Nano Banana (via Emergent)"},
    "openai":     {"env_key": "EMERGENT_LLM_KEY",  "label": "OpenAI (via Emergent)"},
    "elevenlabs": {"env_key": "ELEVENLABS_API_KEY","label": "ElevenLabs TTS"},
    "kling":      {"env_key": "KLING_API_KEY",     "label": "Kling Video"},
    "sora":       {"env_key": "EMERGENT_LLM_KEY",  "label": "Sora 2 (via Emergent)"},
    "ffmpeg":     {"env_key": None,                 "label": "ffmpeg (local binary)"},
    "reportlab":  {"env_key": None,                 "label": "reportlab (local)"},
    "mock":       {"env_key": None,                 "label": "Mock (development)"},
    "internal":   {"env_key": None,                 "label": "Internal fallback"},
}


# --- READ HELPERS ------------------------------------------------------------
async def get_model_for_stage(stage_key: str) -> dict:
    """Return the active model config for a stage, falling back to hardcoded default.

    Services in Phase A may optionally call this. If they don't, they keep
    their existing hardcoded behavior — zero regression.
    """
    doc = await db.model_registry.find_one({"stage_key": stage_key, "active": True}, {"_id": 0})
    if doc:
        return doc
    default = DEFAULT_MODELS.get(stage_key, {}).copy()
    default["stage_key"] = stage_key
    default["active"] = True
    default["source"] = "default"
    return default


async def get_prompt_for_stage(stage_key: str) -> dict | None:
    """Return the active prompt template for a stage (or None if not configured)."""
    return await db.prompt_templates.find_one(
        {"stage_key": stage_key, "active": True}, {"_id": 0}
    )


async def get_pipeline_config() -> dict:
    """Return the current pipeline config with defaults filled in."""
    doc = await db.pipeline_config.find_one({"id": "default"}, {"_id": 0})
    if doc:
        merged = {**DEFAULT_PIPELINE, **{k: v for k, v in doc.items() if k != "id"}}
        return merged
    return {**DEFAULT_PIPELINE, "source": "default"}


def mask_secret(value: str | None) -> str:
    if not value:
        return "—"
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}••••••••{value[-4:]}"


def env_status(env_key: str | None) -> dict:
    if not env_key:
        return {"env_key": None, "configured": True, "masked": "—", "source": "local"}
    val = os.environ.get(env_key)
    return {
        "env_key": env_key,
        "configured": bool(val),
        "masked": mask_secret(val),
        "source": "env",
    }
