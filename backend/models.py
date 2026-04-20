"""Pydantic models for Gheras AI Storytelling platform."""
from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime, timezone
from enum import Enum
import uuid


def _now():
    return datetime.now(timezone.utc).isoformat()


# =========================
# Users
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
# Children
# =========================
class ChildIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    age: int = Field(ge=1, le=14)
    gender: Literal["male", "female"]
    personality: Optional[str] = None
    interests: Optional[str] = None
    appearance: Optional[str] = None


class Child(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    name: str
    age: int
    gender: str
    personality: Optional[str] = None
    interests: Optional[str] = None
    appearance: Optional[str] = None
    created_at: str


# =========================
# Categories (goal tree - step 1)
# =========================
class CategoryIn(BaseModel):
    name_ar: str
    slug: str
    description: Optional[str] = None
    icon: Optional[str] = "sprout"
    color: Optional[str] = "#87A96B"
    sort_order: int = 0
    is_active: bool = True


class Category(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name_ar: str
    slug: str
    description: Optional[str] = None
    icon: Optional[str] = "sprout"
    color: Optional[str] = "#87A96B"
    sort_order: int = 0
    is_active: bool = True
    created_at: str


class SubcategoryIn(BaseModel):
    category_id: str
    name_ar: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class Subcategory(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    category_id: str
    name_ar: str
    description: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: str


# =========================
# Story Styles (step 4)
# =========================
class StoryStyleIn(BaseModel):
    name_ar: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True


class StoryStyle(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name_ar: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    sort_order: int = 0
    is_active: bool = True
    created_at: str


# =========================
# Orders
# =========================
class OrderStatus(str, Enum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    READY_FOR_AI = "ready_for_ai"
    GENERATING = "generating"
    COMPLETED = "completed"


ORDER_STATUS_AR = {
    "pending": "بانتظار المراجعة",
    "in_review": "قيد المراجعة",
    "ready_for_ai": "جاهز للتوليد",
    "generating": "جاري التوليد",
    "completed": "مكتمل",
}


class OrderCreate(BaseModel):
    # Step 1
    category_id: str
    subcategory_id: Optional[str] = None
    custom_goal: Optional[str] = None
    # Step 2 - Child info (inline or existing)
    child: ChildIn
    # Step 3 - Personalization (optional)
    personalization: Optional[Dict[str, Any]] = None
    # Step 4
    style_id: str
    # Step 5 - Additional notes
    notes: Optional[str] = None


class OrderStatusUpdate(BaseModel):
    status: OrderStatus
    admin_note: Optional[str] = None


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    user_id: str
    category_id: str
    subcategory_id: Optional[str] = None
    custom_goal: Optional[str] = None
    child_snapshot: Dict[str, Any]
    personalization: Optional[Dict[str, Any]] = None
    style_id: str
    notes: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    admin_note: Optional[str] = None
    ai_prompt_snapshot: Optional[str] = None
    created_at: str
    updated_at: str


class OrderDetail(Order):
    category_name: Optional[str] = None
    subcategory_name: Optional[str] = None
    style_name: Optional[str] = None
    user_email: Optional[str] = None


# =========================
# CMS - Landing page content
# =========================
class ContentBlockIn(BaseModel):
    key: str
    value: Any
    section: Optional[str] = None


class ContentBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str
    value: Any
    section: Optional[str] = None
    updated_at: str


# =========================
# AI Prompts (prepared for later AI generation)
# =========================
class PromptIn(BaseModel):
    key: str
    title_ar: str
    description: Optional[str] = None
    template: str
    variables: List[str] = []
    is_active: bool = True


class Prompt(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    key: str
    title_ar: str
    description: Optional[str] = None
    template: str
    variables: List[str] = []
    is_active: bool = True
    created_at: str
    updated_at: str


# =========================
# Plans / Pricing
# =========================
class PlanIn(BaseModel):
    name_ar: str
    price: float = 0
    currency: str = "SAR"
    story_limit: int = 1
    features: List[str] = []
    is_active: bool = True
    sort_order: int = 0


class Plan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    name_ar: str
    price: float
    currency: str
    story_limit: int
    features: List[str]
    is_active: bool
    sort_order: int
    created_at: str


# =========================
# Settings (generic key/value)
# =========================
class Setting(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str
    value: Any
    updated_at: str


class SettingIn(BaseModel):
    key: str
    value: Any
