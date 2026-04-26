"""Asset Library + Retention service — Wave 4.

Manages the lifecycle of final deliverables (videos + PDFs).

Lifecycle states (stored in `lifecycle_status` on `final_videos` / `final_pdfs`):
  live       — public-accessible. URLs visible to user.
  archived   — admin-hidden. URLs masked, but document preserved. Restorable.
  purged     — final state. URLs cleared from doc; document tagged purged.
               Underlying storage object may persist (we use Emergent Object
               Storage which has no public delete op) — application treats it
               as gone. Documented honestly in admin UI.

Safety guards (Wave 4 — admin-tunable, with sensible defaults):
  * Recently delivered (within `min_age_for_archive_days`) → NEVER touched.
  * Active bundle reservation linked to the order → NEVER touched.
  * Order in non-terminal state (assembling / media_failed) → NEVER touched.
  * `purge` requires asset already `archived` for `min_archived_days_before_purge`
    (default 30). Bypass requires `force=True` (admin-only, audited).

Storage:
  We do NOT call any delete API on the object store (none is exposed). On
  purge we simply remove the URL from the document so the app stops handing
  it out. This is reflected in the UI as "تم تطهيره (الملف لم يعد مرتبطاً
  بالتطبيق)".
"""
from __future__ import annotations
import logging
import uuid
from datetime import datetime, timedelta, timezone

from db import db
from services.audit_service import record_audit

logger = logging.getLogger("asset_service")

CONFIG_DOC_ID = "default"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ---------------------------------------------------------------------------
# Retention config
# ---------------------------------------------------------------------------
DEFAULT_RETENTION_CONFIG = {
    "id": CONFIG_DOC_ID,
    # Manual archive only allowed after the asset has been live this long.
    "min_age_for_archive_days":          30,
    # Manual purge only allowed after the asset has been archived this long.
    "min_archived_days_before_purge":    30,
    # Auto-archive rule (admin runs "enforce now"): live AND order delivered AND
    # delivered_age >= this threshold.
    "auto_archive_after_delivered_days": 30,
    # Auto-purge rule (admin runs "enforce now"): archived AND archived_age >=
    # this threshold AND no active bundle reservation.
    "auto_purge_after_archived_days":    60,
    "protect_active_bundle_orders":      True,
    "protect_recent_delivered_days":     30,   # ALWAYS protected
    "updated_at": None,
    "updated_by": None,
}


async def get_retention_config() -> dict:
    doc = await db.retention_policy.find_one({"id": CONFIG_DOC_ID}, {"_id": 0})
    if not doc:
        return dict(DEFAULT_RETENTION_CONFIG)
    merged = dict(DEFAULT_RETENTION_CONFIG)
    merged.update(doc)
    return merged


async def update_retention_config(patch: dict, admin_id: str | None, admin_email: str | None) -> dict:
    allowed = set(DEFAULT_RETENTION_CONFIG.keys()) - {"id", "updated_at", "updated_by"}
    upd = {k: v for k, v in (patch or {}).items() if k in allowed}
    upd["updated_at"] = _now_iso()
    upd["updated_by"] = admin_id
    before = await db.retention_policy.find_one({"id": CONFIG_DOC_ID}, {"_id": 0})
    await db.retention_policy.update_one(
        {"id": CONFIG_DOC_ID},
        {"$set": upd, "$setOnInsert": {"id": CONFIG_DOC_ID}},
        upsert=True,
    )
    after = await get_retention_config()
    await record_audit(
        entity_type="pricing_config", entity_id="retention_policy",
        action="config_change", actor_id=admin_id, actor_email=admin_email,
        summary=f"retention policy updated: {sorted(upd.keys())}",
        before=before, after=after,
    )
    return after


# ---------------------------------------------------------------------------
# Asset listing + filters
# ---------------------------------------------------------------------------
COLLS = (
    ("video", "final_videos", "video_url"),
    ("pdf",   "final_pdfs",   "pdf_url"),
)


def _coll_for(asset_type: str) -> tuple[str, str]:
    for t, coll, urlkey in COLLS:
        if t == asset_type:
            return coll, urlkey
    raise ValueError(f"Unknown asset_type: {asset_type}")


