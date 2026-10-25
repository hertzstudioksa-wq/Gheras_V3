"""Payment routes (M6): order payment (wallet / Moyasar card), wallet top-ups,
the Moyasar callback, and the admin side (settings, ledger, waive, refund,
wallet adjustments)."""
import logging
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import require_admin, get_current_user
from db import db
from services import engine_health, moyasar, payment_service, rate_limit, wallet_service

logger = logging.getLogger("payment_routes")


def _origin(request: Request) -> str:
    return request.headers.get("X-Origin") or request.headers.get("Origin") or str(request.base_url).rstrip("/")


def _card_error(e: Exception) -> HTTPException:
    if isinstance(e, moyasar.MoyasarError):
        # The gateway's own text (key problems, API errors) is for the logs, not the parent.
        logger.warning(f"[payment] Moyasar: {e}")
        return HTTPException(502, "تعذّر بدء الدفع بالبطاقة الآن — حاول بعد قليل أو ادفع من رصيدك")
    if isinstance(e, LookupError):
        return HTTPException(404, str(e))
    return HTTPException(400, str(e))


# ---- Admin ------------------------------------------------------------------
admin_router = APIRouter(
    prefix="/admin/payment",
    tags=["admin-payment"],
    dependencies=[Depends(require_admin)],
)


@admin_router.get("/status")
async def admin_provider_status():
    return await payment_service.get_provider_status()


@admin_router.put("/settings")
async def admin_update_settings(payload: dict, admin=Depends(require_admin)):
    try:
        await payment_service.update_payment_settings(payload, admin)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return await payment_service.get_provider_status()


@admin_router.post("/test")
async def admin_test_key():
    try:
        return await moyasar.ping()
    except moyasar.MoyasarError as e:
        return {"ok": False, "error": str(e)}


@admin_router.get("/payments")
async def admin_list_payments(status: str | None = None, purpose: str | None = None, q: str | None = None,
                              page: int = 1, limit: int = 30):
    query: dict = {}
    if status:
        query["status"] = status
    if purpose:
        query["purpose"] = purpose
    if q and q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"user_email": rx}, {"id": rx}, {"order_id": rx}, {"invoice_id": rx}]
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))
    total = await db.payments.count_documents(query)
    rows = await db.payments.find(query, {"_id": 0, "bundle_snapshot": 0}).sort("created_at", -1) \
        .skip((page - 1) * limit).limit(limit).to_list(limit)
    paid = [p async for p in db.payments.aggregate([
        {"$match": {"status": "paid"}},
        {"$group": {"_id": "$purpose", "sar": {"$sum": "$amount_sar"}, "n": {"$sum": 1}}},
    ])]
    wallet_orders = [p async for p in db.orders.aggregate([
        {"$match": {"payment.status": "paid", "payment.method": "wallet"}},
        {"$group": {"_id": None, "sar": {"$sum": "$payment.total_sar"}, "n": {"$sum": 1}}},
    ])]
    return {
        "items": rows, "total": total, "page": page, "limit": limit,
        "totals": {
            "card_orders": next(({"sar": p["sar"], "n": p["n"]} for p in paid if p["_id"] == "order"), {"sar": 0, "n": 0}),
            "topups": next(({"sar": p["sar"], "n": p["n"]} for p in paid if p["_id"] == "topup"), {"sar": 0, "n": 0}),
            "wallet_orders": ({"sar": wallet_orders[0]["sar"], "n": wallet_orders[0]["n"]} if wallet_orders
                              else {"sar": 0, "n": 0}),
        },
    }


