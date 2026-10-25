"""Authentication endpoints."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel

from db import db
from auth import hash_password, verify_password, create_access_token, get_current_user, media_token_for
from services import rate_limit
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


@router.post("/register", response_model=AuthResponse,
             dependencies=[Depends(rate_limit.per_ip("register", 5, 3600, "حسابات كتير من نفس الجهاز — جرّب بعد ساعة"))])
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
        "token_version": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.users.insert_one(doc)
    token = create_access_token(user_id, UserRole.USER.value)
    return AuthResponse(access_token=token, user=UserPublic(**_public(doc)), media_token=media_token_for(doc))


LOGIN_FAILURES = (8, 900)  # wrong passwords per email before a 15-minute pause


@router.post("/login", response_model=AuthResponse,
             dependencies=[Depends(rate_limit.per_ip("login", 30, 600))])
async def login(payload: UserLogin):
    email = payload.email.lower()
    fail_key = f"login-fail:{email}"
    if rate_limit.count(fail_key, LOGIN_FAILURES[1]) >= LOGIN_FAILURES[0]:
        raise HTTPException(status_code=429, detail="محاولات دخول خاطئة كثيرة — حاول مرة أخرى بعد ربع ساعة")
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(payload.password, user.get("hashed_password", "")):
        rate_limit.record(fail_key)
        raise HTTPException(status_code=401, detail="البريد أو كلمة المرور غير صحيحة")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="الحساب غير مفعل")
    token = create_access_token(user["id"], user["role"], user.get("token_version", 0))
    return AuthResponse(access_token=token, user=UserPublic(**_public(user)), media_token=media_token_for(user))


@router.get("/me", response_model=UserPublic)
async def me(current=Depends(get_current_user)):
    return UserPublic(**_public(current))


class AccountDelete(BaseModel):
    password: str


@router.post("/delete-account")
async def delete_account(payload: AccountDelete, current=Depends(get_current_user)):
    """Delete the parent's personal data (privacy policy, audit CS-7)."""
    from services.privacy_service import delete_account as wipe
    user = await db.users.find_one({"id": current["id"]})
    if not user or not verify_password(payload.password, user.get("hashed_password", "")):
        raise HTTPException(status_code=400, detail="كلمة المرور غير صحيحة")
    try:
        return {"ok": True, **(await wipe(current["id"], actor=current, reason="طلب ولي الأمر"))}
    except (ValueError, LookupError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/media-token")
async def media_token(current=Depends(get_current_user)):
    """Short-lived token for <img>/<video> links (files only, not the API)."""
    return {"media_token": media_token_for(current)}


@router.post("/change-password")
async def change_password(payload: PasswordChange, current=Depends(get_current_user)):
    user = await db.users.find_one({"id": current["id"]})
    if not user or not verify_password(payload.current_password, user.get("hashed_password", "")):
        raise HTTPException(status_code=400, detail="كلمة المرور الحالية غير صحيحة")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="كلمة المرور الجديدة يجب أن تختلف عن الحالية")
    if user.get("role") == UserRole.ADMIN.value and len(payload.new_password) < 10:
        raise HTTPException(status_code=400, detail="كلمة مرور المدير يجب ألا تقل عن 10 أحرف")
    await db.users.update_one(
        {"id": current["id"]},
        {"$set": {
            "hashed_password": hash_password(payload.new_password),
            "must_change_password": False,
        }, "$inc": {"token_version": 1}},
    )
    # Every other session is signed out; this one continues with a new token.
    fresh = await db.users.find_one({"id": current["id"]}, {"_id": 0, "hashed_password": 0})
    return {"ok": True, "message": "تم تحديث كلمة المرور",
            "access_token": create_access_token(fresh["id"], fresh["role"], fresh.get("token_version", 0)),
            "media_token": media_token_for(fresh)}
