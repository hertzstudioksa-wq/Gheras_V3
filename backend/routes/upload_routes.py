"""Image uploads (child, character, toy) stored via storage.py."""
import io
import os
import uuid
from datetime import datetime, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Header, Response
from PIL import Image, ImageOps, UnidentifiedImageError

from db import db
from auth import get_current_user, decode_token
from services import rate_limit
from storage import put_object, get_object, ALLOWED_EXT, MIME_TYPES, MAX_BYTES, APP_NAME

router = APIRouter(prefix="/uploads", tags=["uploads"])


def _now():
    return datetime.now(timezone.utc).isoformat()


# "style" = an admin's art style reference / thumbnail (never a customer's photo).
ADMIN_SCOPES = {"style"}
ALLOWED_SCOPES = {"child", "character", "toy"} | ADMIN_SCOPES
MAX_SIDE = 2048


def _sanitize_image(data: bytes) -> tuple[bytes, str]:
    """Decode, drop metadata (EXIF/GPS), cap the size and re-encode.

    These are mostly photos of children that later go to AI providers, so we
    never keep the original bytes. Returns (bytes, ext); raises 400 if the
    file isn't a real image whatever its extension says.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            fmt = "JPEG" if img.format in ("JPEG", "MPO") else "PNG"
            img = ImageOps.exif_transpose(img)  # returns a new image without .format
            img = img.convert("RGB" if fmt == "JPEG" else "RGBA")
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            img.save(out, format=fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(status_code=400, detail="الملف ليس صورة صالحة")
    return out.getvalue(), ("jpg" if fmt == "JPEG" else "png")


@router.post("/image")
async def upload_image(
    file: UploadFile = File(...),
    scope: str = Form("child"),
    current=Depends(get_current_user),
):
    if scope not in ALLOWED_SCOPES:
        raise HTTPException(status_code=400, detail="نطاق الرفع غير صالح")
    rate_limit.check(f"upload:{current['id']}", 40, 3600, "رفعت صور كتير — جرّب بعد شوية")
    if scope in ADMIN_SCOPES and current.get("role") != "admin":
        raise HTTPException(status_code=403, detail="ممنوع الوصول")
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail="امتداد الصورة غير مدعوم")

    data = await file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="حجم الصورة كبير جداً (حد أقصى 6MB)")
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="ملف فارغ")
    data, ext = _sanitize_image(data)

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

    # Served by our backend; <img src> adds the short-lived media token (?mt=).
    url = f"/api/uploads/file/{file_id}"
    return {"id": file_id, "url": url, "storage_path": result["path"], "content_type": content_type}


_RANGE = re.compile(r"bytes=(\d*)-(\d*)$")


@router.get("/file/{file_id}")
async def download_file(
    file_id: str,
    authorization: str = Header(None),
    mt: str | None = Query(None),
    range_header: str | None = Header(None, alias="Range"),
):
    """A stored file for its owner or an admin. <img>/<video> tags can't send
    headers, so links carry the short-lived media token (?mt=), never the
    session token. Supports byte ranges so videos seek (and play on Safari)."""
    if authorization and authorization.startswith("Bearer "):
        token, want_media = authorization.split(" ", 1)[1], False
    elif mt:
        token, want_media = mt, True
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        claims = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if (claims.get("typ") == "media") != want_media:
        raise HTTPException(status_code=401, detail="Unauthorized")
    uid = claims.get("sub")
    user = await db.users.find_one({"id": uid}, {"_id": 0, "role": 1, "token_version": 1, "is_active": 1})
    if not user or not user.get("is_active", True) or \
            int(claims.get("tv", 0)) != int(user.get("token_version", 0)):
        raise HTTPException(status_code=401, detail="Unauthorized")
    role = user.get("role")

    rec = await db.files.find_one({"id": file_id, "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="الملف غير موجود")

    # Access control: owner or admin only
    if rec.get("user_id") != uid and role != "admin":
        raise HTTPException(status_code=403, detail="ممنوع الوصول")

    return await file_response(rec, range_header)


async def file_response(rec: dict, range_header: str | None, cache: str = "private, max-age=3600") -> Response:
    """A stored file as a response, honouring byte ranges (shared by family links)."""
    try:
        data, ct = get_object(rec["storage_path"])
    except Exception:
        raise HTTPException(status_code=502, detail="تعذّر تحميل الملف")
    media_type = rec.get("content_type", ct)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": cache}
    m = _RANGE.match((range_header or "").strip())
    if m and (m.group(1) or m.group(2)):
        size = len(data)
        if m.group(1):
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
        else:  # last N bytes
            start, end = max(0, size - int(m.group(2))), size - 1
        if start >= size or start > end:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
        return Response(content=data[start:end + 1], status_code=206, media_type=media_type,
                        headers={**headers, "Content-Range": f"bytes {start}-{end}/{size}"})
    return Response(content=data, media_type=media_type, headers=headers)
