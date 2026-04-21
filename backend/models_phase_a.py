"""Phase A data model documentation (reference only).

Pydantic models for internal reference. Actual DB documents use the same
shape. Collections are created on first write — nothing to migrate.

Collections added in Phase A:
  * model_registry         — one doc per generation stage
  * prompt_templates       — versioned prompt text per stage
  * pipeline_config        — singleton `{id: "default"}` controlling flow
  * child_character_assets — placeholder for Phase C (I2I) output; empty until then
"""
from typing import Any

from pydantic import BaseModel, Field


class ModelRegistryDoc(BaseModel):
    id: str
    stage_key: str
    stage_name_ar: str
    stage_name_en: str
    provider: str
    model_name: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    env_key: str | None = None
    active: bool = True
    notes: str = ""
    last_test_status: str | None = None  # ok | failed | null
    last_test_at: str | None = None
    created_at: str
    updated_at: str


class PromptTemplateDoc(BaseModel):
    id: str
    stage_key: str
    name: str
    description: str = ""
    template_text: str
    variables: list[str] = Field(default_factory=list)
    version: int = 1
    active: bool = False
    created_at: str
    updated_at: str


class PipelineStageFlags(BaseModel):
    enabled: bool
    max_retries: int = 2
    fallback_allowed: bool = True
    runs_before_scene_generation: bool | None = None  # child_character_i2i only
    uses_child_reference_asset: bool | None = None    # scene_image_generation only


class PipelineConfigDoc(BaseModel):
    id: str = "default"
    order: list[str]
    stages: dict[str, dict[str, Any]]
    created_at: str
    updated_at: str


class ChildCharacterAssetDoc(BaseModel):
    """Phase C will populate this collection. Phase A just declares the shape."""
    id: str
    order_id: str
    child_id: str | None = None
    source_image_url: str
    generated_image_url: str | None = None
    provider: str | None = None
    model_name: str | None = None
    prompt_used: str | None = None
    status: str = "queued"  # queued | processing | completed | failed
    fallback_used: bool = False
    error_message: str | None = None
    created_at: str
    updated_at: str
