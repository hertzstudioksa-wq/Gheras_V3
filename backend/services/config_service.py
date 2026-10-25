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
    # Every entry has a working executor and a model_catalog row (M4). Text:
    # Claude Opus 5.5 through fal's OpenRouter (same fal balance as the media;
    # approved 2026-10-24). Images: GPT Image 2 through fal.
    "scenario_generation": {
        "provider": "fal_llm",
        "model_name": "anthropic/claude-opus-5.5",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "FAL_KEY_TEXT",
    },
    "production_planning": {
        "provider": "fal_llm",
        "model_name": "anthropic/claude-opus-5.5",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "FAL_KEY_TEXT",
    },
    "child_character_i2i": {
        "provider": "fal_image",
        "model_name": "openai/gpt-image-2",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "FAL_KEY_SCENE",
    },
    "extra_character_i2i": {
        "provider": "fal_image",
        "model_name": "openai/gpt-image-2",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "FAL_KEY_SCENE",
    },
    "scene_image_generation": {
        "provider": "fal_image",
        "model_name": "openai/gpt-image-2",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "FAL_KEY_SCENE",
    },
    "book_page_image_generation": {
        "provider": "fal_image",
        "model_name": "openai/gpt-image-2",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": "FAL_KEY_SCENE",
    },
    # Native-dialect narration steered by a direction prompt (approved in M1).
    # Gemini's voices (authentic dialects) through fal: billed on the fal
    # balance, so the parent's text never goes through Google's free tier.
    "narration_generation": {
        "provider": "fal_gemini_tts",
        "model_name": "fal-ai/gemini-3.1-flash-tts",
        "fallback_provider": "fal_tts",
        "fallback_model": "fal-ai/elevenlabs/tts/multilingual-v2",
        "env_key": "FAL_KEY_NARRATION",
    },
    # Kling 2.5 turbo: close to v3 pro in the bake-off at $0.07/s vs $0.112/s
    # (owner decision 2026-10-24). v3 pro stays available as the "premium" preset.
    "video_generation": {
        "provider": "kling",
        "model_name": "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
        "fallback_provider": "mock",
        "fallback_model": "mock-video-v1",
        "env_key": "FAL_KEY_VIDEO",
    },
    "music_generation": {
        "provider": "fal_music",
        "model_name": "fal-ai/elevenlabs/music",
        "fallback_provider": "mock",
        "fallback_model": "mock-music-v1",
        "env_key": "FAL_KEY_MUSIC",
    },
    "video_assembly": {
        "provider": "ffmpeg",
        "model_name": "local-ffmpeg",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": None,
    },
    "pdf_assembly": {
        "provider": "reportlab",
        "model_name": "local-reportlab",
        "fallback_provider": None,
        "fallback_model": None,
        "env_key": None,
    },
}

# Video quality tiers the parent chooses in the story builder (and pays for).
# "balanced" follows the admin's video_generation model (default Kling 2.5 turbo);
# "premium" renders with the admin's premium model (model_catalog.premium_video_model,
# default Kling v3 pro: character elements, any clip length). The per-second costs
# here are fallbacks; prices use the catalog's.
VIDEO_TIERS = {
    "balanced": {"label_ar": "متوازن", "model_name": None, "cost_per_second_usd": 0.07},
    "premium":  {"label_ar": "فاخر", "model_name": "fal-ai/kling-video/v3/pro/image-to-video",
                 "cost_per_second_usd": 0.112},
}
DEFAULT_VIDEO_TIER = "balanced"


def video_tier_of(order: dict | None) -> str:
    tier = (((order or {}).get("data") or {}).get("delivery") or {}).get("video_tier")
    return tier if tier in VIDEO_TIERS else DEFAULT_VIDEO_TIER


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
        "child_character_i2i":      {"enabled": True,  "max_retries": 2, "fallback_allowed": False,
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
        "music_generation":         {"enabled": True,  "max_retries": 2, "fallback_allowed": True,
                                       "audio_aware": True,
                                       "gated_by_output_type": ["video", "both"]},
        "video_generation":         {"enabled": True,  "max_retries": 1, "fallback_allowed": True,
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
    "anthropic":  {"env_key": "ANTHROPIC_API_KEY",  "label": "Anthropic Claude (direct)"},
    "gemini":     {"env_key": "GEMINI_API_KEY",     "label": "Google Gemini (direct — free tier for testing)"},
    "openai":     {"env_key": "OPENAI_API_KEY",     "label": "OpenAI (direct)"},
    "elevenlabs": {"env_key": "ELEVENLABS_API_KEY", "label": "ElevenLabs TTS (direct, legacy)"},
    # Phase N — per-capability fal.ai keys.
    "fal_image":  {"env_key": "FAL_KEY_SCENE",      "label": "fal.ai — Images (Gemini Nano Banana)"},
    "fal_tts":    {"env_key": "FAL_KEY_NARRATION",  "label": "fal.ai — ElevenLabs TTS (narration)"},
    "gemini_tts": {"env_key": "GEMINI_API_KEY",     "label": "Google Gemini TTS (narration)"},
    "fal_gemini_tts": {"env_key": "FAL_KEY_NARRATION", "label": "fal.ai — Gemini TTS (narration)"},
    "fal_llm":    {"env_key": "FAL_KEY_TEXT",       "label": "fal.ai — OpenRouter (Claude / GPT / Gemini text)"},
    "fal_music":  {"env_key": "FAL_KEY_MUSIC",      "label": "fal.ai — ElevenLabs Music"},
    "kling":      {"env_key": "FAL_KEY_VIDEO",      "label": "fal.ai — Kling Video"},
    "luma":       {"env_key": "FAL_KEY_VIDEO",      "label": "fal.ai — Luma Video"},
    "comfy_image": {"env_key": "COMFY_API_KEY",    "label": "Comfy Cloud — Qwen Image 2.1 (shot keyframes)"},
    "comfy_video": {"env_key": "COMFY_API_KEY",    "label": "Comfy Cloud — Wan 2.2 I2V (shot clips)"},
    "sora":       {"env_key": "EMERGENT_LLM_KEY",   "label": "Sora 2 (via Emergent)"},
    "ffmpeg":     {"env_key": None,                  "label": "ffmpeg (local binary)"},
    "reportlab":  {"env_key": None,                  "label": "reportlab (local)"},
    "mock":       {"env_key": None,                  "label": "Mock (development)"},
    "internal":   {"env_key": None,                  "label": "Internal fallback"},
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
    # DEFAULT_MODELS is the single default shown in the admin and used at
    # runtime; the caller's hardcoded pair only covers stages missing from it.
    default = DEFAULT_MODELS.get(stage_key) or {}
    if default.get("provider") and default.get("model_name"):
        return default["provider"], default["model_name"], "default"
    return hardcoded_provider, hardcoded_model, "fallback"


async def resolve_transport(stage_key: str) -> str:
    """Display label for how a stage reaches its provider (Stage Lab / prompt
    preview). All calls go directly to the provider SDK: "direct-<provider>"."""
    provider, _model, _src = await resolve_model(stage_key, "", "")
    return f"direct-{provider}" if provider else "unconfigured"


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
