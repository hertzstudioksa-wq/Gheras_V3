"""Payments (M6): the parent pays the price quoted for their story, from wallet
credit or by card through Moyasar; wallet top-ups are bought the same way.

Flow: after the parent picks a scenario, `gate_production` either starts
production (payment not required, order already paid, or an older per-story
bundle credit covers it) or parks the order in `awaiting_payment` with the
amount to pay. Paying — wallet debit, a Moyasar invoice confirmed by fetching it
back, or an admin waiver — runs `mark_order_paid`, which moves the order on to
production exactly once.

Amounts: the order's `price_quote` (what the parent saw in the builder) plus
VAT at the current rate. Prices are never taken from the browser.
Wallet top-ups carry no VAT; VAT is charged when credit buys a story.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from db import db
from models import OrderStatus
from services import moyasar, wallet_service
from services.audit_service import record_audit

logger = logging.getLogger("payment_service")

SETTINGS_DOC_ID = "default"
DEFAULT_PAYMENT_SETTINGS: dict = {
    "id": SETTINGS_DOC_ID,
    "payment_required": False,  # off: production starts without payment (testing)
    "updated_at": None,
    "updated_by": None,
}
REUSE_INVOICE_FOR = timedelta(minutes=50)
METHOD_LABELS = {"wallet": "الرصيد", "card": "بطاقة (ميسر)", "bundle_credit": "باقة قديمة", "admin": "مجاناً (الإدارة)"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Settings + status
# =============================================================================
async def get_payment_settings() -> dict:
    doc = await db.payment_settings.find_one({"id": SETTINGS_DOC_ID}, {"_id": 0}) or {}
    return {**DEFAULT_PAYMENT_SETTINGS, **{k: doc[k] for k in DEFAULT_PAYMENT_SETTINGS if k in doc}}


async def update_payment_settings(patch: dict, admin: dict) -> dict:
    if set(patch or {}) - {"payment_required"}:
        raise ValueError("إعداد غير معروف")
    required = bool(patch.get("payment_required"))
    if required and not await moyasar.secret_key():
        raise ValueError("سجّل مفتاح ميسر الأول من صفحة المفاتيح — من غيره مفيش دفع بالبطاقة")
    before = await get_payment_settings()
    await db.payment_settings.update_one(
        {"id": SETTINGS_DOC_ID},
        {"$set": {"payment_required": required, "updated_at": _now(), "updated_by": admin.get("email")},
         "$setOnInsert": {"id": SETTINGS_DOC_ID}},
        upsert=True,
    )
    await record_audit(entity_type="payment_settings", entity_id=SETTINGS_DOC_ID, action="config_change",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary="الدفع قبل الإنتاج: " + ("مطلوب" if required else "مش مطلوب"),
                       before={"payment_required": before["payment_required"]},
                       after={"payment_required": required})
    return await get_payment_settings()


async def payment_required() -> bool:
    return bool((await get_payment_settings()).get("payment_required"))


async def get_provider_status() -> dict:
    key = await moyasar.secret_key()
    return {
        "provider": "moyasar",
        "configured": bool(key),
        "mode": moyasar.key_mode(key),
        "key_masked": f"***{key[-4:]}" if key and len(key) >= 8 else None,
        "payment_required": await payment_required(),
        "callback_url": callback_url(),
        "app_url": os.environ.get("PUBLIC_APP_URL") or None,
    }


def callback_url() -> str | None:
    """Moyasar POSTs paid invoices here; only a public https API can receive it.
    Without it the payment is confirmed when the parent comes back to the site."""
    base = (os.environ.get("PUBLIC_API_URL") or "").rstrip("/")
    return f"{base}/api/webhook/moyasar" if base.startswith("https://") else None


def app_origin(request_origin: str | None) -> str:
    return (os.environ.get("PUBLIC_APP_URL") or request_origin or "").rstrip("/")


# =============================================================================
# Order amounts + gate
# =============================================================================
async def order_amounts(order: dict) -> dict:
    """The pre-VAT price the parent was quoted, plus VAT at today's rate."""
    from services import story_pricing

    quote = order.get("price_quote")
    if not quote:  # orders from before quotes existed
        duration = (order.get("duration") or {}).get("seconds") or 60
        delivery = (order.get("data") or {}).get("delivery") or {}
        quote = await story_pricing.current_quote(duration, delivery.get("output_type") or "both",
                                                  delivery.get("video_tier") or "balanced")
    price = float(quote["price_sar"])
    vat = story_pricing.with_vat(price, await story_pricing.get_settings())
    return {"amount_sar": price, "vat_rate": vat["vat_rate"], "vat_sar": vat["vat_sar"], "total_sar": vat["total_sar"]}