async def list_assets(
    *,
    asset_type: str | None = None,           # "video" | "pdf" | None (both)
    lifecycle_status: str | None = None,     # "live" | "archived" | "purged"
    order_status: str | None = None,
    user_id: str | None = None,
    min_age_days: int | None = None,
    max_age_days: int | None = None,
    limit: int = 200,
) -> list[dict]:
    """Aggregated asset list across `final_videos` + `final_pdfs`.

    Each row carries: asset_type, asset_id, order_id, user_email, file_url,
    lifecycle_status, age_days, order_status, created_at, archived_at,
    purged_at, has_active_bundle.
    """
    rows: list[dict] = []
    cutoff_min = (_now() - timedelta(days=min_age_days)).isoformat() if min_age_days else None
    cutoff_max = (_now() - timedelta(days=max_age_days)).isoformat() if max_age_days else None

    for t, coll, urlkey in COLLS:
        if asset_type and asset_type != t:
            continue
        q: dict = {}
        if lifecycle_status:
            # Treat missing field as "live" (legacy assets).
            if lifecycle_status == "live":
                q["$or"] = [{"lifecycle_status": "live"}, {"lifecycle_status": {"$exists": False}}]
            else:
                q["lifecycle_status"] = lifecycle_status
        if cutoff_min:
            q["created_at"] = {**(q.get("created_at") or {}), "$lte": cutoff_min}
        if cutoff_max:
            q["created_at"] = {**(q.get("created_at") or {}), "$gte": cutoff_max}
        docs = await db[coll].find(q, {"_id": 0}).sort("created_at", -1).to_list(int(limit))
        for d in docs:
            order = await db.orders.find_one(
                {"id": d["order_id"]},
                {"_id": 0, "status": 1, "user_id": 1, "bundle_reservation": 1},
            ) or {}
            if order_status and order.get("status") != order_status:
                continue
            if user_id and order.get("user_id") != user_id:
                continue
            user = None
            if order.get("user_id"):
                user = await db.users.find_one({"id": order["user_id"]}, {"_id": 0, "email": 1})
            created = d.get("created_at") or _now_iso()
            try:
                age = (_now() - datetime.fromisoformat(created)).days
            except Exception:
                age = 0
            rows.append({
                "asset_type":        t,
                "asset_id":          d["id"],
                "order_id":          d["order_id"],
                "order_status":      order.get("status"),
                "user_id":           order.get("user_id"),
                "user_email":        (user or {}).get("email"),
                "file_url":          d.get(urlkey),
                "lifecycle_status":  d.get("lifecycle_status") or "live",
                "created_at":        created,
                "archived_at":       d.get("archived_at"),
                "purged_at":         d.get("purged_at"),
                "age_days":          age,
                "has_active_bundle": (order.get("bundle_reservation") or {}).get("status") in ("reserved", "consumed"),
            })
    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[: int(limit)]


# ---------------------------------------------------------------------------
# Lifecycle actions (idempotent, audited, guarded)
# ---------------------------------------------------------------------------
async def _load(asset_type: str, asset_id: str) -> tuple[str, dict | None, str]:
    coll, urlkey = _coll_for(asset_type)
    doc = await db[coll].find_one({"id": asset_id}, {"_id": 0})
    return coll, doc, urlkey


async def _is_protected(asset: dict, cfg: dict) -> tuple[bool, str]:
    """Return (protected, reason). Used both by guards and by preview."""
    order = await db.orders.find_one({"id": asset["order_id"]}, {"_id": 0}) or {}
    status = order.get("status")
    if status in ("assembling", "media_failed"):
        return True, f"order in non-terminal state ({status})"
    bres = (order.get("bundle_reservation") or {}).get("status")
    if cfg.get("protect_active_bundle_orders") and bres in ("reserved",):
        return True, "active bundle reservation"
    # Recently delivered protection
    pdays = int(cfg.get("protect_recent_delivered_days", 30))
    delivered_at = None
    for t in (order.get("status_history") or []):
        if t.get("to_status") == "delivered":
            delivered_at = t.get("at")
            break
    if delivered_at and pdays > 0:
        try:
            age = (_now() - datetime.fromisoformat(delivered_at)).days
            if age < pdays:
                return True, f"delivered only {age}d ago (protection: {pdays}d)"
        except Exception:
            pass
    return False, ""


