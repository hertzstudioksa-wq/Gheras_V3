"""Order endpoints — v4 with scenario batches, duration, regeneration limit."""
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks

from db import db
from auth import get_current_user
from models import OrderCreate, OrderStatus, ORDER_STATUS_AR, duration_meta
from prompt_engine import build_prompt
from services.scenario_service import generate_scenarios, build_scenario_docs

router = APIRouter(prefix="/orders", tags=["orders"])

MAX_REGENERATIONS = 3


def _now():
    return datetime.now(timezone.utc).isoformat()


async def _enrich(data: dict) -> dict:
    goal = data.get("goal", {}) or {}
    style = data.get("style", {}) or {}
    out: dict = {}
    if goal.get("category_id"):
        cat = await db.categories.find_one({"id": goal["category_id"]}, {"_id": 0, "name_ar": 1})
        if cat:
            out["category_name"] = cat["name_ar"]
    if goal.get("subcategory_id"):
        sub = await db.subcategories.find_one({"id": goal["subcategory_id"]}, {"_id": 0, "name_ar": 1})
        if sub:
            out["subcategory_name"] = sub["name_ar"]
    for k, field in [
        ("type_id", "type_name"), ("tone_id", "tone_name"), ("setting_id", "setting_name"),
        ("language_id", "language_name"), ("voice_id", "voice_name"),
    ]:
        if style.get(k):
            opt = await db.story_options.find_one({"id": style[k]}, {"_id": 0, "name_ar": 1})
            if opt:
                out[field] = opt["name_ar"]
    return out


async def append_status(order_id: str, from_status: str | None, to_status: str, by: str, actor_id: str | None = None, reason: str | None = None):
    entry = {
        "from": from_status,
        "to": to_status,
        "at": _now(),
        "by": by,
        "actor_id": actor_id,
        "reason": reason,
    }
    await db.orders.update_one(
        {"id": order_id},
        {
            "$set": {"status": to_status, "updated_at": _now()},
            "$push": {"status_history": entry},
        },
    )


async def run_scenario_generation(order_id: str, batch_id: str):
    """Background task: generate a batch, persist (without deleting old), and advance status."""
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        return
    try:
        items, source, err = await generate_scenarios(order)
        docs = build_scenario_docs(order_id, items, batch_id, source)
        # Archive all existing batches, keep them for history
        await db.scenarios.update_many(
            {"order_id": order_id},
            {"$set": {"is_archived": True, "is_selected": False}},
        )
        await db.scenarios.insert_many(docs)
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "current_scenario_batch_id": batch_id,
                "selected_scenario_id": None,
                "selected_scenario_snapshot": None,
                "scenarios_generation": {
                    "source": source,
                    "error": err,
                    "batch_id": batch_id,
                    "completed_at": _now(),
                },
            }},
        )
        await append_status(order_id, order.get("status"), OrderStatus.SCENARIOS_READY.value, "system", reason=f"via {source} (batch {batch_id[:8]})")
    except Exception as e:
        await db.orders.update_one(
            {"id": order_id},
            {"$set": {
                "scenarios_generation": {"source": "error", "error": str(e), "batch_id": batch_id, "completed_at": _now()},
            }},
        )
        await append_status(order_id, order.get("status"), OrderStatus.FAILED.value, "system", reason=f"scenarios error: {e}")


