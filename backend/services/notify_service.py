"""Email notifications (audit PJ-8): the parent hears when the plan is ready to
approve, when the story is ready, or when something went wrong; the team hears
about failures and plans waiting for a safety review.

Sent through any SMTP mailbox configured as the secret `SMTP_URL`
(smtps://user:password@smtp.example.com:465, or smtp://… on 587 with STARTTLS).
Nothing is sent until it exists. Status changes call `on_status()`, which never
blocks or raises; each (order, event) is sent at most once an hour and logged
in `notifications`.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import smtplib
import ssl
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from urllib.parse import unquote, urlparse

from db import db

logger = logging.getLogger("notify")

SMTP_SECRET = "SMTP_URL"
RESEND_AFTER = timedelta(hours=1)

CUSTOMER_EVENTS = {
    "production_ready": "plan_ready",
    "delivered": "delivered",
    "media_failed": "failed",
    "failed": "failed",
}
OPS_EVENTS = {"media_failed": "ops_failed", "failed": "ops_failed"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def smtp_config() -> dict | None:
    from services.secret_overrides_service import get_secret

    url = (await get_secret(SMTP_SECRET) or "").strip()
    if not url:
        return None
    u = urlparse(url)
    if u.scheme not in ("smtp", "smtps") or not u.hostname:
        logger.warning("[notify] SMTP_URL must look like smtps://user:pass@host:465")
        return None
    return {"ssl": u.scheme == "smtps", "host": u.hostname, "port": u.port or (465 if u.scheme == "smtps" else 587),
            "user": unquote(u.username or ""), "password": unquote(u.password or "")}


async def _setting(key: str, default=""):
    s = await db.settings.find_one({"key": key}, {"_id": 0, "value": 1})
    return (s or {}).get("value", default)


def _send_sync(cfg: dict, msg: EmailMessage) -> None:
    ctx = ssl.create_default_context()
    if cfg["ssl"]:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], context=ctx, timeout=30) as s:
            if cfg["user"]:
                s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        return
    with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as s:
        s.ehlo()
        if s.has_extn("starttls"):
            s.starttls(context=ctx)
            s.ehlo()
        if cfg["user"]:
            s.login(cfg["user"], cfg["password"])
        s.send_message(msg)


async def send_email(to: str, subject: str, body_lines: list[str], button: tuple[str, str] | None = None) -> None:
    """Raises on failure (callers log it)."""
    cfg = await smtp_config()
    if not cfg:
        raise RuntimeError("SMTP_URL مش متسجّل")
    sender = await _setting("notify.from_email") or cfg["user"]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("غِراس", sender))
    msg["To"] = to
    msg["Message-ID"] = make_msgid(domain=(sender.split("@")[-1] or "gheras"))
    text = "\n\n".join(body_lines + ([f"{button[0]}: {button[1]}"] if button else []))
    msg.set_content(text)
    paras = "".join(f'<p style="margin:0 0 14px">{html.escape(line)}</p>' for line in body_lines)
    cta = (f'<p style="margin:22px 0 6px"><a href="{html.escape(button[1])}" style="background:#87A96B;color:#fff;'
           f'padding:12px 26px;border-radius:999px;text-decoration:none;font-weight:bold">{html.escape(button[0])}</a></p>'
           if button else "")
    msg.add_alternative(
        f'<div dir="rtl" style="font-family:Tahoma,Arial,sans-serif;background:#FDFBF7;padding:24px">'
        f'<div style="max-width:520px;margin:auto;background:#fff;border:1px solid #E2D8C9;border-radius:24px;padding:28px;'
        f'color:#2D3748;font-size:16px;line-height:1.8">'
        f'<div style="font-size:22px;font-weight:bold;color:#729352;margin-bottom:14px">غِراس 🌱</div>{paras}{cta}'
        f'<p style="margin:24px 0 0;font-size:12px;color:#8A9AB0">رسالة تلقائية من غِراس.</p></div></div>',
        subtype="html")
    await asyncio.to_thread(_send_sync, cfg, msg)


def _link(order_id: str) -> str | None:
    base = (os.environ.get("PUBLIC_APP_URL") or "").rstrip("/")
    return f"{base}/orders/{order_id}/production-ready" if base else None


def _compose(kind: str, order: dict) -> tuple[str, list[str], str | None]:
    child = ((order.get("data") or {}).get("child") or {}).get("name") or "طفلك"
    link = _link(order["id"])
    if kind == "plan_ready":
        return (f"خطة قصة {child} جاهزة — اعتمدها لنبدأ",
                [f"خطة قصة {child} جاهزة.", "افتحها واعتمدها، ثم نبدأ رسم المشاهد وإعداد الفيديو والكتاب."],
                "افتح الخطة")
    if kind == "delivered":
        return (f"قصة {child} جاهزة 🎉",
                [f"اكتملت قصة {child}! الفيديو والكتاب بانتظارك في حسابك.", "نتمنى أن تعجبكم وتترك أثراً جميلاً 💚"],
                "شاهد القصة")
    if kind == "failed":
        return (f"حدثت مشكلة في تجهيز قصة {child}",
                [f"توقف تجهيز قصة {child} في إحدى الخطوات.",
                 "يمكنك إعادة المحاولة من صفحة القصة، والطلب ظاهر لفريقنا في قائمة المتابعة."],
                "صفحة القصة")
    if kind == "paused":
        return (f"تأخير بسيط في قصة {child} — سنكملها نحن",
                [f"تأخر تجهيز قصة {child} قليلاً بسبب عطل مؤقت من جهتنا، لا بسبب طلبك.",
                 "لا تحتاج إلى فعل أي شيء: سنكملها من حيث توقفت، ونراسلك فور اكتمالها."],
                "صفحة القصة")
    if kind == "ops_failed":
        return (f"طلب وقف: {child} ({order['id'][:8]})",
                [f"طلب {order['id']} وصل لحالة {order.get('status')}.", "افتح الطلب من لوحة الإدارة وشوف المرحلة اللي وقعت."],
                None)
    if kind == "ops_safety":
        return (f"خطة محتاجة مراجعة سلامة: {child} ({order['id'][:8]})",
                ["موديل الخطة علّم القصة «للمراجعة». العميل مش هيقدر يعتمدها لحد ما توافق أو ترفض من صفحة الطلب."],
                None)
    raise ValueError(kind)


async def _send_once(order: dict, kind: str, to: str) -> None:
    key = f"{order['id']}:{kind}"
    last = await db.notifications.find_one({"key": key, "ok": True}, {"_id": 0, "at": 1}, sort=[("at", -1)])
    if last and last["at"] > (_now() - RESEND_AFTER).isoformat():
        return
    subject, lines, button_label = _compose(kind, order)
    link = _link(order["id"])
    row = {"id": str(uuid.uuid4()), "key": key, "order_id": order["id"], "kind": kind, "to": to, "at": _now().isoformat()}
    try:
        await send_email(to, subject, lines, (button_label, link) if button_label and link else None)
        row["ok"] = True
    except Exception as e:  # noqa: BLE001
        row.update(ok=False, error=f"{type(e).__name__}: {str(e)[:200]}")
        logger.warning(f"[notify] {kind} for {order['id'][:8]} not sent: {row['error']}")
    await db.notifications.insert_one(row)


async def _handle(order_id: str, to_status: str) -> None:
    if not await smtp_config() or await _setting("notify.enabled", True) is False:
        return
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "id": 1, "user_id": 1, "status": 1, "data.child": 1,
                                                        "safety_flag": 1, "safety_review": 1, "engine_paused": 1})
    if not order:
        return
    user = await db.users.find_one({"id": order["user_id"]}, {"_id": 0, "email": 1, "deleted_at": 1})
    customer_kind = CUSTOMER_EVENTS.get(to_status)
    # Stopped by an exhausted engine balance: our problem, and the team gets
    # one balance alert instead of an email per order.
    paused = bool(order.get("engine_paused")) and to_status in OPS_EVENTS
    if paused:
        customer_kind = "paused"
    flagged = to_status == "production_ready" and order.get("safety_flag") and not order.get("safety_review")
    if customer_kind and user and not user.get("deleted_at") and not flagged:
        await _send_once(order, customer_kind, user["email"])
    ops = await _setting("notify.ops_email")
    if ops:
        if to_status in OPS_EVENTS and not paused:
            await _send_once(order, OPS_EVENTS[to_status], ops)
        if flagged:
            await _send_once(order, "ops_safety", ops)


def on_status(order_id: str, to_status: str) -> None:
    """Called on every status change; tags orders stopped by an exhausted engine
    balance and sends emails, in the background, never raises."""
    if to_status not in CUSTOMER_EVENTS and to_status not in OPS_EVENTS:
        return
    try:
        asyncio.get_running_loop().create_task(_safe(order_id, to_status))
    except RuntimeError:
        pass


async def _safe(order_id: str, to_status: str) -> None:
    try:
        from services.engine_health import tag_if_paused
        await tag_if_paused(order_id, to_status)
        await _handle(order_id, to_status)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[notify] skipped: {type(e).__name__}: {e}")


async def test_connection(to: str) -> dict:
    """Admin test: send one email now."""
    try:
        await send_email(to, "تجربة إيميلات غِراس", ["لو الرسالة دي وصلتك، الإيميلات شغّالة ✔"])
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
