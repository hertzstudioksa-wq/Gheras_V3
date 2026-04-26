"""Payment service — Wave 3.

Architecture-ready Stripe integration. Endpoints gracefully return 503 when
`STRIPE_API_KEY` is missing.

Design notes:
  * Apple Pay is a CHECKOUT METHOD (selected inside Stripe's Checkout / Payment
    Element on Apple devices when `card` is in `payment_methods`). Settlement
    flows to the merchant's bank account via Stripe Payouts. Apple Pay is NOT
    a payout destination.
  * Bundle prices are read from the BACKEND `bundles` collection — frontend
    never supplies amounts.
  * `payment_settings` (single doc) holds NON-secret values: publishable_key,
    sandbox_mode, supported_methods, supported_currencies, payout_destination_label.
  * Secrets stay in `.env`. Webhook secret is read from env if/when set.
"""
from __future__ import annotations
import logging
import os
import uuid
from datetime import datetime, timezone

from db import db
from services.audit_service import record_audit

logger = logging.getLogger("payment_service")

SETTINGS_DOC_ID = "default"

DEFAULT_PAYMENT_SETTINGS: dict = {
    "id": SETTINGS_DOC_ID,
    "publishable_key":         "",       # safe to store (public)
    "sandbox_mode":            True,
    "supported_methods":       ["card"], # Apple Pay rides on `card` for Stripe
    "supported_currencies":    ["SAR"],
    "payout_destination_label": "حساب التاجر — يُحدّد لاحقاً (ليس Apple Pay)",
    "apple_pay_domain_verified": False,
    "updated_at": None,
    "updated_by": None,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def stripe_secret() -> str | None:
    return (os.environ.get("STRIPE_API_KEY") or "").strip() or None


def is_payment_active() -> bool:
    """The provider is active iff the secret key is present in env."""
    return bool(stripe_secret())


# =============================================================================
# Settings CRUD
# =============================================================================
async def get_payment_settings() -> dict:
    doc = await db.payment_settings.find_one({"id": SETTINGS_DOC_ID}, {"_id": 0})
    if not doc:
        return dict(DEFAULT_PAYMENT_SETTINGS)
    merged = dict(DEFAULT_PAYMENT_SETTINGS)
    merged.update(doc)
    return merged


async def update_payment_settings(patch: dict, admin_id: str | None, admin_email: str | None) -> dict:
    allowed = {
        "publishable_key", "sandbox_mode", "supported_methods",
        "supported_currencies", "payout_destination_label",
        "apple_pay_domain_verified",
    }
    update = {k: v for k, v in (patch or {}).items() if k in allowed}
    update["updated_at"] = _now_iso()
    update["updated_by"] = admin_id
    before = await db.payment_settings.find_one({"id": SETTINGS_DOC_ID}, {"_id": 0})
    await db.payment_settings.update_one(
        {"id": SETTINGS_DOC_ID},
        {"$set": update, "$setOnInsert": {"id": SETTINGS_DOC_ID}},
        upsert=True,
    )
    after = await get_payment_settings()
    await record_audit(
        entity_type="payment_settings", entity_id=SETTINGS_DOC_ID,
        action="config_change", actor_id=admin_id, actor_email=admin_email,
        summary=f"payment settings updated: {sorted(update.keys())}",
        before=before, after=after,
    )
    return after


# =============================================================================
# Provider status (for admin UI)
# =============================================================================
async def get_provider_status() -> dict:
    sk = stripe_secret() or ""
    pk = (await get_payment_settings()).get("publishable_key") or ""
    webhook_secret_env = (os.environ.get("STRIPE_WEBHOOK_SECRET") or "").strip()
    return {
        "active":                    is_payment_active(),
        "secret_key_configured":     bool(sk),
        "secret_key_masked":         (f"***{sk[-4:]}" if len(sk) >= 8 else None),
        "publishable_key_configured": bool(pk),
        "webhook_secret_configured": bool(webhook_secret_env),
        "sandbox_mode":              (await get_payment_settings()).get("sandbox_mode", True),
        "note_ar": (
            "الدفع يعمل فقط عندما يكون STRIPE_API_KEY موجوداً في .env. "
            "Apple Pay طريقة دفع للعميل (يختارها داخل صفحة الدفع)، "
            "وليست وجهة تحويل أرباح. الأرباح تذهب إلى الحساب البنكي للتاجر عبر Stripe Payouts."
        ),
    }


# =============================================================================
# Checkout — bundle purchase
# =============================================================================
async def create_bundle_checkout(
    *,
    bundle_id: str,
    user: dict,
    origin_url: str,
) -> dict:
    """Create a Stripe Checkout Session for buying a bundle.

    Raises RuntimeError if the provider is not configured. Returns:
      {"url": "...", "session_id": "...", "payment_id": "..."}

    Backend resolves the amount/currency from the `bundles` collection;
    frontend NEVER supplies the amount.
    """
    if not is_payment_active():
        raise RuntimeError("payment-not-configured")
    bundle = await db.bundles.find_one({"id": bundle_id, "is_active": True}, {"_id": 0})
    if not bundle:
        raise RuntimeError("bundle-not-found")

    # Lazy import — only loaded when checkout is actually invoked.
    from emergentintegrations.payments.stripe.checkout import (
        StripeCheckout, CheckoutSessionRequest,
    )

    origin = origin_url.rstrip("/")
    success_url = f"{origin}/checkout/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/checkout/cancel"

    settings = await get_payment_settings()
    payment_methods = settings.get("supported_methods") or ["card"]

    payment_id = str(uuid.uuid4())
    metadata = {
        "payment_id":  payment_id,
        "user_id":     user.get("id", ""),
        "user_email":  user.get("email", ""),
        "bundle_id":   bundle_id,
        "bundle_name": bundle.get("name", ""),
        "purpose":     "bundle_purchase",
    }
    request = CheckoutSessionRequest(
        amount=float(bundle["price"]),
        currency=str(bundle.get("currency", "SAR")).lower(),
        success_url=success_url,
        cancel_url=cancel_url,
        metadata=metadata,
        payment_methods=payment_methods,
    )

    sc = StripeCheckout(api_key=stripe_secret(), webhook_url=f"{origin}/api/webhook/stripe")
    session = await sc.create_checkout_session(request)

    payment_doc = {
        "id":           payment_id,
        "user_id":      user.get("id"),
        "user_email":   user.get("email"),
        "bundle_id":    bundle_id,
        "bundle_snapshot": bundle,
        "amount":       float(bundle["price"]),
        "currency":     bundle.get("currency", "SAR"),
        "status":       "pending",
        "payment_status": "unpaid",
        "provider":     "stripe",
        "session_id":   session.session_id,
        "session_url":  session.url,
        "metadata":     metadata,
        "created_at":   _now_iso(),
        "updated_at":   _now_iso(),
    }
    await db.payments.insert_one(payment_doc)
    payment_doc.pop("_id", None)
    await record_audit(
        entity_type="payment", entity_id=payment_id, action="create",
        actor_id=user.get("id"), actor_email=user.get("email"),
        summary=f"checkout session created for bundle '{bundle.get('name')}'",
        after={k: payment_doc[k] for k in ("amount", "currency", "status", "session_id")},
    )
    return {"url": session.url, "session_id": session.session_id, "payment_id": payment_id}


async def poll_checkout_status(session_id: str) -> dict:
    """Refresh local payment status from Stripe.

    Idempotent — if the payment is already `paid` we do NOT re-grant the
    bundle credit. Returns the local payment doc (sanitized).
    """
    if not is_payment_active():
        raise RuntimeError("payment-not-configured")

    payment = await db.payments.find_one({"session_id": session_id}, {"_id": 0})
    if not payment:
        raise RuntimeError("payment-not-found")
    if payment.get("payment_status") == "paid":
        return payment  # already finalized

    from emergentintegrations.payments.stripe.checkout import StripeCheckout
    sc = StripeCheckout(api_key=stripe_secret(), webhook_url="https://example.invalid")
    status = await sc.get_checkout_status(session_id)

    update = {
        "status":         status.status,
        "payment_status": status.payment_status,
        "amount_total":   getattr(status, "amount_total", None),
        "updated_at":     _now_iso(),
    }
    await db.payments.update_one({"session_id": session_id}, {"$set": update})

    if status.payment_status == "paid":
        await _finalize_paid_payment(session_id)

    payment = await db.payments.find_one({"session_id": session_id}, {"_id": 0})
    return payment


async def _finalize_paid_payment(session_id: str) -> None:
    """Idempotently mark a payment as paid and grant the bundle purchase."""
    payment = await db.payments.find_one({"session_id": session_id}, {"_id": 0})
    if not payment:
        return
    if payment.get("bundle_purchase_id"):
        return  # already granted — do NOT double-credit

    from services.bundle_service import grant_purchase_to_user
    user = await db.users.find_one({"id": payment["user_id"]}, {"_id": 0, "email": 1})
    purchase = await grant_purchase_to_user(
        user_id=payment["user_id"],
        bundle_id=payment["bundle_id"],
        granted_by=None,
        granted_by_email=user.get("email") if user else None,
        payment_id=payment["id"],
        price_paid=payment.get("amount"),
        reason="auto-grant via Stripe payment",
    )
    if purchase:
        await db.payments.update_one(
            {"id": payment["id"]},
            {"$set": {"bundle_purchase_id": purchase["id"], "updated_at": _now_iso()}},
        )
        await record_audit(
            entity_type="payment", entity_id=payment["id"], action="update",
            actor_id=payment["user_id"], actor_email=payment.get("user_email"),
            summary="payment finalized → bundle granted",
            metadata={"bundle_purchase_id": purchase["id"]},
        )


# =============================================================================
# Webhook
# =============================================================================
async def handle_stripe_webhook(body_bytes: bytes, stripe_signature: str | None) -> dict:
    if not is_payment_active():
        raise RuntimeError("payment-not-configured")
    from emergentintegrations.payments.stripe.checkout import StripeCheckout
    sc = StripeCheckout(api_key=stripe_secret(), webhook_url="https://example.invalid")
    response = await sc.handle_webhook(body_bytes, stripe_signature)
    sid = getattr(response, "session_id", None)
    pstatus = getattr(response, "payment_status", None)
    if sid and pstatus == "paid":
        await _finalize_paid_payment(sid)
    return {"event_type": getattr(response, "event_type", None), "session_id": sid}
