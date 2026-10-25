"""Can the AI engine take work right now?

fal answers HTTP 403 "User is locked. Exhausted balance" once the prepaid
balance runs out, and every later call fails the same way (it happened in the
first full test order). The first such answer marks the engine locked:

  * new orders and payments are turned away before the parent pays,
  * an order that fails while locked is tagged `engine_paused`: the parent is
    told we'll finish it, and the admin resumes every paused order in one click
    after topping up (from the step it stopped at, reusing what was drawn),
  * the admin gets one email and a banner.

The first fal call that succeeds clears it. Comfy Cloud (shot keyframes and
clips) is watched the same way in its own doc: a 402, a 429 "User has not paid"
or a job failed with InsufficientFundsError locks it; either provider being
locked stops new work, and each one's next success clears only its own lock.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from db import db

logger = logging.getLogger("engine_health")

DOC_ID = "fal"
LOCK_MARKERS = ("exhausted balance", "user is locked", "insufficient balance", "insufficient credit",
                "out of credit", "insufficientfundserror", "inactivesubscriptionerror", "has not paid")
CACHE_SECONDS = 15
PAUSABLE = ("failed", "media_failed")
BUSY_AR = ("التوليد متوقف دقايق عندنا لصيانة سريعة. جرّب تاني بعد شوية — "
           "مفيش أي مبلغ اتخصم منك.")
PROBE_MODEL = "anthropic/claude-haiku-5.5"
# The status an order is put back in for the step it resumes at.
RESUME_STATUS = {"scenarios": "scenarios_generating", "planning": "production_planning",
                 "assets": "assets_generating", "assembly": "assembling"}
# One health doc per paid provider ("fal" is the original doc id).
PROVIDERS = {"fal": "fal", "comfy": "Comfy Cloud"}
COMFY_MIN_BALANCE_USD = 0.5  # below this a keyframe or a long clip may not go through
COMFY_STAGES = ("scene_image_generation", "video_generation")

_cache: dict = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_balance_message(message) -> bool:
    text = str(message or "").lower()
    return any(m in text for m in LOCK_MARKERS)


def is_lock_error(message, provider: str = "fal", status: int | None = None) -> bool:
    """Does this error mean the provider's credit is gone (not a passing fault)?"""
    if is_balance_message(message):
        return True
    if provider == "comfy":
        # 402 = insufficient credits; Comfy's 429 is "User has not paid" (a busy
        # queue says nothing about payment and stays retryable).
        text = str(message or "").lower()
        return status == 402 or (status == 429 and any(w in text for w in ("paid", "payment", "credit", "subscription")))
    return False


async def _doc(fresh: bool = False, provider: str = DOC_ID) -> dict:
    hit = _cache.get(provider)
    if not fresh and hit and time.monotonic() - hit["at"] < CACHE_SECONDS:
        return hit["doc"]
    doc = await db.engine_health.find_one({"id": provider}, {"_id": 0}) or {"id": provider, "locked": False}
    _cache[provider] = {"at": time.monotonic(), "doc": doc}
    return doc


def _view(provider: str, d: dict) -> dict:
    return {"label": PROVIDERS[provider], "locked": bool(d.get("locked")), "locked_at": d.get("locked_at"),
            "stage": d.get("stage"), "message": d.get("message"), "cleared_at": d.get("cleared_at"),
            "last_error": d.get("last_error")}


async def status(fresh: bool = False) -> dict:
    """The locked provider's fields at the top (what the banner shows), plus each provider."""
    docs = {p: await _doc(fresh, p) for p in PROVIDERS}
    shown = next((p for p, d in docs.items() if d.get("locked")), DOC_ID)
    top = _view(shown, docs[shown])
    return {"locked": top["locked"], "locked_at": top["locked_at"], "stage": top["stage"],
            "message": top["message"], "cleared_at": top["cleared_at"],
            "provider": shown, "provider_label": top["label"],
            "providers": {p: _view(p, d) for p, d in docs.items()},
            "paused_orders": await db.orders.count_documents({"engine_paused": {"$ne": None},
                                                               "status": {"$in": list(PAUSABLE)}})}


