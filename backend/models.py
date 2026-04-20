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
    """Derive label / scene_target / cost_tier from a duration in seconds."""
    s = int(seconds)
    if s not in DURATION_SNAPS:
        # snap to nearest allowed
        s = min(DURATION_SNAPS, key=lambda x: abs(x - s))
    mapping = {
        30:  {"label": "30 ثانية",      "scene_target": 3, "cost_tier": "low"},
        45:  {"label": "45 ثانية",      "scene_target": 4, "cost_tier": "low"},
        60:  {"label": "دقيقة",         "scene_target": 5, "cost_tier": "medium"},
        90:  {"label": "دقيقة ونصف",    "scene_target": 6, "cost_tier": "medium"},
        120: {"label": "دقيقتان",       "scene_target": 7, "cost_tier": "high"},
        150: {"label": "دقيقتان ونصف",  "scene_target": 8, "cost_tier": "high"},
        180: {"label": "ثلاث دقائق",    "scene_target": 9, "cost_tier": "high"},
    }
    m = mapping[s]
    return {"seconds": s, "label": m["label"], "scene_target": m["scene_target"], "cost_tier": m["cost_tier"]}


class DurationPayload(BaseModel):
    seconds: int = 90


class StoryData(BaseModel):
    goal: GoalPayload
    child: ChildPayload
    characters: List[CharacterPayload] = []
    personalization: PersonalizationPayload = PersonalizationPayload()
    style: StylePayload = StylePayload()
    duration: DurationPayload = DurationPayload()


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