async def archive_asset(asset_type: str, asset_id: str, *, actor_id: str | None,
                         actor_email: str | None, force: bool = False) -> dict:
    coll, doc, _ = await _load(asset_type, asset_id)
    if not doc:
        return {"ok": False, "reason": "not-found"}
    if doc.get("lifecycle_status") == "archived":
        return {"ok": True, "reason": "already-archived", "asset_id": asset_id}
    if doc.get("lifecycle_status") == "purged":
        return {"ok": False, "reason": "asset-purged"}
    cfg = await get_retention_config()
    if not force:
        protected, why = await _is_protected(doc, cfg)
        if protected:
            return {"ok": False, "reason": f"protected:{why}", "needs_force": True}
        # Min age gate.
        try:
            age = (_now() - datetime.fromisoformat(doc.get("created_at") or _now_iso())).days
        except Exception:
            age = 999
        if age < int(cfg.get("min_age_for_archive_days", 0)):
            return {"ok": False, "reason": f"too-young:{age}d<{cfg['min_age_for_archive_days']}d", "needs_force": True}
    update = {
        "lifecycle_status":         "archived",
        "archived_at":              _now_iso(),
        "archived_by":              actor_id,
    }
    await db[coll].update_one({"id": asset_id}, {"$set": update})
    after = await db[coll].find_one({"id": asset_id}, {"_id": 0})
    await record_audit(
        entity_type="pricing_config", entity_id=asset_id, action="update",
        actor_id=actor_id, actor_email=actor_email,
        summary=f"archive {asset_type} asset {asset_id[:8]}",
        before={"lifecycle_status": doc.get("lifecycle_status") or "live"},
        after={"lifecycle_status": "archived"},
        metadata={"asset_type": asset_type, "asset_id": asset_id, "order_id": doc["order_id"], "wave4_action": "archive", "forced": force},
    )
    return {"ok": True, "asset_id": asset_id, "after": after}


async def restore_asset(asset_type: str, asset_id: str, *, actor_id: str | None,
                         actor_email: str | None) -> dict:
    coll, doc, _ = await _load(asset_type, asset_id)
    if not doc:
        return {"ok": False, "reason": "not-found"}
    if doc.get("lifecycle_status") in (None, "live"):
        return {"ok": True, "reason": "already-live", "asset_id": asset_id}
    if doc.get("lifecycle_status") == "purged":
        return {"ok": False, "reason": "asset-purged-cannot-restore"}
    await db[coll].update_one(
        {"id": asset_id},
        {"$set": {"lifecycle_status": "live", "restored_at": _now_iso(), "restored_by": actor_id},
         "$unset": {"archived_at": "", "archived_by": ""}},
    )
    await record_audit(
        entity_type="pricing_config", entity_id=asset_id, action="update",
        actor_id=actor_id, actor_email=actor_email,
        summary=f"restore {asset_type} asset {asset_id[:8]}",
        before={"lifecycle_status": doc.get("lifecycle_status")},
        after={"lifecycle_status": "live"},
        metadata={"asset_type": asset_type, "asset_id": asset_id, "wave4_action": "restore"},
    )
    return {"ok": True, "asset_id": asset_id}


async def purge_asset(asset_type: str, asset_id: str, *, actor_id: str | None,
                       actor_email: str | None, force: bool = False) -> dict:
    coll, doc, urlkey = await _load(asset_type, asset_id)
    if not doc:
        return {"ok": False, "reason": "not-found"}
    if doc.get("lifecycle_status") == "purged":
        return {"ok": True, "reason": "already-purged"}
    cfg = await get_retention_config()
    # Guard: must be archived first (unless forced).
    if not force:
        if doc.get("lifecycle_status") != "archived":
            return {"ok": False, "reason": "must-archive-first", "needs_force": True}
        try:
            arch_age = (_now() - datetime.fromisoformat(doc.get("archived_at") or _now_iso())).days
        except Exception:
            arch_age = 0
        min_arch = int(cfg.get("min_archived_days_before_purge", 0))
        if arch_age < min_arch:
            return {"ok": False, "reason": f"archived-only-{arch_age}d<{min_arch}d", "needs_force": True}
        protected, why = await _is_protected(doc, cfg)
        if protected:
            return {"ok": False, "reason": f"protected:{why}", "needs_force": True}
    await db[coll].update_one(
        {"id": asset_id},
        {"$set": {
            "lifecycle_status":     "purged",
            "purged_at":            _now_iso(),
            "purged_by":            actor_id,
            urlkey:                 None,
            f"{urlkey}_pre_purge":  doc.get(urlkey),  # bookkeeping only
            "thumbnail_url":        None if asset_type == "video" else doc.get("thumbnail_url"),
        }},
    )
    await record_audit(
        entity_type="pricing_config", entity_id=asset_id, action="delete",
        actor_id=actor_id, actor_email=actor_email,
        summary=f"purge {asset_type} asset {asset_id[:8]}",
        before={"lifecycle_status": doc.get("lifecycle_status"), "url_present": bool(doc.get(urlkey))},
        after={"lifecycle_status": "purged", "url_present": False},
        metadata={"asset_type": asset_type, "asset_id": asset_id, "order_id": doc["order_id"], "wave4_action": "purge", "forced": force},
    )
    return {"ok": True, "asset_id": asset_id}