async def is_locked(fresh: bool = False) -> bool:
    """Any provider locked: new paid work would stop halfway, so none starts."""
    for p in PROVIDERS:
        if (await _doc(fresh, p)).get("locked"):
            return True
    return False


async def ensure_available() -> None:
    """Routes call this before anything that would spend money or start paid
    work: a locked engine turns the parent away before they pay."""
    if await is_locked(fresh=True):
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=BUSY_AR)


async def note_error(stage: str, message, provider: str = DOC_ID, status: int | None = None,
                     raw: str | None = None) -> None:
    """Called by the adapters on every error answer; locks only on a credits answer.
    `raw` (the full answer) is kept as the provider's last error, so its exact
    wording can be read from the admin."""
    upsert = {"$setOnInsert": {"id": provider, "locked": False}}
    if raw is not None:
        upsert["$set"] = {"last_error": {"at": _now(), "stage": stage, "status": status,
                                         "message": str(message)[:300], "raw": str(raw)[:2000]}}
    if raw is not None or is_lock_error(message, provider, status):
        await db.engine_health.update_one({"id": provider}, upsert, upsert=True)
        _cache.pop(provider, None)
    if not is_lock_error(message, provider, status):
        return
    res = await db.engine_health.update_one(
        {"id": provider, "locked": {"$ne": True}},
        {"$set": {"locked": True, "locked_at": _now(), "stage": stage, "message": str(message)[:300]}},
    )
    _cache.pop(provider, None)
    if res.modified_count:
        logger.error(f"[engine] {PROVIDERS[provider]} balance exhausted (first seen in {stage}): new orders are paused")
        try:
            asyncio.get_running_loop().create_task(_alert(stage, provider))
        except RuntimeError:
            pass


async def note_success(provider: str = DOC_ID) -> None:
    """Called by the adapters after a call that needs credit succeeds."""
    if not (await _doc(provider=provider)).get("locked"):
        return
    res = await db.engine_health.update_one({"id": provider, "locked": True},
                                            {"$set": {"locked": False, "cleared_at": _now()}})
    _cache.pop(provider, None)
    if res.modified_count:
        logger.info(f"[engine] {PROVIDERS[provider]} answered again: unlocked")


async def _alert(stage: str, provider: str = DOC_ID) -> None:
    from services.notify_service import _setting, send_email, smtp_config

    ops = await _setting("notify.ops_email")
    if not ops or not await smtp_config():
        return
    label = PROVIDERS[provider]
    try:
        await send_email(ops, f"رصيد {label} خلص — التوليد واقف", [
            f"{label} رفض طلب في مرحلة {stage} لأن الرصيد خلص.",
            "الطلبات الجديدة والدفع متوقفين لحد ما يتشحن. أي طلب وقف في النص متعلّم «موقوف».",
            "بعد الشحن: لوحة الإدارة ← البانر اللي فوق ← «استكمال الطلبات الموقوفة».",
        ])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[engine] alert email not sent: {type(e).__name__}: {e}")


async def tag_if_paused(order_id: str, to_status: str) -> bool:
    """On a failed status: if the engine is locked, the failure is ours, not the
    story's — tag the order so it's resumed after the top-up."""
    if to_status not in PAUSABLE:
        return False
    if not await is_locked(fresh=True):
        # A later failure with a working engine is a real failure again.
        await db.orders.update_one({"id": order_id, "engine_paused": {"$ne": None}}, {"$set": {"engine_paused": None}})
        return False
    order = await db.orders.find_one({"id": order_id}, {"_id": 0, "status_history": {"$slice": -1}})
    last = ((order or {}).get("status_history") or [{}])[-1]
    await db.orders.update_one({"id": order_id, "status": to_status},
                               {"$set": {"engine_paused": {"at": _now(), "from_status": last.get("from")}}})
    return True


