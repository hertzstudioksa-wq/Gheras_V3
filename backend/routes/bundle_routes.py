"""Bundle routes — Wave 3 (admin CRUD + grant + user view)."""
from fastapi import APIRouter, Depends, HTTPException
from typing import Any

from db import db
from auth import require_admin, get_current_user
from services.bundle_service import (
    create_bundle, update_bundle, delete_bundle, list_bundles,
    grant_purchase_to_user, list_user_purchases,
)


# ---- Admin ------------------------------------------------------------------
admin_router = APIRouter(
    prefix="/admin/bundles",
    tags=["admin-bundles"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get("")
async def admin_list(active_only: bool = False):
    rows = await list_bundles(active_only=active_only)
    return {"bundles": rows, "count": len(rows)}


@admin_router.post("")
async def admin_create(payload: dict[str, Any], admin=Depends(require_admin)):
    try:
        return await create_bundle(payload, admin_id=admin.get("id"), admin_email=admin.get("email"))
    except ValueError as e:
        raise HTTPException(400, str(e))


@admin_router.put("/{bundle_id}")
async def admin_update(bundle_id: str, payload: dict[str, Any], admin=Depends(require_admin)):
    try:
        bundle = await update_bundle(bundle_id, payload, admin_id=admin.get("id"), admin_email=admin.get("email"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not bundle:
        raise HTTPException(404, "Bundle not found")
    return bundle


@admin_router.delete("/{bundle_id}")
async def admin_deactivate(bundle_id: str, admin=Depends(require_admin)):
    ok = await delete_bundle(bundle_id, admin_id=admin.get("id"), admin_email=admin.get("email"))
    if not ok:
        raise HTTPException(404, "Bundle not found")
    return {"ok": True}


# Grant a purchase manually (no payment).
@admin_router.post("/{bundle_id}/grant")
async def admin_grant(bundle_id: str, payload: dict[str, Any], admin=Depends(require_admin)):
    user_id = (payload or {}).get("user_id")
    if not user_id:
        raise HTTPException(400, "user_id is required")
    bundle = await db.bundles.find_one({"id": bundle_id, "is_active": True}, {"_id": 0})
    if bundle and bundle.get("credit_sar"):
        # M6 — a top-up granted by the admin is wallet credit, not a purchase.
        from services.wallet_service import credit, to_halalas
        if not await db.users.find_one({"id": user_id}, {"_id": 1}):
            raise HTTPException(404, "المستخدم غير موجود")
        await credit(user_id, to_halalas(bundle["credit_sar"]), "adjust", actor=admin,
                     note=f"{bundle['name']} — {(payload or {}).get('reason') or 'منحة من الإدارة'}")
        return {"ok": True, "wallet_credit_sar": bundle["credit_sar"]}
    purchase = await grant_purchase_to_user(
        user_id=user_id,
        bundle_id=bundle_id,
        granted_by=admin.get("id"),
        granted_by_email=admin.get("email"),
        reason=(payload or {}).get("reason") or "manual admin grant",
    )
    if not purchase:
        raise HTTPException(404, "Bundle or user not found")
    return purchase


# Look up purchases for a user (admin view).
@admin_router.get("/users/{user_id}/purchases")
async def admin_list_user_purchases(user_id: str, only_active: bool = False):
    rows = await list_user_purchases(user_id, only_active=only_active)
    return {"purchases": rows, "count": len(rows)}


# ---- User -------------------------------------------------------------------
user_router = APIRouter(
    prefix="/bundles",
    tags=["bundles"],
)


@user_router.get("")
async def public_active_bundles():
    rows = await list_bundles(active_only=True)
    # Strip admin-only fields from public response.
    return {"bundles": [
        {k: v for k, v in b.items() if k in ("id", "name", "description", "output_type",
                                              "quantity", "validity_days", "price", "credit_sar", "currency")}
        for b in rows
    ]}


@user_router.get("/me")
async def my_bundles(only_active: bool = True, current=Depends(get_current_user)):
    rows = await list_user_purchases(current["id"], only_active=only_active)
    return {"purchases": rows, "count": len(rows)}
