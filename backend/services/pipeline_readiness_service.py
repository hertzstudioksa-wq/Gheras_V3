"""Pipeline Readiness — Phase I.

Single source of truth for `/admin/pipeline` and any cross-page consistency
check. Joins:
  * canonical SUPPORTED_STAGES + EXECUTOR_STATUS + STAGE_NOTES_AR (Phase G)
  * pipeline_config (DEFAULT_PIPELINE merged with admin overrides)
  * model_registry (provider/model + applied_by_preset_*)
  * prompt_templates (active vs missing → prompt_driven flag)
  * pricing_service.per_stage_costs
  * secret_overrides_service (env_key resolution & secret_source)
  * preset_stacks (active preset)

The output is intentionally read-mostly. Edit endpoints stay where they are.
"""
from __future__ import annotations

from db import db
from services.config_service import (
    DEFAULT_PIPELINE, DEFAULT_MODELS, PROVIDER_ENV_MAP, STAGE_DISPLAY_NAMES,
    get_pipeline_config,
)
from services.stage_lab_service import (
    SUPPORTED_STAGES, EXECUTOR_STATUS, STAGE_NOTES_AR, REAL_CALL_STAGES,
)
from services.pricing_service import get_pricing_config
from services.secret_overrides_service import secret_source
from services.tts_service import narration_real_call_available


# Phase K — stages whose prompt is editable from /admin/prompts.
# `local-binary` and `reuse-from-other-stage` stages have no admin-editable
# prompt today (they call ffmpeg/reportlab or reuse another stage's output).
_PROMPT_EDITABLE_STATUSES = {
    "real-call", "real-call-when-keyed", "preview-only", "not-yet-wired",
}


# Why a stage may run / not run, surfaced in the UI as a "tags" array.
def _flags(stage_key: str, pipeline_stage: dict) -> list[str]:
    out = []
    if pipeline_stage.get("uses_child_reference_asset") or pipeline_stage.get("reference_aware"):
        out.append("reference_aware")
    if pipeline_stage.get("audio_aware"):
        out.append("audio_aware")
    if pipeline_stage.get("local_binary"):
        out.append("local_binary")
    if pipeline_stage.get("reuses_scene_image_today"):
        out.append("reuse_from_scene_image")
    if pipeline_stage.get("runs_before_scene_generation"):
        out.append("runs_before_scenes")
    gated = pipeline_stage.get("gated_by_output_type")
    if gated:
        out.append(f"gated:{','.join(gated)}")
    return out


