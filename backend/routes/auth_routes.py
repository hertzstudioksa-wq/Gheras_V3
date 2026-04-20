"""Authentication endpoints."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends

from db import db
from auth import hash_password, verify_password, create_access_token, get_current_user
from models import (
    UserCreate, UserLogin, UserPublic, AuthResponse, UserRole,
    PasswordChange,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _public(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
        "is_active": user.get("is_active", True),
        "must_change_password": user.get("must_change_password", False),
        "created_at": user["created_at"],
    }


@router.post("/register", response_model=AuthResponse)
async def register(payload: UserCreate):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=400, detail="هذا البريد مسجّل مسبقاً")
    user_id = str(uuid.uuid4())
    doc = {
        "id": user_id,
        "email": payload.email.lower(),
        "full_name": payload.full_name.strip(),
        "hashed_password": hash_password(payload.password),
        "role": UserRole.USER.value,
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    token = create_access_token(user_id, UserRole.USER.value)
    return AuthResponse(access_token=token, user=UserPublic(**_public(doc)))


@router.post("/login", response_model=AuthResponse)
async def login(payload: UserLogin):
    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=401, detail="البريد أو كلمة المرور غير صحيحة")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="الحساب غير مفعل")
    token = create_access_token(user["id"], user["role"])
    return AuthResponse(access_token=token, user=UserPublic(**_public(user)))


@router.get("/me", response_model=UserPublic)
async def me(current=Depends(get_current_user)):
    return UserPublic(**_public(current))


@router.post("/change-password")
async def change_password(payload: PasswordChange, current=Depends(get_current_user)):
    user = await db.users.find_one({"id": current["id"]})
    if not user or not verify_password(payload.current_password, user.get("hashed_password", "")):
        raise HTTPException(status_code=400, detail="كلمة المرور الحالية غير صحيحة")
    await db.users.update_one(
        {"id": current["id"]},
        {"$set": {
            "hashed_password": hash_password(payload.new_password),
            "must_change_password": False,
        }},
    )
    return {"ok": True, "message": "تم تحديث كلمة المرور"}