async def _start_production(order_id: str, background, reason: str) -> bool:
    """Planning starts once per order: only the request that moves it to
    ready_for_ai triggers the run (double taps and concurrent payments lose)."""
    from routes.production_routes import trigger_production_planning
    from services.order_state import PLANNING_STARTABLE, claim

    if not await claim(order_id, PLANNING_STARTABLE, OrderStatus.READY_FOR_AI.value, "system", reason=reason):
        return False
    await trigger_production_planning(order_id, background)
    return True


async def gate_production(order_id: str, background) -> dict:
    """After the parent picks a scenario: start production, or wait for payment."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    status = order.get("status")
    if (order.get("payment") or {}).get("status") == "paid" or not await payment_required():
        await _start_production(order_id, background, "auto after selection")
        return {"next": "production"}

    # An older per-story bundle credit still pays for a story.
    from models import get_order_output_type
    from services.bundle_service import reserve_for_order
    reserved = await reserve_for_order(user_id=order["user_id"], order_id=order_id,
                                       output_type=get_order_output_type(order))
    amounts = await order_amounts(order)
    if reserved.get("ok"):
        await db.orders.update_one({"id": order_id}, {"$set": {"payment": {
            **amounts, "status": "paid", "method": "bundle_credit", "paid_at": _now(),
            "bundle_purchase_id": reserved.get("bundle_purchase_id")}}})
        await _start_production(order_id, background, "paid with bundle credit")
        return {"next": "production"}

    from services.order_state import claim
    if status != OrderStatus.AWAITING_PAYMENT.value:
        await claim(order_id, (OrderStatus.SCENARIO_SELECTED.value,), OrderStatus.AWAITING_PAYMENT.value, "system",
                    reason=f"awaiting payment {amounts['total_sar']} SAR",
                    extra={"payment": {**amounts, "status": "awaiting"}})
    return {"next": "payment", **amounts}


async def mark_order_paid(order_id: str, *, method: str, background, payment_id: str | None = None,
                          actor: dict | None = None, note: str | None = None) -> bool:
    """Record the payment and move a waiting order to production. Returns False
    if the order was already paid (nothing changes)."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return False
    current = order.get("payment") or {}
    amounts = {k: current[k] for k in ("amount_sar", "vat_rate", "vat_sar", "total_sar") if k in current} \
        or await order_amounts(order)
    if method == "admin":
        amounts = {**amounts, "amount_sar": 0, "vat_sar": 0, "total_sar": 0, "quoted_total_sar": amounts["total_sar"]}
    payment = {**amounts, "status": "paid", "method": method, "payment_id": payment_id,
               "paid_at": _now(), "note": note}
    res = await db.orders.update_one({"id": order_id, "payment.status": {"$ne": "paid"}},
                                     {"$set": {"payment": payment}})
    if not res.modified_count:
        return False
    await record_audit(entity_type="order", entity_id=order_id,
                       action="payment.waived" if method == "admin" else "payment.paid",
                       actor_id=(actor or {}).get("id"), actor_email=(actor or {}).get("email"),
                       summary=f"دفع الطلب — {METHOD_LABELS.get(method, method)} {payment['total_sar']} ر.س"
                               + (f" — {note}" if note else ""),
                       metadata={"payment_id": payment_id})
    if order.get("status") == OrderStatus.AWAITING_PAYMENT.value:
        await _start_production(order_id, background, f"paid ({method})")
    return True


async def pay_order_with_wallet(order: dict, user: dict, background) -> dict:
    payment = order.get("payment") or {}
    if payment.get("status") != "awaiting":
        raise ValueError("الطلب مش مستني دفع")
    amount = wallet_service.to_halalas(payment["total_sar"])
    debit = await wallet_service.debit(user["id"], amount, "order_charge", order_id=order["id"], actor=user,
                                       note=f"قصة {((order.get('data') or {}).get('child') or {}).get('name') or ''}".strip())
    if not debit["ok"]:
        raise ValueError(f"رصيدك {debit['balance_halalas'] / 100:.2f} ر.س — مش كفاية")
    if not await mark_order_paid(order["id"], method="wallet", background=background, actor=user):
        # Paid some other way meanwhile: give the credit back.
        await wallet_service.credit(user["id"], amount, "refund", note="دفعة مكررة", order_id=order["id"],
                                    idem_key=f"dup-wallet:{order['id']}")
    return {"ok": True, "balance_halalas": await wallet_service.balance(user["id"])}


