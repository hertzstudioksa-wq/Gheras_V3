"""Authentication utilities - JWT + bcrypt."""
import os
import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional

from db import db
from models import UserRole

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_DAYS = int(os.environ.get("JWT_EXPIRE_DAYS", "7"))
# Media links (<img>, <video>, PDF downloads) carry this short-lived token
# instead of the session token: it opens files only, never the API (CS-5).
MEDIA_TOKEN_HOURS = int(os.environ.get("MEDIA_TOKEN_HOURS", "12"))

bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, role: str, token_version: int = 0) -> str:
    """Session token. `tv` must match users.token_version, so changing the
    password, role or active flag signs out every older session (CS-13)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "tv": int(token_version or 0),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=JWT_EXPIRE_DAYS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_media_token(user_id: str, role: str, token_version: int = 0) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "tv": int(token_version or 0),
        "typ": "media",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=MEDIA_TOKEN_HOURS)).timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def media_token_for(user: dict) -> str:
    return create_media_token(user["id"], user["role"], user.get("token_version", 0))


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="انتهت صلاحية الجلسة، سجل دخولك مجدداً")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="جلسة غير صالحة")


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="يرجى تسجيل الدخول")
    data = decode_token(creds.credentials)
    if data.get("typ") == "media":  # file links only, never the API
        raise HTTPException(status_code=401, detail="جلسة غير صالحة")
    user = await db.users.find_one({"id": data["sub"]}, {"_id": 0, "hashed_password": 0})
    if not user:
        raise HTTPException(status_code=401, detail="المستخدم غير موجود")
    if int(data.get("tv", 0)) != int(user.get("token_version", 0)):
        raise HTTPException(status_code=401, detail="انتهت الجلسة، سجل دخولك مجدداً")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="الحساب غير مفعل")
    return user


async def get_optional_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    if not creds or not creds.credentials:
        return None
    try:
        data = decode_token(creds.credentials)
        if data.get("typ") == "media":
            return None
        user = await db.users.find_one({"id": data["sub"]}, {"_id": 0, "hashed_password": 0})
        if user and int(data.get("tv", 0)) != int(user.get("token_version", 0)):
            return None
        return user
    except HTTPException:
        return None


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="صلاحيات المدير مطلوبة")
    # Seeded admins start with a temporary password; block admin APIs until it
    # is changed. /auth/change-password and /auth/me use get_current_user, so
    # they stay reachable.
    if user.get("must_change_password"):
        raise HTTPException(status_code=403, detail="يجب تغيير كلمة المرور قبل استخدام لوحة الإدارة")
    return user