@router.post("")
async def create_order(payload: OrderCreate, background: BackgroundTasks, current=Depends(get_current_user)):
    data = payload.data.model_dump()
    if not await db.categories.find_one({"id": data["goal"]["category_id"], "is_active": True}):
        raise HTTPException(status_code=400, detail="التصنيف غير موجود")

    max_chars = 3
    s = await db.settings.find_one({"key": "characters.max_count"}, {"_id": 0})
    if s and isinstance(s.get("value"), (int, float)):
        max_chars = int(s["value"])
    if len(data.get("characters", [])) > max_chars:
        raise HTTPException(status_code=400, detail=f"الحد الأقصى للشخصيات هو {max_chars}")

    # Duration — normalize & compute meta
    raw_seconds = int((data.get("duration") or {}).get("seconds") or 90)
    dur_meta = duration_meta(raw_seconds)

    order_id = str(uuid.uuid4())
    enriched = await _enrich(data)
    prompt = build_prompt(data, enriched)
    batch_id = str(uuid.uuid4())

    initial_history = [
        {"from": None, "to": OrderStatus.PENDING.value, "at": _now(), "by": "user", "actor_id": current["id"], "reason": "submit"},
    ]
    doc = {
        "id": order_id,
        "user_id": current["id"],
        "data": data,
        "enriched": enriched,
        "duration": dur_meta,
        "status": OrderStatus.PENDING.value,
        "admin_note": None,
        "ai_prompt_snapshot": prompt,
        "prompt_edited": False,
        "current_scenario_batch_id": batch_id,
        "selected_scenario_id": None,
        "selected_scenario_snapshot": None,
        "selected_scenario_batch_id": None,
        "regeneration_count": 0,
        "max_regenerations": MAX_REGENERATIONS,
        "scenarios_generation": None,
        "status_history": initial_history,
        "created_at": _now(),
        "updated_at": _now(),
    }
    await db.orders.insert_one(doc)
    await db.drafts.delete_one({"user_id": current["id"]})

    await append_status(order_id, OrderStatus.PENDING.value, OrderStatus.SCENARIOS_GENERATING.value, "system", reason="auto")
    background.add_task(run_scenario_generation, order_id, batch_id)

    fresh = await db.orders.find_one({"id": order_id}, {"_id": 0})
    return fresh


def _summary(o: dict) -> dict:
    e = o.get("enriched", {}) or {}
    child = (o.get("data") or {}).get("child", {})
    return {
        "id": o["id"],
        "user_id": o.get("user_id"),
        "status": o.get("status"),
        "status_ar": ORDER_STATUS_AR.get(o.get("status"), o.get("status")),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
        "child_name": child.get("name"),
        "child_age": child.get("age"),
        "child_gender": child.get("gender"),
        "category_name": e.get("category_name"),
        "subcategory_name": e.get("subcategory_name"),
        "type_name": e.get("type_name"),
        "selected_scenario_id": o.get("selected_scenario_id"),
        "duration": o.get("duration"),
    }


# Keys that MUST NEVER be sent to the user (internal prompts, AI snapshots, DB bookkeeping).
_INTERNAL_ORDER_KEYS = {
    "ai_prompt_snapshot",
    "prompt_edited",
    "scenarios_generation",
    "production_generation",
    "asset_generation_run_id",
    "asset_generation_started_at",
    "asset_generation_completed_at",
    "final_assembly_run_id",
    "final_assembly_started_at",
    "final_assembly_completed_at",
    "status_history",
    "admin_note",
    "production_plan_id",
    "current_scenario_batch_id",
    "selected_scenario_batch_id",
}

# Fields inside a scenario snapshot that are safe to surface to the user.
_SAFE_SCENARIO_FIELDS = {
    "id", "scenario_index", "title", "short_summary",
    "emotional_angle", "learning_goal", "visual_style_hint",
    "estimated_scene_count", "why_this_fits",
}


def _sanitize_scenario_snapshot(snap: dict | None) -> dict | None:
    if not snap:
        return None
    return {k: snap[k] for k in _SAFE_SCENARIO_FIELDS if k in snap}


def _sanitize_user_order(o: dict) -> dict:
    clean = {k: v for k, v in o.items() if k not in _INTERNAL_ORDER_KEYS}
    clean["status_ar"] = ORDER_STATUS_AR.get(o.get("status"), o.get("status"))
    if clean.get("selected_scenario_snapshot"):
        clean["selected_scenario_snapshot"] = _sanitize_scenario_snapshot(
            clean["selected_scenario_snapshot"]
        )
    # Expose only the minimal public summary snapshot (no run ids, no generator source).
    if clean.get("production_plan_snapshot"):
        plan_snap = clean["production_plan_snapshot"] or {}
        clean["production_plan_snapshot"] = {
            "target_scene_count": plan_snap.get("target_scene_count"),
            "generated_at": plan_snap.get("generated_at"),
        }
    return clean


