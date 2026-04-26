"""Admin audit log routes — Wave 3 (read-only)."""
from fastapi import APIRouter, Depends

from auth import require_admin
from services.audit_service import list_audit, ENTITY_TYPES, ACTIONS

router = APIRouter(
    prefix="/admin/audit",
    tags=["admin-audit"],
    dependencies=[Depends(require_admin)],
)


@router.get("/log")
async def get_log(
    entity_type: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
):
    rows = await list_audit(entity_type=entity_type, actor_id=actor_id, action=action, limit=limit)
    return {
        "rows": rows,
        "count": len(rows),
        "entity_types": list(ENTITY_TYPES),
        "actions": list(ACTIONS),
    }
