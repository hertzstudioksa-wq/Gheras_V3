"""Payment routes — Wave 3 (admin settings + checkout + webhook).

The user-facing checkout endpoint and the Stripe webhook gracefully return
HTTP 503 when STRIPE_API_KEY is not configured.
"""
from fastapi import APIRouter, Depends, HTTPException, Request

from auth import require_admin, get_current_user
from db import db
from services.payment_service import (
    get_payment_settings, update_payment_settings, get_provider_status,
    create_bundle_checkout, poll_checkout_status, handle_stripe_webhook,
    is_payment_active,
)


# ---- Admin ------------------------------------------------------------------
admin_router = APIRouter(
    prefix="/admin/payment",
    tags=["admin-payment"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get("/settings")
async def admin_get_settings():
    return await get_payment_settings()


@admin_router.put("/settings")
async def admin_update_settings(payload: dict, admin=Depends(require_admin)):
    return await update_payment_settings(
        payload, admin_id=admin.get("id"), admin_email=admin.get("email"),
    )


@admin_router.get("/status")
async def admin_provider_status():
    return await get_provider_status()


@admin_router.get("/payments")
async def admin_list_payments(status: str | None = None, user_id: str | None = None, limit: int = 100):
    q: dict = {}
    if status:
        q["status"] = status
    if user_id:
        q["user_id"] = user_id
    rows = await db.payments.find(q, {"_id": 0}).sort("created_at", -1).to_list(int(limit))
    return {"payments": rows, "count": len(rows)}


# ---- Customer checkout -------------------------------------------------------
checkout_router = APIRouter(
    prefix="/checkout",
    tags=["checkout"],
)


@checkout_router.post("/bundle/{bundle_id}")
async def start_bundle_checkout(bundle_id: str, request: Request, current=Depends(get_current_user)):
    if not is_payment_active():
        raise HTTPException(
            status_code=503,
            detail="الدفع غير مفعّل بعد. الرجاء التواصل مع الإدارة لتفعيل المزوّد.",
        )
    # Frontend supplies origin via the standard X-Origin header or falls back
    # to request URL; amounts are NEVER taken from the frontend.
    origin = request.headers.get("X-Origin") or request.headers.get("Origin") or str(request.base_url).rstrip("/")
    try:
        result = await create_bundle_checkout(
            bundle_id=bundle_id, user=current, origin_url=origin,
        )
    except RuntimeError as e:
        msg = str(e)
        if msg == "bundle-not-found":
            raise HTTPException(404, "الباقة غير متوفرة")
        if msg == "payment-not-configured":
            raise HTTPException(503, "الدفع غير مفعّل بعد")
        raise HTTPException(400, msg)
    return result


@checkout_router.get("/status/{session_id}")
async def get_status(session_id: str, current=Depends(get_current_user)):
    if not is_payment_active():
        raise HTTPException(503, "الدفع غير مفعّل بعد")
    try:
        payment = await poll_checkout_status(session_id)
    except RuntimeError as e:
        if str(e) == "payment-not-found":
            raise HTTPException(404, "العملية غير موجودة")
        raise HTTPException(400, str(e))
    # Restrict to the owner.
    if payment.get("user_id") != current.get("id"):
        raise HTTPException(403, "غير مصرّح")
    return {
        "status":         payment.get("status"),
        "payment_status": payment.get("payment_status"),
        "amount":         payment.get("amount"),
        "currency":       payment.get("currency"),
        "bundle_purchase_id": payment.get("bundle_purchase_id"),
    }


# ---- Webhook -----------------------------------------------------------------
webhook_router = APIRouter(prefix="/webhook", tags=["webhook"])


@webhook_router.post("/stripe")
async def stripe_webhook(request: Request):
    if not is_payment_active():
        # Honest 503 — better than silently swallowing webhooks.
        raise HTTPException(503, "Stripe webhook handler is disabled (no STRIPE_API_KEY).")
    body = await request.body()
    sig = request.headers.get("Stripe-Signature") or request.headers.get("stripe-signature")
    try:
        result = await handle_stripe_webhook(body, sig)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"webhook error: {type(e).__name__}: {e}")
    return result
