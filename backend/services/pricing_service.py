"""Pricing service — Wave 2.

Computes internal cost from an order's pipeline footprint and produces a
sell price using admin-editable markup + minimum-price rules.

Single source of truth for cost math:
  internal_cost  → derived from generation_jobs + order data
  sell_price     → max(minimum_price, internal_cost * (1 + markup%))
  margin         → sell_price - internal_cost

Two snapshot moments per order (Wave 2 design):
  * `estimate` — taken at production_ready (scenes known, no real jobs yet).
  * `actual`   — taken at delivered (real jobs counted).

Backwards compatibility:
  * Legacy orders without `data.delivery` → output_type defaults to "both".
  * Missing pricing_config doc → built-in defaults are used.
  * Missing duration meta → safe `medium` tier fallback.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from db import db
from models import get_order_output_type

logger = logging.getLogger("pricing_service")

CONFIG_DOC_ID = "default"  # single doc collection

# ---- Built-in defaults ------------------------------------------------------
# All values are SAR and admin-editable via /api/admin/pricing/config.
DEFAULT_PRICING_CONFIG: dict = {
    "id": CONFIG_DOC_ID,
    "currency": "SAR",
    "markup_percent": 35.0,
    "minimum_price": 49.0,
    "rounding": 1.0,  # round sell_price to nearest 1 SAR
    # Per-stage internal cost (SAR units). Calibrated to feel realistic for a
    # small Arabic story platform. Admin can tune freely.
    "per_stage_costs": {
        "scenario_generation":     0.20,   # one LLM call per batch
        "production_planning":     1.50,   # heavy mega-JSON LLM call
        "child_character_i2i":     0.40,   # one OpenAI image edit
        "extra_character_i2i":     0.40,   # per visible extra character
        "scene_image_generation":  0.30,   # per generated scene image
        "cover_image":             0.30,   # cover illustration
        "narration_audio":         0.05,   # per scene (mock today; bump on real TTS)
        "book_page_asset":         0.02,   # per book page (reuses scene image)
        "vision_describe":         0.10,   # per uploaded toy/character analysis
        "video_assembly":          0.40,   # ffmpeg render
        "pdf_assembly":            0.20,   # reportlab render
        "scene_reference_injection": 0.05, # per ACTUAL reference image attached to a scene call
    },
    # Each retry attempt re-burns this fraction of the stage's unit cost.
    "retry_attempt_cost_fraction": 0.30,
    # Output-type modifier on the FINAL internal cost (applied after stage sum).
    # PDF-only is cheaper because it skips narration+video assembly.
    "per_output_modifier": {
        "video": 1.00,
        "pdf":   0.65,
        "both":  1.00,
    },
    # Tier modifier on the final internal cost — bumps long stories slightly.
    "per_cost_tier_modifier": {
        "low":    1.00,
        "medium": 1.00,
        "high":   1.15,
    },
    "updated_at": None,
    "updated_by": None,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Config CRUD
# =============================================================================
async def get_pricing_config() -> dict:
    """Return the active pricing config (defaults if none stored)."""
    doc = await db.pricing_config.find_one({"id": CONFIG_DOC_ID}, {"_id": 0})
    if not doc:
        return dict(DEFAULT_PRICING_CONFIG)
    # Merge with defaults so newly-added keys never cause KeyErrors after
    # an admin edited a partial config.
    merged = dict(DEFAULT_PRICING_CONFIG)
    merged.update(doc)
    # Deep-merge nested dicts.
    for nested in ("per_stage_costs", "per_output_modifier", "per_cost_tier_modifier"):
        merged[nested] = {
            **DEFAULT_PRICING_CONFIG.get(nested, {}),
            **(doc.get(nested) or {}),
        }
    return merged


async def update_pricing_config(patch: dict, admin_id: str | None) -> dict:
    """Upsert pricing config. Returns the new effective config."""
    allowed = {
        "currency", "markup_percent", "minimum_price", "rounding",
        "per_stage_costs", "per_output_modifier", "per_cost_tier_modifier",
        "retry_attempt_cost_fraction",
    }
    update: dict = {k: v for k, v in patch.items() if k in allowed}
    update["updated_at"] = _now()
    update["updated_by"] = admin_id
    before = await db.pricing_config.find_one({"id": CONFIG_DOC_ID}, {"_id": 0})
    await db.pricing_config.update_one(
        {"id": CONFIG_DOC_ID},
        {"$set": update, "$setOnInsert": {"id": CONFIG_DOC_ID}},
        upsert=True,
    )
    cfg = await get_pricing_config()
    # Wave 3 — audit pricing config changes.
    try:
        from services.audit_service import record_audit
        await record_audit(
            entity_type="pricing_config", entity_id=CONFIG_DOC_ID, action="config_change",
            actor_id=admin_id, actor_email=None,
            summary=f"pricing config updated: {sorted(update.keys())}",
            before=before, after=cfg,
        )
    except Exception:  # noqa: BLE001
        pass
    return cfg


# =============================================================================
# Cost calculation
# =============================================================================
def _round_to(value: float, step: float) -> float:
    if not step or step <= 0:
        return round(value, 2)
    return round(round(value / step) * step, 2)


async def _count_extra_characters_with_image(order: dict) -> int:
    chars = (order.get("data") or {}).get("characters") or []
    return sum(1 for c in chars if c.get("role") == "visible" and c.get("image_url"))


async def _has_toy_image(order: dict) -> bool:
    pers = (order.get("data") or {}).get("personalization") or {}
    return bool(pers.get("toy_image_url") or pers.get("toy_description_auto"))


def _payment_source(order: dict) -> str:
    """Wave 3 — classify how this order will be (or was) paid.

    Returns one of:
      "bundle"     — order has a bundle_reservation linked (consumed/reserved)
      "paid"       — order has a successful payment row
      "pending"    — neither bundle nor payment yet (free preview / unpaid)
    """
    res = order.get("bundle_reservation") or {}
    if res and res.get("status") in ("reserved", "consumed"):
        return "bundle"
    if (order.get("payment") or {}).get("status") == "paid":
        return "paid"
    return "pending"


async def estimate_cost(order: dict) -> dict:
    """Build an ESTIMATE breakdown without touching generation_jobs.

    Used at `production_ready` — the production_plan exists so we know the
    scene count, but no real jobs have run yet.
    """
    cfg = await get_pricing_config()
    stage_costs = cfg["per_stage_costs"]
    output_type = get_order_output_type(order)
    duration = order.get("duration") or {}
    cost_tier = duration.get("cost_tier") or "medium"

    plan_id = order.get("production_plan_id")
    plan = await db.production_plans.find_one(
        {"id": plan_id, "is_archived": False}, {"_id": 0}
    ) if plan_id else None
    scene_count = (plan or {}).get("target_scene_count") or duration.get("scene_target") or 5

    extra_chars = await _count_extra_characters_with_image(order)
    has_toy = await _has_toy_image(order)
    needs_video = output_type in ("video", "both")
    needs_pdf = output_type in ("pdf", "both")

    items: list[dict] = []
    def add(stage: str, qty: int, label: str, note: str = ""):
        unit = float(stage_costs.get(stage, 0.0))
        line = round(unit * qty, 4)
        items.append({
            "stage": stage,
            "label": label,
            "quantity": qty,
            "unit_cost": unit,
            "line_cost": line,
            "note": note,
        })

    # 1) Story planning (always)
    add("scenario_generation", 1, "توليد السيناريوهات (دفعة واحدة)")
    add("production_planning", 1, "خطة الإنتاج الكاملة")
    # 2) Vision / I2I extras (always considered when present)
    if has_toy:
        add("vision_describe", 1, "تحليل صورة اللعبة")
    add("child_character_i2i", 1, "إعادة رسم الطفل (i2i)", "اختياري — يدير من خط الإنتاج")
    if extra_chars:
        add("extra_character_i2i", extra_chars, "إعادة رسم شخصيات إضافية", f"عدد الشخصيات المرئية: {extra_chars}")
    # 3) Per-scene image work (always)
    add("cover_image", 1, "غلاف القصة")
    add("scene_image_generation", scene_count, "صور المشاهد")
    # 4) Output-gated work
    if needs_video:
        add("narration_audio", scene_count, "السرد الصوتي لكل مشهد")
        add("video_assembly", 1, "تجميع الفيديو النهائي")
    if needs_pdf:
        add("book_page_asset", scene_count, "صفحات الكتاب")
        add("pdf_assembly", 1, "تجميع كتاب PDF")

    base_cost = sum(it["line_cost"] for it in items)
    output_mod = float(cfg["per_output_modifier"].get(output_type, 1.0))
    tier_mod = float(cfg["per_cost_tier_modifier"].get(cost_tier, 1.0))
    internal_cost = round(base_cost * output_mod * tier_mod, 2)

    sell_price, margin = _apply_markup(internal_cost, cfg)
    return {
        "kind": "estimate",
        "currency": cfg["currency"],
        "output_type": output_type,
        "cost_tier": cost_tier,
        "scene_count": scene_count,
        "extra_characters_count": extra_chars,
        "has_toy_image": has_toy,
        "modifiers": {
            "output": output_mod,
            "cost_tier": tier_mod,
        },
        "items": items,
        "base_cost": round(base_cost, 2),
        "internal_cost": internal_cost,
        "sell_price": sell_price,
        "margin": margin,
        "markup_percent": cfg["markup_percent"],
        "minimum_price": cfg["minimum_price"],
        "payment_source": _payment_source(order),
        "computed_at": _now(),
    }


async def actual_cost(order: dict) -> dict:
    """Compute the ACTUAL cost from generation_jobs + final assembly outcomes.

    Each completed job is billed once at its stage's unit cost; each retry
    attempt beyond the first costs `retry_attempt_cost_fraction` of the unit
    cost. Failed-then-fallback child_character runs are billed as a real
    attempt (because the API call still happened).
    """
    cfg = await get_pricing_config()
    stage_costs = cfg["per_stage_costs"]
    retry_frac = float(cfg.get("retry_attempt_cost_fraction", 0.3))
    output_type = get_order_output_type(order)
    duration = order.get("duration") or {}
    cost_tier = duration.get("cost_tier") or "medium"

    order_id = order["id"]
    items: list[dict] = []

    # generation_jobs cover: cover_image, scene_image, narration_audio,
    # book_page_asset, final_video_assembly, final_pdf_assembly.
    job_to_stage = {
        "cover_image":            "cover_image",
        "scene_image":            "scene_image_generation",
        "narration_audio":        "narration_audio",
        "book_page_asset":        "book_page_asset",
        "final_video_assembly":   "video_assembly",
        "final_pdf_assembly":     "pdf_assembly",
    }
    jobs = await db.generation_jobs.find(
        {"order_id": order_id}, {"_id": 0}
    ).to_list(500)
    # Aggregate counts and attempts per job_type.
    job_buckets: dict[str, dict] = {}
    for j in jobs:
        bucket = job_buckets.setdefault(
            j.get("job_type"), {"count": 0, "extra_attempts": 0}
        )
        bucket["count"] += 1
        att = max(0, int(j.get("attempt_count") or 1) - 1)
        bucket["extra_attempts"] += att
    for job_type, b in job_buckets.items():
        stage = job_to_stage.get(job_type)
        if not stage:
            continue
        unit = float(stage_costs.get(stage, 0.0))
        line = unit * b["count"] + unit * retry_frac * b["extra_attempts"]
        items.append({
            "stage": stage,
            "label": stage,
            "quantity": b["count"],
            "unit_cost": unit,
            "extra_attempts": b["extra_attempts"],
            "line_cost": round(line, 4),
            "note": (f"+{b['extra_attempts']} retries" if b["extra_attempts"] else ""),
        })

    # Always-ran stages (LLM text + I2I + vision) — count via collections.
    # 1) scenario_generation: count batches
    batches = await db.scenarios.distinct("scenario_batch_id", {"order_id": order_id})
    if batches:
        unit = float(stage_costs.get("scenario_generation", 0.0))
        items.append({
            "stage": "scenario_generation",
            "label": "scenario_generation",
            "quantity": len(batches),
            "unit_cost": unit,
            "line_cost": round(unit * len(batches), 4),
            "note": f"{len(batches)} batches",
        })
    # 2) production_planning: count plans (including archived → counts regenerations)
    plan_count = await db.production_plans.count_documents({"order_id": order_id})
    if plan_count:
        unit = float(stage_costs.get("production_planning", 0.0))
        items.append({
            "stage": "production_planning",
            "label": "production_planning",
            "quantity": plan_count,
            "unit_cost": unit,
            "line_cost": round(unit * plan_count, 4),
            "note": f"{plan_count} plan(s)",
        })
    # 3) child_character_i2i: count assets
    cc_count = await db.child_character_assets.count_documents({"order_id": order_id})
    if cc_count:
        unit = float(stage_costs.get("child_character_i2i", 0.0))
        items.append({
            "stage": "child_character_i2i",
            "label": "child_character_i2i",
            "quantity": cc_count,
            "unit_cost": unit,
            "line_cost": round(unit * cc_count, 4),
        })
    # 4) extra_character_i2i: count assets
    ec_count = await db.extra_character_assets.count_documents({"order_id": order_id})
    if ec_count:
        unit = float(stage_costs.get("extra_character_i2i", 0.0))
        items.append({
            "stage": "extra_character_i2i",
            "label": "extra_character_i2i",
            "quantity": ec_count,
            "unit_cost": unit,
            "line_cost": round(unit * ec_count, 4),
        })
    # 5) vision_describe: presence of toy/extra-char description fields
    if await _has_toy_image(order):
        unit = float(stage_costs.get("vision_describe", 0.0))
        items.append({
            "stage": "vision_describe",
            "label": "vision_describe (toy)",
            "quantity": 1,
            "unit_cost": unit,
            "line_cost": round(unit, 4),
        })

    # 6) Phase E — actual scene reference injections (count only what was
    #    really attached to a successful provider call, NOT what was
    #    available). Counted from scene_plans.scene_reference_log.
    inj_total = 0
    scene_logs = await db.scene_plans.find(
        {"order_id": order_id, "is_archived": False,
         "scene_reference_log.references_used": True},
        {"_id": 0, "scene_reference_log.references_injected_count": 1},
    ).to_list(50)
    for sp in scene_logs:
        inj_total += int(((sp or {}).get("scene_reference_log") or {})
                          .get("references_injected_count") or 0)
    if inj_total > 0:
        unit = float(stage_costs.get("scene_reference_injection", 0.0))
        items.append({
            "stage": "scene_reference_injection",
            "label": "scene_reference_injection",
            "quantity": inj_total,
            "unit_cost": unit,
            "line_cost": round(unit * inj_total, 4),
            "note": "references actually attached across scenes",
        })

    base_cost = sum(it["line_cost"] for it in items)
    output_mod = float(cfg["per_output_modifier"].get(output_type, 1.0))
    tier_mod = float(cfg["per_cost_tier_modifier"].get(cost_tier, 1.0))
    internal_cost = round(base_cost * output_mod * tier_mod, 2)

    sell_price, margin = _apply_markup(internal_cost, cfg)
    return {
        "kind": "actual",
        "currency": cfg["currency"],
        "output_type": output_type,
        "cost_tier": cost_tier,
        "modifiers": {
            "output": output_mod,
            "cost_tier": tier_mod,
        },
        "items": items,
        "base_cost": round(base_cost, 2),
        "internal_cost": internal_cost,
        "sell_price": sell_price,
        "margin": margin,
        "markup_percent": cfg["markup_percent"],
        "minimum_price": cfg["minimum_price"],
        "payment_source": _payment_source(order),
        "computed_at": _now(),
    }


def _apply_markup(internal_cost: float, cfg: dict) -> tuple[float, float]:
    markup = float(cfg.get("markup_percent", 0.0)) / 100.0
    minimum = float(cfg.get("minimum_price", 0.0))
    rounding = float(cfg.get("rounding", 1.0))
    sell = max(minimum, internal_cost * (1.0 + markup))
    sell = _round_to(sell, rounding)
    margin = round(sell - internal_cost, 2)
    return sell, margin


# =============================================================================
# Snapshots
# =============================================================================
async def snapshot_estimate(order: dict) -> dict | None:
    """Persist an estimate snapshot. Idempotent — overwrites the last estimate
    of this order. Never raises (cost-tracking must not block the pipeline).
    """
    try:
        breakdown = await estimate_cost(order)
        doc = {
            "id": str(uuid.uuid4()),
            "order_id": order["id"],
            "kind": "estimate",
            "breakdown": breakdown,
            "internal_cost": breakdown["internal_cost"],
            "sell_price": breakdown["sell_price"],
            "margin": breakdown["margin"],
            "currency": breakdown["currency"],
            "output_type": breakdown["output_type"],
            "created_at": _now(),
        }
        # Replace the latest estimate for this order (single estimate per order).
        await db.order_pricing.update_one(
            {"order_id": order["id"], "kind": "estimate"},
            {"$set": doc},
            upsert=True,
        )
        # Mirror a quick summary onto the order doc for fast reads.
        await db.orders.update_one(
            {"id": order["id"]},
            {"$set": {"pricing_estimate": {
                "internal_cost": doc["internal_cost"],
                "sell_price":    doc["sell_price"],
                "margin":        doc["margin"],
                "currency":      doc["currency"],
                "output_type":   doc["output_type"],
                "computed_at":   breakdown["computed_at"],
            }}},
        )
        logger.info(f"[pricing] estimate snapshot order={order['id']} sell={doc['sell_price']} {doc['currency']}")
        return doc
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[pricing] estimate snapshot failed: {type(e).__name__}: {e}")
        return None


async def snapshot_actual(order: dict) -> dict | None:
    """Persist an actual snapshot. Idempotent — overwrites prior `actual`
    for the same order. Never raises.
    """
    try:
        breakdown = await actual_cost(order)
        doc = {
            "id": str(uuid.uuid4()),
            "order_id": order["id"],
            "kind": "actual",
            "breakdown": breakdown,
            "internal_cost": breakdown["internal_cost"],
            "sell_price": breakdown["sell_price"],
            "margin": breakdown["margin"],
            "currency": breakdown["currency"],
            "output_type": breakdown["output_type"],
            "created_at": _now(),
        }
        await db.order_pricing.update_one(
            {"order_id": order["id"], "kind": "actual"},
            {"$set": doc},
            upsert=True,
        )
        await db.orders.update_one(
            {"id": order["id"]},
            {"$set": {"pricing_actual": {
                "internal_cost": doc["internal_cost"],
                "sell_price":    doc["sell_price"],
                "margin":        doc["margin"],
                "currency":      doc["currency"],
                "output_type":   doc["output_type"],
                "computed_at":   breakdown["computed_at"],
            }}},
        )
        logger.info(f"[pricing] actual snapshot order={order['id']} sell={doc['sell_price']} {doc['currency']}")
        return doc
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[pricing] actual snapshot failed: {type(e).__name__}: {e}")
        return None


async def get_order_pricing(order_id: str) -> dict:
    """Return both snapshots (if present) plus a fresh recompute on demand."""
    estimate = await db.order_pricing.find_one(
        {"order_id": order_id, "kind": "estimate"}, {"_id": 0}
    )
    actual = await db.order_pricing.find_one(
        {"order_id": order_id, "kind": "actual"}, {"_id": 0}
    )
    return {"estimate": estimate, "actual": actual}
