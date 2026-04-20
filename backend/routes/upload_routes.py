"""Image uploads (child, character, toy) via Emergent Object Storage."""
import os
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Header, Response

from db import db
from auth import get_current_user, decode_token
from storage import put_object, get_object, ALLOWED_EXT, MIME_TYPES, MAX_BYTES, APP_NAME

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _now():
    return datetime.now(timezone.utc).isoformat()


ALLOWED_SCOPES = {"child", "character", "toy"}


@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    scope: str = Form("child"),
    current=Depends(get_current_user),
):
    if scope not in ALLOWED_SCOPES:
        raise HTTPException(status_code=400, detail="نطاق الرفع غير صالح")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="امتداد الصورة غير مدعوم")

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="حجم الصورة كبير جداً (حد أقصى 6MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="ملف فارغ")

    content_type = MIME_TYPES.get(ext, file.content_type or "application/octet-stream")
    file_id = str(uuid.uuid4())
    storage_path = f"{APP_NAME}/users/{current['id']}/{scope}s/{file_id}.{ext}"

    try:
        result = put_object(storage_path, data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"تعذّر رفع الملف: {e}")

    # Persist reference
    await db.files.insert_one({
        "id": file_id,
        "user_id": current["id"],
        "scope": scope,
        "storage_path": result["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": result.get("size", len(data)),
        "is_deleted": False,
        "created_at": _now(),
    })

    # URL served by our backend, token via ?auth= for <img src>
    url = f"/api/uploads/file/{file_id}"
    return {"id": file_id, "url": url, "storage_path": result["path"], "content_type": content_type}


@router.get("/file/{file_id}")
async def download_file(
    file_id: str,
    authorization: str = Header(None),
    auth: str | None = Query(None),
):
    # Auth can come from header OR ?auth= query (for <img> tags).
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
    elif auth:
        token = auth
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")
    uid = claims.get("sub")
    role = claims.get("role")

    rec = await db.files.find_one({"id": file_id, "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="الملف غير موجود")

    # Access control: owner or admin only
    if rec.get("user_id") != uid and role != "admin":
        raise HTTPException(status_code=403, detail="ممنوع الوصول")

    try:
        data, ct = get_object(rec["storage_path"])
    except Exception:
        raise HTTPException(status_code=502, detail="تعذّر تحميل الملف")
    return Response(content=data, media_type=rec.get("content_type", ct))