# ---------------------------------------------------------------------------
# Retention enforcement: preview + apply
# ---------------------------------------------------------------------------
async def preview_retention(cfg: dict | None = None) -> dict:
    """Compute (without applying) which assets would be archived/purged now."""
    cfg = cfg or await get_retention_config()
    archive_thr = int(cfg.get("auto_archive_after_delivered_days", 30))
    purge_thr   = int(cfg.get("auto_purge_after_archived_days", 60))
    rows = await list_assets(limit=2000)
    to_archive: list[dict] = []
    to_purge:   list[dict] = []
    skipped:    list[dict] = []

    for r in rows:
        protected = False
        reason = ""
        order = await db.orders.find_one({"id": r["order_id"]}, {"_id": 0}) or {}
        order_status = order.get("status")
        bres = (order.get("bundle_reservation") or {}).get("status")
        # Active bundle protection
        if cfg.get("protect_active_bundle_orders") and bres in ("reserved",):
            protected, reason = True, "active bundle"
        # Non-terminal order
        if order_status in ("assembling", "media_failed"):
            protected, reason = True, f"order:{order_status}"
        # Recent delivered
        if not protected and order_status == "delivered":
            delivered_at = None
            for t in (order.get("status_history") or []):
                if t.get("to_status") == "delivered":
                    delivered_at = t.get("at")
                    break
            if delivered_at:
                try:
                    days_since_delivered = (_now() - datetime.fromisoformat(delivered_at)).days
                    if days_since_delivered < int(cfg.get("protect_recent_delivered_days", 30)):
                        protected, reason = True, f"delivered<{cfg['protect_recent_delivered_days']}d"
                except Exception:
                    pass
        if r["lifecycle_status"] == "live":
            if protected:
                skipped.append({**r, "reason": reason, "matched_rule": "protect"})
                continue
            # Archive eligibility: order delivered + age >= threshold
            if order_status == "delivered" and r["age_days"] >= archive_thr:
                to_archive.append({**r, "matched_rule": f"auto_archive ({archive_thr}d delivered)"})
        elif r["lifecycle_status"] == "archived":
            if protected:
                skipped.append({**r, "reason": reason, "matched_rule": "protect"})
                continue
            try:
                arch_age = (_now() - datetime.fromisoformat(r.get("archived_at") or _now_iso())).days
            except Exception:
                arch_age = 0
            if arch_age >= purge_thr:
                to_purge.append({**r, "archived_age_days": arch_age,
                                 "matched_rule": f"auto_purge ({purge_thr}d archived)"})
    return {
        "to_archive_count": len(to_archive),
        "to_purge_count":   len(to_purge),
        "skipped_count":    len(skipped),
        "to_archive":       to_archive[:200],
        "to_purge":         to_purge[:200],
        "skipped":          skipped[:50],
        "config":           cfg,
        "computed_at":      _now_iso(),
    }


async def enforce_retention(*, actor_id: str | None, actor_email: str | None) -> dict:
    """Apply the retention policy NOW. Idempotent — re-runs are safe."""
    plan = await preview_retention()
    archived = 0
    purged = 0
    failures: list[dict] = []
    for r in plan["to_archive"]:
        res = await archive_asset(r["asset_type"], r["asset_id"],
                                   actor_id=actor_id, actor_email=actor_email)
        if res.get("ok"):
            archived += 1
        else:
            failures.append({"asset_id": r["asset_id"], "kind": "archive", "reason": res.get("reason")})
    for r in plan["to_purge"]:
        res = await purge_asset(r["asset_type"], r["asset_id"],
                                 actor_id=actor_id, actor_email=actor_email)
        if res.get("ok"):
            purged += 1
        else:
            failures.append({"asset_id": r["asset_id"], "kind": "purge", "reason": res.get("reason")})
    summary = {
        "id":              str(uuid.uuid4()),
        "archived_count":  archived,
        "purged_count":    purged,
        "failed_count":    len(failures),
        "failures":        failures[:50],
        "ran_at":          _now_iso(),
        "ran_by":          actor_id,
    }
    await db.retention_runs.insert_one(summary)
    summary.pop("_id", None)
    await record_audit(
        entity_type="pricing_config", entity_id="retention_policy",
        action="config_change", actor_id=actor_id, actor_email=actor_email,
        summary=f"retention enforce: archived={archived} purged={purged} failed={len(failures)}",
        metadata={"wave4_action": "retention_enforce"},
    )
    return summary
