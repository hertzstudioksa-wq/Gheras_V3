"""Audit Trail — Wave 3.

Records critical admin/config changes with before/after snapshots.

Tracked entity_types:
  pricing_config, model_registry, pipeline_config, prompt_template,
  bundle, bundle_purchase, payment_settings, payment.

Tracked actions:
  create, update, delete, grant, reserve, consume, refund, expire,
  config_change, secret_rotation_attempt.

Never raises — audit is observability and must not block business logic.
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timezone

from db import db

logger = logging.getLogger("audit_service")

ENTITY_TYPES = (
    "pricing_config", "model_registry", "pipeline_config", "prompt_template",
    "bundle", "bundle_purchase", "payment_settings", "payment",
)
ACTIONS = (
    "create", "update", "delete",
    "grant", "reserve", "consume", "refund", "expire",
    "config_change", "secret_rotation_attempt",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trim_snapshot(doc: dict | None, max_chars: int = 4000) -> dict | None:
    """Keep snapshots compact — drop _id, truncate giant fields."""
    if not doc or not isinstance(doc, dict):
        return doc
    trimmed = {k: v for k, v in doc.items() if k != "_id"}
    # Truncate any string > max_chars/10.
    for k, v in list(trimmed.items()):
        if isinstance(v, str) and len(v) > max_chars // 10:
            trimmed[k] = v[: max_chars // 10] + "...[truncated]"
    return trimmed


async def record_audit(
    *,
    entity_type: str,
    entity_id: str | None,
    action: str,
    actor_id: str | None,
    actor_email: str | None,
    summary: str,
    before: dict | None = None,
    after: dict | None = None,
    metadata: dict | None = None,
) -> None:
    """Insert an audit row. Never raises."""
    try:
        if entity_type not in ENTITY_TYPES:
            logger.warning(f"[audit] unknown entity_type={entity_type}; recording anyway")
        if action not in ACTIONS:
            logger.warning(f"[audit] unknown action={action}; recording anyway")
        await db.audit_log.insert_one({
            "id": str(uuid.uuid4()),
            "created_at": _now(),
            "actor_id": actor_id,
            "actor_email": actor_email,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "summary": summary[:500] if isinstance(summary, str) else str(summary)[:500],
            "before": _trim_snapshot(before),
            "after": _trim_snapshot(after),
            "metadata": metadata or {},
        })
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[audit] insert failed: {type(e).__name__}: {e}")


async def list_audit(
    entity_type: str | None = None,
    actor_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> list[dict]:
    q: dict = {}
    if entity_type:
        q["entity_type"] = entity_type
    if actor_id:
        q["actor_id"] = actor_id
    if action:
        q["action"] = action
    rows = await db.audit_log.find(q, {"_id": 0}).sort("created_at", -1).to_list(int(limit))
    return rows