async def build_readiness() -> dict:
    """Return a consolidated readiness payload."""
    cfg = await get_pipeline_config()
    pricing = await get_pricing_config()

    # All active prompt templates.
    tpl_rows = await db.prompt_templates.find(
        {"active": True}, {"_id": 0, "stage_key": 1, "id": 1, "version": 1},
    ).to_list(50)
    tpl_by_stage = {r["stage_key"]: r for r in tpl_rows}

    # Model registry.
    mr_rows = await db.model_registry.find({}, {"_id": 0}).to_list(50)
    mr_by_stage = {r["stage_key"]: r for r in mr_rows}

    # Active preset (Phase H).
    active_preset = await db.preset_stacks.find_one(
        {"is_active": True, "is_archived": {"$ne": True}}, {"_id": 0},
    )

    stages_out = []
    pipeline_stages = cfg.get("stages") or {}
    pipeline_order = cfg.get("order") or list(SUPPORTED_STAGES)

    # Make sure every SUPPORTED stage shows up exactly once, ordered by the
    # admin-controlled pipeline order with unknown stages appended.
    seen = set()
    ordered = [s for s in pipeline_order if s in SUPPORTED_STAGES] + \
              [s for s in SUPPORTED_STAGES if s not in pipeline_order]

    for s in ordered:
        if s in seen:
            continue
        seen.add(s)
        ps = pipeline_stages.get(s, {})
        # Provider/model — DB row first, then DEFAULT_MODELS for stages with
        # no explicit row yet (so /admin/pipeline mirrors /admin/models).
        mr = mr_by_stage.get(s, {})
        if not mr:
            defaults = DEFAULT_MODELS.get(s) or {}
            mr = {
                "provider":          defaults.get("provider"),
                "model_name":        defaults.get("model_name"),
                "fallback_provider": defaults.get("fallback_provider"),
                "fallback_model":    defaults.get("fallback_model"),
                "env_key":           defaults.get("env_key"),
            }
        env_key = mr.get("env_key")
        executor_status = EXECUTOR_STATUS.get(s, "preview-only")
        # Source-aware secret resolution.
        sec_source = await secret_source(env_key) if env_key else "n/a"

        # Phase K — `executor_callable` collapses status + secret presence
        # into a single boolean so the unified Stage Control can show a
        # green/grey indicator without re-implementing the rules.
        if executor_status == "real-call":
            executor_callable = sec_source in ("env", "override") if env_key else True
        elif executor_status == "real-call-when-keyed":
            # Today only narration_generation falls in this bucket.
            if s == "narration_generation":
                executor_callable = await narration_real_call_available()
            else:
                executor_callable = sec_source in ("env", "override")
        elif executor_status == "local-binary":
            executor_callable = True       # no key needed
        else:
            executor_callable = False

        prompt_editable = executor_status in _PROMPT_EDITABLE_STATUSES

        # Default cost line.
        unit_cost = float((pricing.get("per_stage_costs") or {}).get(s, 0.0))
        config_source = "preset" if mr.get("applied_by_preset_id") else "manual_or_default"

        stages_out.append({
            "order_index":      ordered.index(s),
            "stage_key":        s,
            "name_ar":          (STAGE_DISPLAY_NAMES.get(s) or {}).get("ar") or s,
            "name_en":          (STAGE_DISPLAY_NAMES.get(s) or {}).get("en") or s,
            "executor_status":  executor_status,
            "executor_notes_ar": STAGE_NOTES_AR.get(s, ""),
            "executor_callable": bool(executor_callable),
            "prompt_editable":   bool(prompt_editable),
            "is_real_call_stage": s in REAL_CALL_STAGES,
            # Pipeline switches
            "enabled":           bool(ps.get("enabled", False)),
            "max_retries":       int(ps.get("max_retries", 1)),
            "fallback_allowed":  bool(ps.get("fallback_allowed", False)),
            "flags":             _flags(s, ps),
            # Provider/model + preset provenance
            "provider":              mr.get("provider"),
            "model_name":            mr.get("model_name"),
            "fallback_provider":     mr.get("fallback_provider"),
            "fallback_model":        mr.get("fallback_model"),
            "env_key":               env_key,
            "secret_source":         sec_source,
            "config_source":         config_source,
            "applied_by_preset_id":  mr.get("applied_by_preset_id"),
            "applied_by_preset_name": mr.get("applied_by_preset_name"),
            # Prompt
            "prompt_driven":     s in tpl_by_stage,
            "prompt_template_id": (tpl_by_stage.get(s) or {}).get("id"),
            "prompt_template_version": (tpl_by_stage.get(s) or {}).get("version"),
            # Cost
            "estimated_cost":   unit_cost,
            "currency":         pricing.get("currency", "SAR"),
        })

    # Cross-page integrity self-check — surfaces any orphan we'd otherwise
    # silently absorb.
    orphan_stages_in_pipeline = [
        s for s in pipeline_stages if s not in SUPPORTED_STAGES
    ]
    missing_stages_in_pipeline = [
        s for s in SUPPORTED_STAGES if s not in pipeline_stages
    ]
    integrity = {
        "orphan_stages_in_pipeline": orphan_stages_in_pipeline,
        "missing_stages_in_pipeline": missing_stages_in_pipeline,
        "ok": not orphan_stages_in_pipeline and not missing_stages_in_pipeline,
    }

    # Audio mode awareness map.
    audio_aware_stages = [s["stage_key"] for s in stages_out if "audio_aware" in s["flags"]]
    reference_aware_stages = [s["stage_key"] for s in stages_out if "reference_aware" in s["flags"]]

    return {
        "stages": stages_out,
        "active_preset": (
            {"id": active_preset.get("id"), "name": active_preset.get("name"),
             "slug": active_preset.get("slug"), "applied_at": active_preset.get("applied_at")}
            if active_preset else None
        ),
        "audio_aware_stages": audio_aware_stages,
        "reference_aware_stages": reference_aware_stages,
        "supported_stages_count": len(SUPPORTED_STAGES),
        "pipeline_source": cfg.get("source"),
        "integrity": integrity,
        "provider_env_map": dict(PROVIDER_ENV_MAP),
        "default_pipeline_order": list(DEFAULT_PIPELINE["order"]),
    }
