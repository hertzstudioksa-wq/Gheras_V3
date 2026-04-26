"""Admin Preset Stacks routes — Phase H."""
from typing import Any
from fastapi import APIRouter, Depends, HTTPException

from auth import require_admin
from services import preset_stacks_service as svc

router = APIRouter(
    prefix="/admin/presets",
    tags=["admin-preset-stacks"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
async def list_all():
    return {"items": await svc.list_presets()}


@router.get("/active")
async def get_active():
    return {"active": await svc.get_active_preset()}


@router.get("/{preset_id}")
async def get_one(preset_id: str):
    p = await svc.get_preset(preset_id)
    if not p:
        raise HTTPException(status_code=404, detail="preset not found")
    return p


@router.post("")
async def create(payload: dict[str, Any], admin=Depends(require_admin)):
    try:
        p = await svc.create_preset(payload, admin.get("id"), admin.get("email"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return p


@router.put("/{preset_id}")
async def update(preset_id: str, payload: dict[str, Any], admin=Depends(require_admin)):
    try:
        p = await svc.update_preset(preset_id, payload, admin.get("id"), admin.get("email"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not p:
        raise HTTPException(status_code=404, detail="preset not found")
    return p


@router.post("/{preset_id}/clone")
async def clone(preset_id: str, payload: dict[str, Any] = None, admin=Depends(require_admin)):
    p = await svc.clone_preset(preset_id, (payload or {}).get("name"),
                                admin.get("id"), admin.get("email"))
    if not p:
        raise HTTPException(status_code=404, detail="preset not found")
    return p


@router.delete("/{preset_id}")
async def remove(preset_id: str, admin=Depends(require_admin)):
    ok = await svc.delete_preset(preset_id, admin.get("id"), admin.get("email"))
    if not ok:
        raise HTTPException(status_code=404, detail="preset not found")
    return {"ok": True}


@router.post("/{preset_id}/dry-run")
async def preview(preset_id: str):
    try:
        return await svc.dry_run(preset_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{preset_id}/apply")
async def apply(preset_id: str, admin=Depends(require_admin)):
    try:
        return await svc.apply_preset(preset_id, admin.get("id"), admin.get("email"))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