@admin_router.post("/payments/{payment_id}/refresh")
async def admin_refresh_payment(payment_id: str, background: BackgroundTasks):
    p = await db.payments.find_one({"id": payment_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "العملية غير موجودة")
    try:
        return await payment_service.refresh_payment(p, background)
    except moyasar.MoyasarError as e:
        raise HTTPException(502, str(e))


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


class AdjustIn(BaseModel):
    amount_sar: float = Field(ge=-100000, le=100000)
    reason: str = Field(min_length=3, max_length=300)  # internal: audit trail only
    public_note: str | None = Field(None, max_length=200)  # what the customer sees, if anything


admin_orders_router = APIRouter(prefix="/admin", tags=["admin-payment"], dependencies=[Depends(require_admin)])


@admin_orders_router.post("/orders/{order_id}/payment/waive")
async def admin_waive(order_id: str, payload: ReasonIn, background: BackgroundTasks, admin=Depends(require_admin)):
    """Let an order through without payment (gift, test, support case)."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "id": 1, "payment": 1})
    if not order:
        raise HTTPException(404, "الطلب غير موجود")
    if (order.get("payment") or {}).get("status") != "awaiting":
        raise HTTPException(400, "الطلب مش مستني دفع")
    if not await payment_service.mark_order_paid(order_id, method="admin", background=background,
                                                 actor=admin, note=payload.reason):
        raise HTTPException(400, "الطلب مدفوع بالفعل")
    return {"ok": True}


@admin_orders_router.post("/orders/{order_id}/payment/refund")
async def admin_refund(order_id: str, payload: ReasonIn, admin=Depends(require_admin)):
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        raise HTTPException(404, "الطلب غير موجود")
    try:
        return await payment_service.refund_order_to_wallet(order, admin, payload.reason)
    except ValueError as e:
        raise HTTPException(400, str(e))


@admin_orders_router.get("/wallets/{user_id}")
async def admin_wallet(user_id: str):
    return {"balance_halalas": await wallet_service.balance(user_id),
            "history": await wallet_service.history(user_id, 50)}


@admin_orders_router.post("/wallets/{user_id}/adjust")
async def admin_wallet_adjust(user_id: str, payload: AdjustIn, admin=Depends(require_admin)):
    if not await db.users.find_one({"id": user_id}, {"_id": 1}):
        raise HTTPException(404, "المستخدم غير موجود")
    amount = wallet_service.to_halalas(payload.amount_sar)
    if amount > 0:
        await wallet_service.credit(user_id, amount, "adjust", note=payload.reason, actor=admin,
                                    public_note=payload.public_note)
    elif amount < 0:
        res = await wallet_service.debit(user_id, -amount, "adjust", note=payload.reason, actor=admin,
                                         public_note=payload.public_note)
        if not res["ok"]:
            raise HTTPException(400, f"الرصيد {res['balance_halalas'] / 100:.2f} ر.س — أقل من المبلغ")
    else:
        raise HTTPException(400, "المبلغ صفر")
    return await admin_wallet(user_id)


# ---- Customer: paying for an order -------------------------------------------
order_payment_router = APIRouter(prefix="/orders", tags=["order-payment"])


async def _own_order(order_id: str, user: dict) -> dict:
    order = await db.orders.find_one({"id": order_id, "user_id": user["id"]}, {"_id": 0})
    if not order:
        raise HTTPException(404, "الطلب غير موجود")
    return order


@order_payment_router.get("/{order_id}/payment")
async def order_payment(order_id: str, current=Depends(get_current_user)):
    order = await _own_order(order_id, current)
    payment = order.get("payment") or {}
    return {
        "required": await payment_service.payment_required(),
        "status": payment.get("status"),
        "method": payment.get("method"),
        "amount_sar": payment.get("amount_sar"),
        "vat_rate": payment.get("vat_rate"),
        "vat_sar": payment.get("vat_sar"),
        "total_sar": payment.get("total_sar"),
        "wallet_halalas": await wallet_service.balance(current["id"]),
        "card_available": bool(await moyasar.secret_key()),
    }


@order_payment_router.post("/{order_id}/payment/wallet")
async def pay_with_wallet(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    order = await _own_order(order_id, current)
    await engine_health.ensure_available()
    try:
        return await payment_service.pay_order_with_wallet(order, current, background)
    except ValueError as e:
        raise HTTPException(400, str(e))


@order_payment_router.post("/{order_id}/payment/card")
async def pay_with_card(order_id: str, request: Request, background: BackgroundTasks,
                        current=Depends(get_current_user)):
    order = await _own_order(order_id, current)
    rate_limit.check(f"checkout:{current['id']}", 20, 3600)
    if not await moyasar.secret_key():
        raise HTTPException(503, "الدفع بالبطاقة غير متاح حالياً")
    await engine_health.ensure_available()
    try:
        return await payment_service.start_order_checkout(order, current, _origin(request), background)
    except (ValueError, LookupError, moyasar.MoyasarError) as e:
        raise _card_error(e)


@order_payment_router.post("/{order_id}/payment/refresh")
async def refresh_order_payment(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    """Called when the parent comes back from the Moyasar page."""
    await _own_order(order_id, current)
    try:
        for p in await db.payments.find({"order_id": order_id, "status": "pending"}, {"_id": 0}).to_list(10):
            await payment_service.refresh_payment(p, background)
    except moyasar.MoyasarError as e:
        raise HTTPException(502, str(e))
    return await order_payment(order_id, current)


# ---- Customer: wallet ----------------------------------------------------------
wallet_router = APIRouter(prefix="/wallet", tags=["wallet"])


@wallet_router.get("/me")
async def my_wallet(current=Depends(get_current_user)):
    topups = await db.bundles.find({"is_active": True, "credit_sar": {"$gt": 0}},
                                   {"_id": 0, "id": 1, "name": 1, "description": 1, "price": 1, "credit_sar": 1}) \
        .sort("price", 1).to_list(20)
    return {
        "balance_halalas": await wallet_service.balance(current["id"]),
        "history": await wallet_service.history(current["id"], 30, for_customer=True),
        "topups": topups,
        "card_available": bool(await moyasar.secret_key()),
    }


@wallet_router.post("/topup/{bundle_id}")
async def start_topup(bundle_id: str, request: Request, current=Depends(get_current_user)):
    rate_limit.check(f"checkout:{current['id']}", 20, 3600)
    if not await moyasar.secret_key():
        raise HTTPException(503, "الدفع بالبطاقة غير متاح حالياً")
    try:
        return await payment_service.start_topup_checkout(bundle_id, current, _origin(request))
    except (ValueError, LookupError, moyasar.MoyasarError) as e:
        raise _card_error(e)


@wallet_router.post("/topup/refresh/{payment_id}")
async def refresh_topup(payment_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    p = await db.payments.find_one({"id": payment_id, "user_id": current["id"]}, {"_id": 0})
    if not p:
        raise HTTPException(404, "العملية غير موجودة")
    try:
        p = await payment_service.refresh_payment(p, background)
    except moyasar.MoyasarError as e:
        raise HTTPException(502, str(e))
    return {"status": p["status"], "balance_halalas": await wallet_service.balance(current["id"])}


# ---- Moyasar callback -----------------------------------------------------------
webhook_router = APIRouter(prefix="/webhook", tags=["webhook"])


@webhook_router.post("/moyasar", dependencies=[Depends(rate_limit.per_ip("moyasar-callback", 120, 60))])
async def moyasar_callback(request: Request, background: BackgroundTasks):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "invalid body")
    if not isinstance(body, dict):
        raise HTTPException(400, "invalid body")
    try:
        return await payment_service.handle_callback(body, background)
    except moyasar.MoyasarError as e:
        raise HTTPException(502, str(e))
