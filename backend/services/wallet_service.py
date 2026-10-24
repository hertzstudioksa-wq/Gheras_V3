"""Customer wallet (M6): SAR credit bought in top-ups (with a bonus), spent on
stories, refunded by the admin.

Amounts are halalas (1 SAR = 100). Every change is a `wallet_ledger` row;
`wallets.balance_halalas` is the running total. A debit only happens when the
balance covers it (conditional $inc), and credits carry an `idem_key` (e.g. the
payment id) so a paid top-up can never be credited twice.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pymongo.errors import DuplicateKeyError

from db import db
from services.audit_service import record_audit

KIND_LABELS = {
    "topup": "شحن رصيد",
    "bonus": "هدية شحن",
    "order_charge": "دفع قصة",
    "refund": "استرداد",
    "adjust": "تعديل من الإدارة",
}
AUDIT_ACTION = {"topup": "wallet.topup", "bonus": "wallet.topup", "refund": "wallet.refund", "adjust": "wallet.adjust"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_halalas(sar: float) -> int:
    return int(round(float(sar) * 100))


async def balance(user_id: str) -> int:
    w = await db.wallets.find_one({"user_id": user_id}, {"_id": 0, "balance_halalas": 1})
    return int((w or {}).get("balance_halalas") or 0)


async def _ledger(user_id: str, amount: int, kind: str, *, note: str, idem_key: str | None,
                  order_id: str | None, payment_id: str | None, actor: dict | None,
                  balance_after: int | None = None) -> dict:
    row = {
        "id": str(uuid.uuid4()), "user_id": user_id, "amount_halalas": int(amount), "kind": kind,
        "note": note, "order_id": order_id, "payment_id": payment_id, "balance_after": balance_after,
        "actor_email": (actor or {}).get("email"), "created_at": _now(),
    }
    if idem_key:
        row["idem_key"] = idem_key
    await db.wallet_ledger.insert_one(row)
    row.pop("_id", None)
    return row


async def credit(user_id: str, amount: int, kind: str, *, note: str = "", idem_key: str | None = None,
                 order_id: str | None = None, payment_id: str | None = None, actor: dict | None = None) -> dict:
    """Add credit. Returns {"ok": True, "applied": False} if `idem_key` was used before."""
    if amount <= 0:
        raise ValueError("المبلغ لازم يكون أكبر من صفر")
    try:
        row = await _ledger(user_id, amount, kind, note=note, idem_key=idem_key,
                            order_id=order_id, payment_id=payment_id, actor=actor)
    except DuplicateKeyError:
        return {"ok": True, "applied": False}
    await db.wallets.update_one({"user_id": user_id},
                                {"$inc": {"balance_halalas": int(amount)}, "$set": {"updated_at": _now()},
                                 "$setOnInsert": {"user_id": user_id}}, upsert=True)
    bal = await balance(user_id)
    await db.wallet_ledger.update_one({"id": row["id"]}, {"$set": {"balance_after": bal}})
    await record_audit(entity_type="wallet", entity_id=user_id, action=AUDIT_ACTION.get(kind, "wallet.adjust"),
                       actor_id=(actor or {}).get("id"), actor_email=(actor or {}).get("email"),
                       summary=f"{KIND_LABELS.get(kind, kind)} +{amount / 100:.2f} ر.س — {note}".strip(" —"),
                       metadata={"order_id": order_id, "payment_id": payment_id, "balance_after": bal})
    return {"ok": True, "applied": True, "balance_halalas": bal}


async def debit(user_id: str, amount: int, kind: str, *, note: str = "", order_id: str | None = None,
                actor: dict | None = None) -> dict:
    """Spend credit if the balance covers it. Returns {"ok": False} otherwise."""
    if amount <= 0:
        raise ValueError("المبلغ لازم يكون أكبر من صفر")
    res = await db.wallets.update_one(
        {"user_id": user_id, "balance_halalas": {"$gte": int(amount)}},
        {"$inc": {"balance_halalas": -int(amount)}, "$set": {"updated_at": _now()}},
    )
    if not res.modified_count:
        return {"ok": False, "reason": "insufficient", "balance_halalas": await balance(user_id)}
    bal = await balance(user_id)
    await _ledger(user_id, -amount, kind, note=note, idem_key=None, order_id=order_id, payment_id=None,
                  actor=actor, balance_after=bal)
    await record_audit(entity_type="wallet", entity_id=user_id, action="wallet.charge",
                       actor_id=(actor or {}).get("id"), actor_email=(actor or {}).get("email"),
                       summary=f"{KIND_LABELS.get(kind, kind)} −{amount / 100:.2f} ر.س — {note}".strip(" —"),
                       metadata={"order_id": order_id, "balance_after": bal})
    return {"ok": True, "balance_halalas": bal}


async def history(user_id: str, limit: int = 50) -> list[dict]:
    rows = await db.wallet_ledger.find({"user_id": user_id}, {"_id": 0, "idem_key": 0}) \
        .sort("created_at", -1).to_list(max(1, min(limit, 200)))
    for r in rows:
        r["kind_ar"] = KIND_LABELS.get(r["kind"], r["kind"])
    return rows
