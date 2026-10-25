"""Family watch links: the parent makes / switches off a link; anyone with the
link watches the story (see services/share_service.py)."""
import os

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response

from auth import get_current_user
from db import db
from services import rate_limit, share_service

user_router = APIRouter(prefix="/orders", tags=["share"])
public_router = APIRouter(prefix="/public/share", tags=["share-public"])

NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


def _url(request: Request, token: str) -> str:
    base = (os.environ.get("PUBLIC_APP_URL") or request.headers.get("origin") or "").rstrip("/")
    return f"{base}/s/{token}"


def _view(link: dict | None, request: Request) -> dict:
    if not link:
        return {"active": False}
    return {"active": True, "url": _url(request, link["token"]), "expires_at": link["expires_at"],
            "views": link.get("views", 0)}


async def _own_delivered(order_id: str, user: dict) -> dict:
    order = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0, "id": 1, "user_id": 1,
                                                                                "status": 1})
    if not order:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if order.get("status") != "delivered":
        raise HTTPException(status_code=400, detail="الرابط بيتعمل بعد ما القصة تخلص")
    return order


@user_router.get("/{order_id}/share")
async def get_share(order_id: str, request: Request, current=Depends(get_current_user)):
    await _own_delivered(order_id, current)
    return _view(await share_service.active_link(order_id), request)


@user_router.post("/{order_id}/share")
async def create_share(order_id: str, request: Request, current=Depends(get_current_user)):
    rate_limit.check(f"share:{current['id']}", 20, 3600)
    order = await _own_delivered(order_id, current)
    return _view(await share_service.create(order), request)


@user_router.delete("/{order_id}/share")
async def revoke_share(order_id: str, current=Depends(get_current_user)):
    await _own_delivered(order_id, current)
    await share_service.revoke(order_id)
    return {"active": False}


async def _shared(token: str) -> dict:
    found = await share_service.resolve(token)
    if not found:
        raise HTTPException(status_code=404, detail="الرابط ده انتهى أو اتقفل", headers=NOINDEX)
    return found


@public_router.get("/{token}", dependencies=[Depends(rate_limit.per_ip("share-view", 120, 60))])
async def shared_story(token: str, response: Response):
    found = await _shared(token)
    await share_service.count_view(found["link"]["id"])
    response.headers.update(NOINDEX)
    return {"title": found["title"], "child_name": found["child_name"], "expires_at": found["link"]["expires_at"],
            "has_cover": bool(found["cover_file_id"])}


async def _stream(file_id: str | None, range_header: str | None) -> Response:
    from routes.upload_routes import file_response

    rec = await db.files.find_one({"id": file_id, "is_deleted": False}, {"_id": 0}) if file_id else None
    if not rec:
        raise HTTPException(status_code=404, detail="الملف غير موجود")
    resp = await file_response(rec, range_header, cache="private, max-age=600")
    resp.headers.update(NOINDEX)
    return resp


@public_router.get("/{token}/video", dependencies=[Depends(rate_limit.per_ip("share-media", 600, 60))])
async def shared_video(token: str, range_header: str | None = Header(None, alias="Range")):
    return await _stream((await _shared(token))["video_file_id"], range_header)


@public_router.get("/{token}/cover", dependencies=[Depends(rate_limit.per_ip("share-media", 600, 60))])
async def shared_cover(token: str):
    return await _stream((await _shared(token))["cover_file_id"], None)
