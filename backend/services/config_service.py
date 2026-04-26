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
        "provider": "openai",
        "model_name": "gpt-image-1",
        "fallback_provider": "mock",
        "fallback_model": "dry-run",
        "env_key": "OPENAI_API_KEY",
    },
    "extra_character_i2i": {
        "provider": "openai",
        "model_name": "gpt-image-1",
        "fallback_provider": "mock",
        "fallback_model": "dry-run",
        "env_key": "OPENAI_API_KEY",
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
    "extra_character_i2i":   {"ar": "تحويل شخصيات إضافية",       "en": "Extra Characters I2I"},
    "scene_image_generation":{"ar": "توليد صور المشاهد",         "en": "Scene Image Generation"},
    "book_page_image_generation": {"ar": "إيضاحات صفحات الكتاب", "en": "Book Page Image Generation"},
    "narration_generation":  {"ar": "توليد السرد الصوتي",         "en": "Narration Generation"},
    "video_generation":      {"ar": "توليد الفيديو",               "en": "Video Generation"},
    "music_generation":      {"ar": "توليد الموسيقى",              "en": "Music Generation"},
    "video_assembly":        {"ar": "تجميع الفيديو النهائي",       "en": "Video Assembly (ffmpeg)"},
    "pdf_assembly":          {"ar": "تجميع الكتاب PDF",            "en": "PDF Assembly (reportlab)"},
    "final_assembly":        {"ar": "التجميع النهائي",             "en": "Final Assembly"},
    "pdf_generation":        {"ar": "توليد الكتاب PDF",            "en": "PDF Generation"},
}

# Default pipeline ordering + flags. child_character_i2i is DISABLED by default
# in Phase A (data-only; no runtime effect) — admin must explicitly enable it
# in Phase B when the execution code lands.
DEFAULT_PIPELINE = {
    # Canonical execution order — 11 stages reflecting the real implementation.
    "order": [
        "scenario_generation",
        "production_planning",
        "child_character_i2i",
        "extra_character_i2i",
        "scene_image_generation",
        "book_page_image_generation",
        "narration_generation",
        "music_generation",
        "video_generation",
        "video_assembly",
        "pdf_assembly",
    ],
    "stages": {
        "scenario_generation":      {"enabled": True,  "max_retries": 2, "fallback_allowed": True},
        "production_planning":      {"enabled": True,  "max_retries": 2, "fallback_allowed": True},
        "child_character_i2i":      {"enabled": False, "max_retries": 2, "fallback_allowed": False,
                                       "runs_before_scene_generation": True},
        "extra_character_i2i":      {"enabled": False, "max_retries": 2, "fallback_allowed": True,
                                       "runs_before_scene_generation": True},
        "scene_image_generation":   {"enabled": True,  "max_retries": 3, "fallback_allowed": True,
                                       "uses_child_reference_asset": True,
                                       "reference_aware": True},
        "book_page_image_generation": {"enabled": True, "max_retries": 1, "fallback_allowed": True,
                                       "reuses_scene_image_today": True,
                                       "gated_by_output_type": ["pdf", "both"]},
        "narration_generation":     {"enabled": True,  "max_retries": 2, "fallback_allowed": True,
                                       "audio_aware": True,
                                       "gated_by_output_type": ["video", "both"]},
        "music_generation":         {"enabled": False, "max_retries": 2, "fallback_allowed": True,
                                       "audio_aware": True,
                                       "gated_by_output_type": ["video", "both"]},
        "video_generation":         {"enabled": False, "max_retries": 1, "fallback_allowed": True,
                                       "gated_by_output_type": ["video", "both"]},
        "video_assembly":           {"enabled": True,  "max_retries": 2, "fallback_allowed": True,
                                       "local_binary": True,
                                       "gated_by_output_type": ["video", "both"]},
        "pdf_assembly":             {"enabled": True,  "max_retries": 2, "fallback_allowed": True,
                                       "local_binary": True,
                                       "gated_by_output_type": ["pdf", "both"]},
    },
}