async def _probe_fal() -> dict:
    """A free one-byte upload and a few tokens of Haiku through fal (a fraction of
    a cent): the only way to know the balance works — fal's status endpoint
    answers fine on a locked account."""
    from services.ai import AIError, fal
    from services.ai.text_client import generate_text

    try:
        # A free one-byte upload first: on an exhausted account fal still served
        # small text requests while uploads (and every image, clip and voice)
        # were refused.
        await fal.upload(env_key="FAL_KEY_SCENE", data=b"ok", content_type="text/plain", file_name="probe.txt")
        await generate_text(stage="engine_probe", provider="fal_llm", model=PROBE_MODEL,
                            system="Reply with the single word OK.", user="ping", effort="low",
                            max_tokens=16, timeout=45.0)
    except AIError as e:
        locked = is_balance_message(e)
        return {"ok": False, "locked": locked, "error": "رصيد fal خلص" if locked else str(e)[:200]}
    return {"ok": True, "locked": False, "error": None}


async def comfy_in_use() -> bool:
    """A keyframe or clip stage (or the premium video tier) runs on Comfy."""
    from services.config_service import resolve_model
    from services.model_catalog import premium_video_model

    for stage in COMFY_STAGES:
        provider, _model, _src = await resolve_model(stage, "", "")
        if (provider or "").startswith("comfy"):
            return True
    return (await premium_video_model()).startswith("comfy/")


async def _probe_comfy() -> dict:
    """Comfy's credit is a free read: below the minimum counts as locked."""
    from services.ai import AIError, comfy

    try:
        usd = await comfy.balance_usd(stage="engine_probe")
        if usd is None:
            await comfy.ping(stage="engine_probe")
    except AIError as e:
        locked = is_lock_error(e, "comfy")
        return {"ok": False, "locked": locked, "balance_usd": None,
                "error": "رصيد Comfy خلص" if locked else f"Comfy: {str(e)[:200]}"}
    if usd is not None and usd < COMFY_MIN_BALANCE_USD:
        await note_error("engine_probe", f"insufficient credit: ${usd:.2f} left", provider="comfy")
        return {"ok": False, "locked": True, "balance_usd": usd, "error": f"رصيد Comfy خلص (${usd:.2f})"}
    await note_success("comfy")
    return {"ok": True, "locked": False, "balance_usd": usd, "error": None}


async def probe(providers: tuple[str, ...] = tuple(PROVIDERS)) -> dict:
    """Checks each provider's balance for real. Comfy is checked only when a
    stage uses it or it's locked, so an unused provider never stops orders."""
    started = time.monotonic()
    checks = {}
    if "fal" in providers:
        checks["fal"] = await _probe_fal()
    if "comfy" in providers and ((await _doc(True, "comfy")).get("locked") or await comfy_in_use()):
        checks["comfy"] = await _probe_comfy()
    bad = next((p for p, c in checks.items() if not c["ok"]), None)
    return {"ok": bad is None, "locked": any(c["locked"] for c in checks.values()),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "error": checks[bad]["error"] if bad else None, "checks": checks}


async def resume_paused(actor_id: str | None = None) -> dict:
    """After a top-up: probe once, then restart every paused order from the step
    it stopped at (drawn sheets, keyframes and paid clips are reused)."""
    from services.order_state import claim
    from services.recovery_service import STEP_OF_STATUS, _resume

    check = await probe()
    if not check["ok"]:
        return {"ok": False, "error": check["error"], "resumed": [], "skipped": []}
    resumed, skipped = [], []
    async for o in db.orders.find({"engine_paused": {"$ne": None}, "status": {"$in": list(PAUSABLE)}},
                                  {"_id": 0, "id": 1, "status": 1, "engine_paused": 1, "current_scenario_batch_id": 1}):
        step = STEP_OF_STATUS.get((o.get("engine_paused") or {}).get("from_status") or "")
        if not step:
            skipped.append(o["id"])
            continue
        if step == "assembly":
            from routes.media_routes import assets_complete
            if not await assets_complete(o["id"]):
                step = "assets"
        back_to = RESUME_STATUS[step]
        if not await claim(o["id"], (o["status"],), back_to, "admin", actor_id=actor_id,
                           reason="استكمال بعد شحن رصيد المحرك", extra={"engine_paused": None}):
            skipped.append(o["id"])
            continue
        try:
            await _resume({**o, "status": back_to}, step)
            resumed.append(o["id"])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[engine] resume {o['id'][:8]} failed: {type(e).__name__}: {e}")
            skipped.append(o["id"])
    return {"ok": True, "error": None, "resumed": resumed, "skipped": skipped}