# =============================================================================
# Moyasar checkouts
# =============================================================================
async def _new_payment(*, purpose: str, user: dict, total_sar: float, description: str, success_url: str,
                       back_url: str, order_id: str | None = None, bundle: dict | None = None) -> dict:
    payment_id = str(uuid.uuid4())
    amount_halalas = wallet_service.to_halalas(total_sar)
    invoice = await moyasar.create_invoice(
        amount_halalas=amount_halalas, description=description,
        success_url=success_url.replace("{pid}", payment_id), back_url=back_url,
        callback_url=callback_url(),
        metadata={"payment_id": payment_id, "purpose": purpose, "order_id": order_id or "", "user_id": user["id"]},
    )
    doc = {
        "id": payment_id, "purpose": purpose, "provider": "moyasar",
        "user_id": user["id"], "user_email": user.get("email"),
        "order_id": order_id, "bundle_id": (bundle or {}).get("id"),
        "bundle_snapshot": bundle, "amount_sar": round(total_sar, 2), "amount_halalas": amount_halalas,
        "currency": "SAR", "status": "pending", "invoice_id": invoice["id"], "invoice_url": invoice["url"],
        "mode": moyasar.key_mode(await moyasar.secret_key()),
        "created_at": _now(), "updated_at": _now(),
    }
    await db.payments.insert_one(doc)
    doc.pop("_id", None)
    await record_audit(entity_type="payment", entity_id=payment_id, action="create",
                       actor_id=user["id"], actor_email=user.get("email"),
                       summary=f"فاتورة ميسر {purpose} {doc['amount_sar']} ر.س",
                       metadata={"invoice_id": invoice["id"], "order_id": order_id})
    return doc


async def start_order_checkout(order: dict, user: dict, origin: str | None, background) -> dict:
    payment = order.get("payment") or {}
    if payment.get("status") != "awaiting":
        raise ValueError("الطلب مش مستني دفع")
    # A parent who already paid an earlier invoice must not pay twice.
    for p in await db.payments.find({"order_id": order["id"], "status": "pending"}, {"_id": 0}).to_list(10):
        p = await refresh_payment(p, background)
        if p["status"] == "paid":
            return {"paid": True}
        fresh = datetime.fromisoformat(p["created_at"]) > datetime.now(timezone.utc) - REUSE_INVOICE_FOR
        if p["status"] == "pending" and fresh and abs(p["amount_sar"] - payment["total_sar"]) < 0.01:
            return {"url": p["invoice_url"], "payment_id": p["id"]}
    base = app_origin(origin)
    child = ((order.get("data") or {}).get("child") or {}).get("name") or ""
    doc = await _new_payment(
        purpose="order", user=user, total_sar=payment["total_sar"], order_id=order["id"],
        description=f"غِراس — قصة {child} ({order['id'][:8]})",
        success_url=f"{base}/orders/{order['id']}/production-ready?payment={{pid}}",
        back_url=f"{base}/orders/{order['id']}/production-ready",
    )
    return {"url": doc["invoice_url"], "payment_id": doc["id"]}


async def start_topup_checkout(bundle_id: str, user: dict, origin: str | None) -> dict:
    bundle = await db.bundles.find_one({"id": bundle_id, "is_active": True, "credit_sar": {"$gt": 0}}, {"_id": 0})
    if not bundle:
        raise LookupError("الباقة مش متاحة")
    base = app_origin(origin)
    doc = await _new_payment(
        purpose="topup", user=user, total_sar=float(bundle["price"]), bundle=bundle,
        description=f"غِراس — {bundle['name']}",
        success_url=f"{base}/my-bundles?payment={{pid}}", back_url=f"{base}/my-bundles",
    )
    return {"url": doc["invoice_url"], "payment_id": doc["id"]}


