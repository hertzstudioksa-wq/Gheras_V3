"""Moyasar (Saudi payment gateway) — hosted invoice pages.

We create an invoice server-side for an amount the backend computed, send the
parent to its hosted page (mada, Visa/Mastercard, Apple Pay), then confirm by
fetching the invoice back with the secret key. Nothing a browser or a callback
body says is trusted on its own.

Docs: https://docs.moyasar.com/api/invoices/01-create-invoice — Basic auth with
the secret key as the username and an empty password; amounts in halalas.
"""
from __future__ import annotations

import httpx

from services.secret_overrides_service import get_secret

API = "https://api.moyasar.com/v1"
SECRET_ENV = "MOYASAR_SECRET_KEY"
PAID = "paid"
CLOSED = {"failed", "canceled", "expired", "voided", "refunded"}


class MoyasarError(RuntimeError):
    pass


async def secret_key() -> str | None:
    key = (await get_secret(SECRET_ENV) or "").strip()
    return key or None


def key_mode(key: str | None) -> str | None:
    if not key:
        return None
    return "live" if key.startswith("sk_live_") else "test" if key.startswith("sk_test_") else "unknown"


async def _request(method: str, path: str, json: dict | None = None, params: dict | None = None) -> dict:
    key = await secret_key()
    if not key:
        raise MoyasarError("مفتاح ميسر مش متسجّل")
    try:
        async with httpx.AsyncClient(timeout=20) as c:
            r = await c.request(method, API + path, json=json, params=params, auth=(key, ""))
    except httpx.HTTPError as e:
        raise MoyasarError(f"تعذّر الاتصال بميسر: {type(e).__name__}") from e
    if r.status_code >= 400:
        try:
            body = r.json()
            msg = body.get("message") or body.get("type") or r.text[:200]
        except ValueError:
            msg = r.text[:200]
        raise MoyasarError(f"ميسر رفض الطلب ({r.status_code}): {msg}")
    return r.json()


async def create_invoice(*, amount_halalas: int, description: str, success_url: str, back_url: str,
                         callback_url: str | None, metadata: dict) -> dict:
    if amount_halalas < 100:
        raise MoyasarError("أقل مبلغ في ميسر 1 ريال")
    body = {
        "amount": int(amount_halalas),
        "currency": "SAR",
        "description": description[:255],
        "success_url": success_url,
        "back_url": back_url,
        "metadata": {k: str(v) for k, v in metadata.items()},
    }
    if callback_url:
        body["callback_url"] = callback_url
    return await _request("POST", "/invoices", json=body)


async def fetch_invoice(invoice_id: str) -> dict:
    return await _request("GET", f"/invoices/{invoice_id}")


async def ping() -> dict:
    """Is the key accepted? Lists one invoice page; creates nothing."""
    await _request("GET", "/invoices", params={"page": 1})
    return {"ok": True, "mode": key_mode(await secret_key())}