# Scenario fields to publish to the user (strict allow-list).
_PUBLIC_SCENARIO_KEYS = _SAFE_SCENARIO_FIELDS | {"is_selected"}


@router.get("")
async def my_orders(current=Depends(get_current_user)):
    items = await db.orders.find({"user_id": current["id"]}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return [_summary(o) for o in items]


@router.get("/{order_id}")
async def order_detail(order_id: str, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    # Strip internal / AI-prep fields from user-facing payload.
    sanitized = _sanitize_user_order(o)
    return sanitized


# ---------- Scenarios (user-facing) ----------
@router.get("/{order_id}/scenarios")
async def list_scenarios(order_id: str, current=Depends(get_current_user)):
    o = await db.orders.find_one(
        {"id": order_id, "user_id": current["id"]},
        {"_id": 0, "status": 1, "scenarios_generation": 1, "selected_scenario_id": 1,
         "current_scenario_batch_id": 1, "regeneration_count": 1, "max_regenerations": 1,
         "duration": 1},
    )
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    current_batch = o.get("current_scenario_batch_id")
    items = await db.scenarios.find(
        {"order_id": order_id, "scenario_batch_id": current_batch},
        {"_id": 0},
    ).sort("scenario_index", 1).to_list(10)
    # Strict allow-list → avoid leaking internal fields like scenario_batch_id/source.
    items = [{k: v for k, v in s.items() if k in _PUBLIC_SCENARIO_KEYS} for s in items]
    max_regen = o.get("max_regenerations", MAX_REGENERATIONS)
    used = o.get("regeneration_count", 0)
    return {
        "status": o.get("status"),
        "status_ar": ORDER_STATUS_AR.get(o.get("status"), o.get("status")),
        "selected_scenario_id": o.get("selected_scenario_id"),
        "regeneration_count": used,
        "max_regenerations": max_regen,
        "regenerations_remaining": max(0, max_regen - used),
        "duration": o.get("duration"),
        "scenarios": items,
    }


# Wave 1 — scenario history (previous batches the user can return to).
@router.get("/{order_id}/scenarios/batches")
async def list_scenario_batches(order_id: str, current=Depends(get_current_user)):
    """Return all scenario batches generated for this order (most recent first).

    The UI uses this to render an "أفكار سابقة" / "previous ideas" expander on
    the scenario selection page so the user can revisit any prior batch and
    pick a scenario from it. Internal fields are stripped per
    `_PUBLIC_SCENARIO_KEYS` to match the live `/scenarios` endpoint.
    """
    o = await db.orders.find_one(
        {"id": order_id, "user_id": current["id"]},
        {"_id": 0, "status": 1, "current_scenario_batch_id": 1,
         "selected_scenario_id": 1, "selected_scenario_batch_id": 1},
    )
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")

    rows = await db.scenarios.find(
        {"order_id": order_id}, {"_id": 0}
    ).sort([("created_at", -1), ("scenario_index", 1)]).to_list(500)

    batches_map: dict[str, dict] = {}
    for s in rows:
        bid = s.get("scenario_batch_id")
        if not bid:
            continue
        if bid not in batches_map:
            batches_map[bid] = {
                "batch_id": bid,
                "created_at": s.get("created_at"),
                "is_current": bid == o.get("current_scenario_batch_id"),
                "scenarios": [],
            }
        # Earliest created_at across the batch's scenarios → batch creation time.
        if s.get("created_at") and s["created_at"] < batches_map[bid]["created_at"]:
            batches_map[bid]["created_at"] = s["created_at"]
        batches_map[bid]["scenarios"].append(
            {k: v for k, v in s.items() if k in _PUBLIC_SCENARIO_KEYS}
        )

    batches = sorted(batches_map.values(), key=lambda b: b.get("created_at") or "", reverse=True)
    for b in batches:
        b["scenarios"].sort(key=lambda x: x.get("scenario_index", 0))

    return {
        "current_batch_id": o.get("current_scenario_batch_id"),
        "selected_scenario_id": o.get("selected_scenario_id"),
        "selected_scenario_batch_id": o.get("selected_scenario_batch_id"),
        "batches": batches,
        "batch_count": len(batches),
    }


@router.post("/{order_id}/scenarios/regenerate")
async def regenerate_scenarios(order_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if o.get("status") in (OrderStatus.GENERATING.value, OrderStatus.COMPLETED.value):
        raise HTTPException(status_code=400, detail="لا يمكن إعادة التوليد بعد بدء الإنتاج")

    used = int(o.get("regeneration_count", 0))
    max_regen = int(o.get("max_regenerations", MAX_REGENERATIONS))
    if used >= max_regen:
        raise HTTPException(
            status_code=429,
            detail="لقد وصلت للحد الأقصى من إعادة توليد الأفكار لهذه القصة.",
        )

    new_batch_id = str(uuid.uuid4())
    await db.orders.update_one(
        {"id": order_id},
        {
            "$set": {
                "current_scenario_batch_id": new_batch_id,
                "selected_scenario_id": None,
                "selected_scenario_snapshot": None,
            },
            "$inc": {"regeneration_count": 1},
        },
    )
    await append_status(order_id, o.get("status"), OrderStatus.SCENARIOS_GENERATING.value, "user", actor_id=current["id"], reason=f"regenerate ({used + 1}/{max_regen})")
    background.add_task(run_scenario_generation, order_id, new_batch_id)
    return {"ok": True, "batch_id": new_batch_id, "regeneration_count": used + 1, "regenerations_remaining": max_regen - used - 1}


@router.post("/{order_id}/scenarios/{scenario_id}/select")
async def select_scenario(order_id: str, scenario_id: str, background: BackgroundTasks, current=Depends(get_current_user)):
    o = await db.orders.find_one({"id": order_id, "user_id": current["id"]}, {"_id": 0})
    if not o:
        raise HTTPException(status_code=404, detail="الطلب غير موجود")
    if o.get("status") in (OrderStatus.GENERATING.value, OrderStatus.COMPLETED.value):
        raise HTTPException(status_code=400, detail="لا يمكن التعديل بعد بدء الإنتاج")
    scenario = await db.scenarios.find_one({"id": scenario_id, "order_id": order_id}, {"_id": 0})
    if not scenario:
        raise HTTPException(status_code=404, detail="السيناريو غير موجود")

    # Wave 1 — scenarios from a PREVIOUS batch are allowed. Selecting one
    # promotes its batch back to current so the rest of the pipeline (which
    # already filters on current_scenario_batch_id) keeps working unchanged.
    selected_batch = scenario.get("scenario_batch_id")
    current_batch = o.get("current_scenario_batch_id")
    promote_batch = bool(selected_batch and selected_batch != current_batch)

    await db.scenarios.update_many({"order_id": order_id}, {"$set": {"is_selected": False}})
    await db.scenarios.update_one({"id": scenario_id}, {"$set": {"is_selected": True}})
    update_fields: dict = {
        "selected_scenario_id": scenario_id,
        "selected_scenario_snapshot": scenario,
        "selected_scenario_batch_id": selected_batch,
    }
    if promote_batch:
        update_fields["current_scenario_batch_id"] = selected_batch
    await db.orders.update_one({"id": order_id}, {"$set": update_fields})

    reason = (
        f"selected scenario {scenario.get('scenario_index')}"
        + (" (from previous batch)" if promote_batch else "")
    )
    await append_status(order_id, o.get("status"), OrderStatus.SCENARIO_SELECTED.value, "user",
                        actor_id=current["id"], reason=reason)
    await append_status(order_id, OrderStatus.SCENARIO_SELECTED.value, OrderStatus.READY_FOR_AI.value,
                        "system", reason="auto after selection")
    # Trigger production planning in background (phase 5)
    from routes.production_routes import trigger_production_planning
    await trigger_production_planning(order_id, background)
    return {"ok": True, "promoted_batch": promote_batch}
