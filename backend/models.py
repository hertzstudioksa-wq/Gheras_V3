"""Pydantic models for Gheras — v2 (6-step structured builder)."""
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Dict, Any, Literal
from enum import Enum


# =========================
# Users (unchanged)
# =========================
class UserRole(str, Enum):
    USER = "user"
    ADMIN = "admin"


class UserPublic(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool = True
    must_change_password: bool = False
    created_at: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    full_name: str = Field(min_length=1, max_length=80)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    role: Optional[UserRole] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic


# =========================
# Categories + Subcategories
# =========================
class CategoryIn(BaseModel):
    name_ar: str
    slug: str
    description: Optional[str] = None
    icon: Optional[str] = "sprout"
    color: Optional[str] = "#87A96B"
    sort_order: int = 0
    is_active: bool = True


class SubcategoryIn(BaseModel):
    category_id: str
    name_ar: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


# =========================
# Story Options (unified dynamic options for Step 5)
# kinds: type | tone | setting | language | voice
# =========================
StoryOptionKind = Literal["type", "tone", "setting", "language", "voice"]


class StoryOptionIn(BaseModel):
    kind: StoryOptionKind
    name_ar: str
    value: str  # machine-readable key e.g. "realistic"
    description: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    is_hidden: bool = False


# =========================
# Structured order data
# =========================
class GoalPayload(BaseModel):
    category_id: str
    subcategory_id: Optional[str] = None
    custom_subcategory: Optional[str] = None
    context: str = Field(min_length=3, max_length=2000)  # REQUIRED real-life situation


class ChildPayload(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    age: int = Field(ge=1, le=14)
    gender: Literal["male", "female"]
    image_url: str = Field(min_length=3)  # REQUIRED
    appearance_notes: Optional[str] = None
    hijab: Optional[bool] = False


class CharacterPayload(BaseModel):
    type: Literal["mother", "father", "sibling", "friend", "teacher", "grandparent", "other"]
    name: Optional[str] = None
    role: Literal["mentioned", "visible"] = "mentioned"
    image_url: Optional[str] = None


class FavoriteItem(BaseModel):
    selected: bool = False
    name: Optional[str] = None  # value typed by user


class PersonalizationPayload(BaseModel):
    favorites: Dict[str, FavoriteItem] = {}  # keys: toy, place, character, hobby, other
    toy_image_url: Optional[str] = None
    custom_notes: Optional[str] = None


class StylePayload(BaseModel):
    type_id: Optional[str] = None
    tone_id: Optional[str] = None
    setting_id: Optional[str] = None
    language_id: Optional[str] = None
    voice_id: Optional[str] = None


# Allowed duration snap points (seconds)
DURATION_SNAPS = [30, 45, 60, 90, 120, 150, 180]


def duration_meta(seconds: int) -> dict:
    """Derive label / scene_target / scene_target_{min,max} / bucket / cost_tier.

    Phase D.5 — duration → scene_target bucket mapping (dynamic within range):
      * 30–45s   → 3–4 scenes   (bucket="short")
      * 60–90s   → 5–6 scenes   (bucket="medium")
      * 120–180s → 7–9 scenes   (bucket="long")

    Each specific snap point keeps its own dynamic pick inside the bucket so the
    LLM gets a concrete target (scene_target) while downstream validation uses
    the bucket range [scene_target_min, scene_target_max].
    """
    s = int(seconds)
    if s not in DURATION_SNAPS:
        # snap to nearest allowed
        s = min(DURATION_SNAPS, key=lambda x: abs(x - s))
    mapping = {
        30:  {"label": "30 ثانية",      "scene_target": 3, "bucket": "short",  "min": 3, "max": 4, "cost_tier": "low"},
        45:  {"label": "45 ثانية",      "scene_target": 4, "bucket": "short",  "min": 3, "max": 4, "cost_tier": "low"},
        60:  {"label": "دقيقة",         "scene_target": 5, "bucket": "medium", "min": 5, "max": 6, "cost_tier": "medium"},
        90:  {"label": "دقيقة ونصف",    "scene_target": 6, "bucket": "medium", "min": 5, "max": 6, "cost_tier": "medium"},
        120: {"label": "دقيقتان",       "scene_target": 7, "bucket": "long",   "min": 7, "max": 9, "cost_tier": "high"},
        150: {"label": "دقيقتان ونصف",  "scene_target": 8, "bucket": "long",   "min": 7, "max": 9, "cost_tier": "high"},
        180: {"label": "ثلاث دقائق",    "scene_target": 9, "bucket": "long",   "min": 7, "max": 9, "cost_tier": "high"},
    }
    m = mapping[s]
    return {
        "seconds": s,
        "label": m["label"],
        "scene_target": m["scene_target"],
        "scene_target_min": m["min"],
        "scene_target_max": m["max"],
        "scene_target_bucket": m["bucket"],
        "cost_tier": m["cost_tier"],
    }


def duration_scene_range(duration: dict | None) -> tuple[int, int] | None:
    """Return (min, max) scene range for an order's stored duration dict.

    Returns None for old orders that were persisted before Phase D.5 (no
    bucket fields). Callers MUST treat `None` as "use legacy exact-match
    validation" so existing orders keep their current behaviour.
    """
    if not duration:
        return None
    mn = duration.get("scene_target_min")
    mx = duration.get("scene_target_max")
    if isinstance(mn, int) and isinstance(mx, int) and mn <= mx:
        return (mn, mx)
    return None


class DurationPayload(BaseModel):
    seconds: int = 90


AUDIO_BACKGROUND_MODES = ("music", "human_rhythm", "none")


class AudioBackgroundPayload(BaseModel):
    mode: str = "music"  # one of AUDIO_BACKGROUND_MODES


def get_order_output_type(order: dict | None) -> str:
    """Read the requested deliverable type from an order doc.

    Backwards-compatible:
      * Legacy orders without `data.delivery` default to "both" (the full
        pipeline that always ran). This guarantees ZERO regression on orders
        created before Wave 1.
      * Unknown/invalid values also fall back to "both".
    """
    if not order:
        return "both"
    data = order.get("data") or {}
    delivery = data.get("delivery") or {}
    ot = delivery.get("output_type")
    if ot in OUTPUT_TYPES:
        return ot
    return "both"


# Phase Wave-1 — deliverable type. Drives pricing + which pipeline stages run.
OUTPUT_TYPES = ("video", "pdf", "both")


class DeliveryPayload(BaseModel):
    output_type: str = "both"  # one of OUTPUT_TYPES; default keeps legacy full pipeline


class StoryData(BaseModel):
    goal: GoalPayload
    child: ChildPayload
    characters: List[CharacterPayload] = []
    personalization: PersonalizationPayload = PersonalizationPayload()
    style: StylePayload = StylePayload()
    duration: DurationPayload = DurationPayload()
    audio_background: AudioBackgroundPayload = AudioBackgroundPayload()
    delivery: DeliveryPayload = DeliveryPayload()


# =========================
# Order
# =========================
class OrderStatus(str, Enum):
    DRAFT = "draft"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    SCENARIOS_GENERATING = "scenarios_generating"
    SCENARIOS_READY = "scenarios_ready"
    SCENARIO_SELECTED = "scenario_selected"
    READY_FOR_AI = "ready_for_ai"
    PRODUCTION_PLANNING = "production_planning"
    PRODUCTION_READY = "production_ready"
    PRODUCTION_APPROVED = "production_approved"
    ASSETS_GENERATING = "assets_generating"
    ASSETS_READY = "assets_ready"
    ASSEMBLING = "assembling"
    DELIVERED = "delivered"
    MEDIA_FAILED = "media_failed"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


ORDER_STATUS_AR = {
    "draft": "مسودة",
    "pending": "بانتظار البدء",
    "in_review": "قيد المراجعة",
    "scenarios_generating": "جاري توليد السيناريوهات",
    "scenarios_ready": "السيناريوهات جاهزة",
    "scenario_selected": "تم اختيار سيناريو",
    "ready_for_ai": "جاهز للتوليد",
    "production_planning": "جاري إعداد خطة الإنتاج",
    "production_ready": "خطة الإنتاج جاهزة",
    "production_approved": "تمت الموافقة على الخطة",
    "assets_generating": "جاري توليد الوسائط",
    "assets_ready": "الوسائط جاهزة",
    "assembling": "جاري التجميع",
    "delivered": "تم التسليم",
    "media_failed": "فشل إنتاج الوسائط",
    "generating": "جاري التوليد",
    "completed": "مكتمل",
    "failed": "فشل",
}


class OrderCreate(BaseModel):
    data: StoryData


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    admin_note: Optional[str] = None


class PromptUpdate(BaseModel):
    ai_prompt_snapshot: str


# =========================
# Production Plan (Phase 5 - Production Planning Engine)
# =========================
ARC_TEMPLATES = {
    3: ["introduction", "problem", "resolution"],
    4: ["introduction", "problem", "turning_point", "positive_ending"],
    5: ["introduction", "problem", "escalation", "resolution", "positive_ending"],
    6: ["introduction", "problem", "escalation", "climax", "resolution", "positive_ending"],
    7: ["setup", "introduction", "problem", "escalation", "climax", "resolution", "positive_ending"],
    8: ["setup", "introduction", "problem", "escalation_1", "escalation_2", "climax", "resolution", "positive_ending"],
    9: ["setup", "introduction", "problem", "escalation_1", "escalation_2", "climax", "resolution", "reflection", "positive_ending"],
}


class SceneEdit(BaseModel):
    narration_text: Optional[str] = None
    book_text: Optional[str] = None
    visual_description: Optional[str] = None
    image_prompt_text: Optional[str] = None
    animation_motion_hint: Optional[str] = None
    animation_camera_style: Optional[str] = None


class BookPageEdit(BaseModel):
    text: Optional[str] = None
    illustration_prompt: Optional[str] = None


class CharacterProfileEdit(BaseModel):
    visual_description: Optional[str] = None
    clothing_style: Optional[str] = None
    key_features: Optional[str] = None


# =========================
# Drafts (server-side auto-save for logged-in users)
# =========================
class DraftUpsert(BaseModel):
    current_step: int = 1
    data: Dict[str, Any] = {}  # partial, relaxed


# =========================
# CMS, Prompts, Plans, Settings
# =========================
class ContentBlockIn(BaseModel):
    key: str
    value: Any
    section: Optional[str] = None


class PromptIn(BaseModel):
    key: str
    title_ar: str
    description: Optional[str] = None
    template: str
    variables: List[str] = []
    is_active: bool = True


class PlanIn(BaseModel):
    name_ar: str
    price: float = 0
    currency: str = "SAR"
    story_limit: int = 1
    features: List[str] = []
    is_active: bool = True
    sort_order: int = 0


class SettingIn(BaseModel):
    key: str
    value: Any