async def refresh_payment(payment: dict, background) -> dict:
    """Ask Moyasar for the invoice and settle the payment if it is paid."""
    if payment.get("status") != "pending":
        return payment
    invoice = await moyasar.fetch_invoice(payment["invoice_id"])
    status = invoice.get("status")
    if status == moyasar.PAID:
        if int(invoice.get("amount") or 0) != payment["amount_halalas"] or invoice.get("currency") != "SAR":
            await db.payments.update_one({"id": payment["id"]}, {"$set": {
                "status": "mismatch", "updated_at": _now(),
                "provider_amount": invoice.get("amount"), "provider_currency": invoice.get("currency")}})
            logger.error(f"[payments] amount mismatch on {payment['id']}: {invoice.get('amount')} {invoice.get('currency')}")
        else:
            await _settle(payment, invoice, background)
    elif status in moyasar.CLOSED:
        await db.payments.update_one({"id": payment["id"], "status": "pending"},
                                     {"$set": {"status": status, "updated_at": _now()}})
    return await db.payments.find_one({"id": payment["id"]}, {"_id": 0})


async def _settle(payment: dict, invoice: dict, background) -> None:
    paid_attempt = next((p for p in invoice.get("payments") or [] if p.get("status") == "paid"), {})
    res = await db.payments.update_one(
        {"id": payment["id"], "status": "pending"},
        {"$set": {"status": "paid", "paid_at": _now(), "updated_at": _now(),
                  "provider_payment_id": paid_attempt.get("id"),
                  "source": (paid_attempt.get("source") or {}).get("company") or (paid_attempt.get("source") or {}).get("type")}},
    )
    if not res.modified_count:
        return  # settled by a concurrent callback / poll
    user = {"id": payment["user_id"], "email": payment.get("user_email")}
    if payment["purpose"] == "order":
        if not await mark_order_paid(payment["order_id"], method="card", payment_id=payment["id"],
                                     background=background, actor=user):
            # The order was paid another way first: keep the money as wallet credit.
            await wallet_service.credit(payment["user_id"], payment["amount_halalas"], "refund",
                                        note="دفعة مكررة بالبطاقة أُضيفت إلى رصيدك", order_id=payment["order_id"],
                                        payment_id=payment["id"], idem_key=f"dup:{payment['id']}")
    elif payment["purpose"] == "topup":
        bundle = payment.get("bundle_snapshot") or {}
        paid = payment["amount_halalas"]
        credit = wallet_service.to_halalas(bundle.get("credit_sar") or payment["amount_sar"])
        await wallet_service.credit(payment["user_id"], paid, "topup", note=bundle.get("name", ""),
                                    payment_id=payment["id"], idem_key=f"topup:{payment['id']}")
        if credit > paid:
            await wallet_service.credit(payment["user_id"], credit - paid, "bonus", note=bundle.get("name", ""),
                                        payment_id=payment["id"], idem_key=f"bonus:{payment['id']}")


async def handle_callback(body: dict, background) -> dict:
    """Moyasar's POST when an invoice is paid. The body only tells us which
    invoice to look at; the status comes from fetching it with our key."""
    invoice_id = body.get("invoice_id") or (body.get("data") or {}).get("invoice_id") or body.get("id")
    payment = await db.payments.find_one({"invoice_id": invoice_id}, {"_id": 0}) if invoice_id else None
    if not payment:
        return {"ok": False, "reason": "unknown invoice"}
    payment = await refresh_payment(payment, background)
    return {"ok": True, "status": payment["status"]}


# =============================================================================
# Admin actions
# =============================================================================
async def refund_order_to_wallet(order: dict, admin: dict, reason: str) -> dict:
    payment = order.get("payment") or {}
    if payment.get("status") != "paid" or payment.get("method") not in ("wallet", "card"):
        raise ValueError("الاسترداد للرصيد متاح للطلبات المدفوعة بالرصيد أو البطاقة بس")
    amount = wallet_service.to_halalas(payment["total_sar"])
    await wallet_service.credit(order["user_id"], amount, "refund", note=reason, order_id=order["id"],
                                actor=admin, idem_key=f"refund:{order['id']}")
    await db.orders.update_one({"id": order["id"]}, {"$set": {"payment.status": "refunded",
                                                              "payment.refunded_at": _now(),
                                                              "payment.refund_reason": reason}})
    await record_audit(entity_type="order", entity_id=order["id"], action="payment.refund",
                       actor_id=admin.get("id"), actor_email=admin.get("email"),
                       summary=f"استرداد {payment['total_sar']} ر.س للرصيد — {reason}")
    return {"ok": True}