# Env-var mapping for admin API Status page (keys stored in .env, never in DB).
PROVIDER_ENV_MAP = {
    "anthropic":  {"env_key": "EMERGENT_LLM_KEY",  "label": "Claude (via Emergent)"},
    "gemini":     {"env_key": "EMERGENT_LLM_KEY",  "label": "Gemini / Nano Banana (via Emergent)"},
    "openai":     {"env_key": "OPENAI_API_KEY",  "label": "OpenAI (direct)"},
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


async def resolve_model(stage_key: str, hardcoded_provider: str, hardcoded_model: str) -> tuple[str, str, str]:
    """Phase B.1 helper: return (provider, model_name, source).

    Prefers the admin-configured active model when present, otherwise falls
    back to the service's hardcoded values. `source` is either "admin" or
    "fallback" — handy for debug logs so we can see exactly where the config
    came from on each call.
    """
    try:
        doc = await db.model_registry.find_one(
            {"stage_key": stage_key, "active": True},
            {"_id": 0, "provider": 1, "model_name": 1},
        )
    except Exception:  # noqa: BLE001 — never fail the pipeline because of a DB hiccup.
        doc = None
    if doc and doc.get("provider") and doc.get("model_name"):
        return doc["provider"], doc["model_name"], "admin"
    return hardcoded_provider, hardcoded_model, "fallback"


async def resolve_transport(stage_key: str) -> str:
    """Decide which transport to use for a given text stage.

    Returns:
      * "direct-openai" — when the admin registry row has provider=openai AND
        env_key=OPENAI_API_KEY AND the env var is set. The caller should
        bypass emergentintegrations and hit api.openai.com directly.
      * "emergent"      — default. Use the emergentintegrations library with
        EMERGENT_LLM_KEY (existing behavior, unchanged).

    Safe by design: any DB hiccup or missing key → falls back to "emergent".
    """
    import os as _os
    try:
        doc = await db.model_registry.find_one(
            {"stage_key": stage_key, "active": True},
            {"_id": 0, "provider": 1, "env_key": 1},
        )
    except Exception:  # noqa: BLE001
        doc = None
    if (
        doc
        and doc.get("provider") == "openai"
        and doc.get("env_key") == "OPENAI_API_KEY"
        and _os.environ.get("OPENAI_API_KEY")
    ):
        return "direct-openai"
    return "emergent"


# -----------------------------------------------------------------------------
# Phase B.2 — Prompt template rendering (scenario_generation only)
# -----------------------------------------------------------------------------
import re  # noqa: E402
from string import Template  # noqa: E402


# Matches both $var and ${var}. Identifier must start with letter/underscore.
_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def _extract_placeholders(text: str) -> set[str]:
    if not text:
        return set()
    return {m.group(1) or m.group(2) for m in _VAR_PATTERN.finditer(text)}


def render_prompt_template(
    template_text: str,
    context: dict,
    required_vars: list[str] | None = None,
) -> tuple[str | None, bool, str]:
    """Safely render a string.Template-style prompt.

    Returns (rendered_text, ok, reason).
      * ok=True  → rendered is a non-empty string safe to send to the LLM
      * ok=False → caller MUST fall back to the hardcoded default. `reason`
                   is a short machine-readable code suitable for logging.

    Never raises. Never executes code. No f-string, no eval.
    """
    if not template_text or not template_text.strip():
        return None, False, "empty_template"

    placeholders = _extract_placeholders(template_text)
    # Verify every placeholder used in the template has a context value.
    missing = [p for p in placeholders if p not in context or context[p] is None]
    if missing:
        return None, False, f"missing_variable:{missing[0]}"

    # Verify all explicitly required variables are present (admin-declared).
    if required_vars:
        req_missing = [v for v in required_vars if v not in context or context[v] is None]
        if req_missing:
            return None, False, f"required_missing:{req_missing[0]}"

    try:
        # `safe_substitute` never raises on unknown keys; we already verified
        # all placeholders above so behavior is the same as `substitute`.
        rendered = Template(template_text).safe_substitute(
            {k: str(v) for k, v in context.items()}
        )
    except (ValueError, KeyError) as e:
        return None, False, f"render_error:{type(e).__name__}"

    if not rendered.strip():
        return None, False, "rendered_empty"
    return rendered, True, "ok"


async def resolve_prompt(
    stage_key: str,
    context: dict,
    required_vars: list[str] | None = None,
) -> tuple[str | None, str, str]:
    """Try to load + render the admin-active prompt for a stage.

    Returns (rendered_text_or_none, source, reason).
      * source = "admin"   → rendered_text is safe to use
      * source = "default" → caller must build the hardcoded prompt
                             (rendered_text is None)
      * reason is always set so the caller can emit a single structured log.
    """
    try:
        doc = await db.prompt_templates.find_one(
            {"stage_key": stage_key, "active": True},
            {"_id": 0, "id": 1, "template_text": 1, "variables": 1, "version": 1},
        )
    except Exception:  # noqa: BLE001
        return None, "default", "db_error"

    if not doc:
        return None, "default", "no_active_template"

    tpl = doc.get("template_text") or ""
    declared = doc.get("variables") or []
    rendered, ok, reason = render_prompt_template(tpl, context, required_vars or declared)
    if ok:
        return rendered, "admin", f"template_id={doc.get('id')} version={doc.get('version')}"
    return None, "default", reason


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
