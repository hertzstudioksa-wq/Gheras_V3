"""Admin Asset Library + Retention routes — Wave 4."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from auth import require_admin
from services.asset_service import (
    list_assets,
    get_retention_config, update_retention_config,
    archive_asset, restore_asset, purge_asset,
    preview_retention, enforce_retention,
)


router = APIRouter(
    prefix="/admin",
    tags=["admin-assets"],
    dependencies=[Depends(require_admin)],
)


@router.get("/assets")
async def admin_list_assets(
    asset_type: str | None = None,
    lifecycle_status: str | None = None,
    order_status: str | None = None,
    user_id: str | None = None,
    min_age_days: int | None = None,
    max_age_days: int | None = None,
    limit: int = 200,
):
    rows = await list_assets(
        asset_type=asset_type, lifecycle_status=lifecycle_status,
        order_status=order_status, user_id=user_id,
        min_age_days=min_age_days, max_age_days=max_age_days, limit=limit,
    )
    return {"assets": rows, "count": len(rows)}


@router.post("/assets/{asset_type}/{asset_id}/archive")
async def admin_archive(asset_type: str, asset_id: str,
                         force: bool = False, admin=Depends(require_admin)):
    if asset_type not in ("video", "pdf"):
        raise HTTPException(400, "asset_type must be 'video' or 'pdf'")
    res = await archive_asset(asset_type, asset_id,
                               actor_id=admin.get("id"), actor_email=admin.get("email"),
                               force=force)
    if not res.get("ok") and not res.get("needs_force"):
        raise HTTPException(404 if res.get("reason") == "not-found" else 400, res.get("reason"))
    return res


@router.post("/assets/{asset_type}/{asset_id}/restore")
async def admin_restore(asset_type: str, asset_id: str, admin=Depends(require_admin)):
    if asset_type not in ("video", "pdf"):
        raise HTTPException(400, "asset_type must be 'video' or 'pdf'")
    res = await restore_asset(asset_type, asset_id,
                               actor_id=admin.get("id"), actor_email=admin.get("email"))
    if not res.get("ok"):
        raise HTTPException(404 if res.get("reason") == "not-found" else 400, res.get("reason"))
    return res


@router.post("/assets/{asset_type}/{asset_id}/purge")
async def admin_purge(asset_type: str, asset_id: str,
                       force: bool = False, admin=Depends(require_admin)):
    if asset_type not in ("video", "pdf"):
        raise HTTPException(400, "asset_type must be 'video' or 'pdf'")
    res = await purge_asset(asset_type, asset_id,
                             actor_id=admin.get("id"), actor_email=admin.get("email"),
                             force=force)
    if not res.get("ok") and not res.get("needs_force"):
        raise HTTPException(404 if res.get("reason") == "not-found" else 400, res.get("reason"))
    return res


# ---- Retention --------------------------------------------------------------
@router.get("/retention/config")
async def admin_retention_config():
    return await get_retention_config()


@router.put("/retention/config")
async def admin_retention_update(payload: dict[str, Any], admin=Depends(require_admin)):
    return await update_retention_config(payload, admin_id=admin.get("id"), admin_email=admin.get("email"))


@router.get("/retention/preview")
async def admin_retention_preview():
    return await preview_retention()


@router.post("/retention/enforce")
async def admin_retention_enforce(admin=Depends(require_admin)):
    return await enforce_retention(actor_id=admin.get("id"), actor_email=admin.get("email"))
