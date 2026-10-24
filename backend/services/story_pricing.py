"""Customer price for a story by length, deliverable and video tier.

Cost = what one story uses (counts measured on the Yaman test order against
fal's invoice and in the text bake-off, 2026-10-24) × the unit prices of the
models the stages use right now (model catalog, M4: text per token, images per
picture at the configured quality, video per second, music and narration per
minute), then a retry buffer, payment fees and the target margin, rounded up to
a price ending in 9. Switching a stage to a pricier model in the admin therefore
raises the price the parent sees.

The margin, buffer, fee, minimum price, USD→SAR rate, VAT and any manual price
for a single (length, deliverable, tier) cell live in `pricing_settings` and are
edited on the admin pricing page (M6).
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone

from db import db
from models import DURATION_SNAPS
from services.config_service import DEFAULT_VIDEO_TIER, VIDEO_TIERS
from services.house_style import SHOT_SECONDS

# Fallback unit costs (USD) for models the catalog has no price for yet.
IMAGE_HIGH = 0.17      # character sheets + cover (GPT Image 2 high)
IMAGE_MEDIUM = 0.06    # shot keyframes (GPT Image 2 medium)
MUSIC_PER_MINUTE = 0.60
TEXT_PER_STORY = 0.35  # scenarios + production plan (Claude via fal), when a model has no token price
# Tokens one story spends per text stage (input, output). Measured in the text
# bake-off (2026-10-24, upper end across models: the plan's output includes reasoning).
TEXT_TOKENS = {"scenario_generation": (1700, 2500), "production_planning": (6500, 17000)}
CAST_SHEETS = 3        # child + one relative + one other (horse, pet...) on average
# Clip seconds paid per story second: line gaps, the end tail and 5/10 s rounding.
CLIP_SECONDS_FACTOR = 1.33
OUTPUT_TYPES = ("video", "pdf", "both")

SETTINGS_ID = "story"
DEFAULT_SETTINGS = {
    "target_margin": 0.50,   # share of the price left after the loaded cost
    "retry_buffer": 0.15,    # regenerated shots, failed takes
    "payment_fee": 0.03,     # card / mada processing
    "min_price_sar": 39,
    "usd_to_sar": 3.75,
    "vat_rate": 0.0,         # 0 until the business is VAT-registered, then 0.15
}
SETTING_LIMITS = {
    "target_margin": (0.0, 0.9),
    "retry_buffer": (0.0, 1.0),
    "payment_fee": (0.0, 0.2),
    "min_price_sar": (0, 5000),
    "usd_to_sar": (1.0, 10.0),
    "vat_rate": (0.0, 0.3),
}
SETTING_LABELS = {
    "target_margin": "هامش الربح المستهدف",
    "retry_buffer": "احتياطي إعادة المحاولة",
    "payment_fee": "رسوم الدفع",
    "min_price_sar": "أقل سعر",
    "usd_to_sar": "سعر الدولار بالريال",
    "vat_rate": "ضريبة القيمة المضافة",
}

DEFAULT_PRICES = {
    "text": TEXT_PER_STORY,
    "image_sheet": IMAGE_HIGH,
    "image_shot": IMAGE_MEDIUM,
    "music_per_minute": MUSIC_PER_MINUTE,
    "narration_per_minute": 0.0,
    "video_per_second": {t: v["cost_per_second_usd"] for t, v in VIDEO_TIERS.items()},
    "shot_seconds": SHOT_SECONDS,
}

_cache: dict[str, tuple[float, dict]] = {}
_TTL = 10.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ends_in_9(sar: float) -> int:
    return int(math.ceil((sar + 1) / 10.0) * 10 - 1)


def _tier_for(output_type: str, tier: str | None) -> str:
    if output_type == "pdf" or tier not in VIDEO_TIERS:
        return DEFAULT_VIDEO_TIER
    return tier


def cell_key(seconds: int, output_type: str, tier: str | None) -> str:
    return f"{int(seconds)}|{output_type}|{_tier_for(output_type, tier)}"


# ---------------------------------------------------------------- settings
async def get_settings() -> dict:
    hit = _cache.get("settings")
    if hit and time.monotonic() - hit[0] < _TTL:
        return hit[1]
    doc = await db.pricing_settings.find_one({"id": SETTINGS_ID}, {"_id": 0}) or {}
    settings = {**DEFAULT_SETTINGS, **{k: doc[k] for k in DEFAULT_SETTINGS if k in doc}}
    settings["overrides"] = dict(doc.get("overrides") or {})
    settings["updated_at"] = doc.get("updated_at")
    settings["updated_by"] = doc.get("updated_by")
    _cache["settings"] = (time.monotonic(), settings)
    return settings


def invalidate() -> None:
    _cache.clear()


def validate_settings(patch: dict) -> dict:
    """Known keys within their limits; raises ValueError (Arabic) otherwise."""
    clean = {}
    for key, value in (patch or {}).items():
        if key not in SETTING_LIMITS:
            raise ValueError(f"إعداد غير معروف: {key}")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{SETTING_LABELS[key]} لازم يكون رقم")
        lo, hi = SETTING_LIMITS[key]
        if not lo <= value <= hi:
            raise ValueError(f"{SETTING_LABELS[key]} لازم يكون بين {lo} و{hi}")
        clean[key] = int(value) if key == "min_price_sar" else float(value)
    return clean


async def update_settings(patch: dict, admin: dict) -> dict:
    from services.audit_service import record_audit

    clean = validate_settings(patch)
    before = await get_settings()
    await db.pricing_settings.update_one(
        {"id": SETTINGS_ID},
        {"$set": {**clean, "updated_at": _now(), "updated_by": admin.get("email")},
         "$setOnInsert": {"id": SETTINGS_ID}},
        upsert=True,
    )
    invalidate()
    after = await get_settings()
    await record_audit(
        entity_type="pricing_config", entity_id=SETTINGS_ID, action="pricing.settings",
        actor_id=admin.get("id"), actor_email=admin.get("email"),
        summary="إعدادات التسعير: " + "، ".join(f"{SETTING_LABELS[k]} {before.get(k)} ← {v}" for k, v in clean.items()),
        before={k: before.get(k) for k in clean}, after=clean,
    )
    return after


async def set_override(seconds: int, output_type: str, tier: str | None, price: int | None, admin: dict) -> dict:
    """Pin (or with price=None, unpin) the price of one table cell."""
    from services.audit_service import record_audit

    if int(seconds) not in DURATION_SNAPS or output_type not in OUTPUT_TYPES:
        raise ValueError("مدة أو نوع مخرج غير معروف")
    if price is not None and (isinstance(price, bool) or not isinstance(price, (int, float)) or not 1 <= price <= 10000):
        raise ValueError("السعر لازم يكون بين 1 و10000 ريال")
    key = cell_key(seconds, output_type, tier)
    update = ({"$unset": {f"overrides.{key}": ""}} if price is None
              else {"$set": {f"overrides.{key}": int(price)}})
    update.setdefault("$set", {}).update({"updated_at": _now(), "updated_by": admin.get("email")})
    await db.pricing_settings.update_one({"id": SETTINGS_ID}, {**update, "$setOnInsert": {"id": SETTINGS_ID}},
                                         upsert=True)
    invalidate()
    await record_audit(
        entity_type="pricing_config", entity_id=SETTINGS_ID, action="pricing.override",
        actor_id=admin.get("id"), actor_email=admin.get("email"),
        summary=(f"سعر يدوي {key} = {int(price)} ر.س" if price is not None else f"رجوع للسعر المحسوب {key}"),
        after={"cell": key, "price_sar": price},
    )
    return await get_settings()


# ---------------------------------------------------------------- unit prices
async def current_prices() -> dict:
    """Unit prices of the models in use now (catalog), falling back to the
    measured constants above for any model without a catalog price."""
    from services import engine_config, model_catalog
    from services.config_service import resolve_model

    pacing = await engine_config.get_pacing()
    quality = pacing["image_quality"]

    async def stage_entry(stage: str) -> dict | None:
        provider, model, _src = await resolve_model(stage, "", "")
        return await model_catalog.find_model(provider, model)

    async def tier_entry(tier: str) -> dict | None:
        return await model_catalog.find_model(*(await model_catalog.video_model_for_tier(tier)))

    def pick(value, fallback):
        return value if isinstance(value, (int, float)) else fallback

    return {
        "text": round(sum([await text_stage_cost(stage, await stage_entry(stage)) for stage in TEXT_TOKENS]), 4),
        "image_sheet": pick(model_catalog.unit_price(await stage_entry("child_character_i2i"),
                                                     quality.get("child_character_i2i", "high")), IMAGE_HIGH),
        "image_shot": pick(model_catalog.unit_price(await stage_entry("scene_image_generation"),
                                                    quality.get("scene_image_generation", "high")), IMAGE_MEDIUM),
        "music_per_minute": pick(model_catalog.unit_price(await stage_entry("music_generation")), MUSIC_PER_MINUTE),
        "narration_per_minute": pick(model_catalog.unit_price(await stage_entry("narration_generation")), 0.0),
        "video_per_second": {t: pick(model_catalog.unit_price(await tier_entry(t)), v["cost_per_second_usd"])
                             for t, v in VIDEO_TIERS.items()},
        "shot_seconds": pacing["shot_seconds"],
    }


async def text_stage_cost(stage: str, entry: dict | None) -> float:
    """One run of a text stage: the model's token price × the tokens the stage
    spends; an unpriced model gets its share of the measured Claude cost."""
    tokens_in, tokens_out = TEXT_TOKENS[stage]
    price = (entry or {}).get("price") or {}
    if isinstance(price.get("input_usd"), (int, float)) and isinstance(price.get("output_usd"), (int, float)):
        return (tokens_in * price["input_usd"] + tokens_out * price["output_usd"]) / 1_000_000
    return TEXT_PER_STORY * (0.15 if stage == "scenario_generation" else 0.85)


# ---------------------------------------------------------------- price
def cost_usd(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER,
             prices: dict | None = None) -> float:
    p = {**DEFAULT_PRICES, **(prices or {})}
    shots = max(1, round(seconds / (p.get("shot_seconds") or SHOT_SECONDS)))
    cost = p["text"] + (CAST_SHEETS + 1) * p["image_sheet"] + shots * p["image_shot"]
    if output_type in ("video", "both"):
        per_second = p["video_per_second"].get(tier, p["video_per_second"][DEFAULT_VIDEO_TIER])
        cost += seconds * CLIP_SECONDS_FACTOR * per_second
        cost += (seconds + 8) / 60 * p["music_per_minute"]
        cost += seconds / 60 * p["narration_per_minute"]
    return round(cost, 3)


def loaded_cost_sar(cost: float, settings: dict | None = None) -> float:
    """Cost in SAR with the retry buffer and payment fees on top."""
    s = settings or DEFAULT_SETTINGS
    return cost * s["usd_to_sar"] * (1 + s["retry_buffer"]) / (1 - s["payment_fee"])


def computed_price(loaded_sar: float, settings: dict | None = None) -> int:
    s = settings or DEFAULT_SETTINGS
    return max(int(s["min_price_sar"]), _ends_in_9(loaded_sar / (1 - s["target_margin"])))


def price_sar(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER,
              prices: dict | None = None, settings: dict | None = None) -> int:
    s = settings or DEFAULT_SETTINGS
    override = (s.get("overrides") or {}).get(cell_key(seconds, output_type, tier))
    if override:
        return int(override)
    return computed_price(loaded_cost_sar(cost_usd(seconds, output_type, tier, prices), s), s)


def with_vat(price: float, settings: dict | None = None) -> dict:
    rate = float((settings or DEFAULT_SETTINGS).get("vat_rate") or 0)
    vat = round(price * rate, 2)
    return {"vat_rate": rate, "vat_sar": vat, "total_sar": round(price + vat, 2)}


def quote(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER,
          prices: dict | None = None, settings: dict | None = None) -> dict:
    tier = _tier_for(output_type, tier)
    s = settings or DEFAULT_SETTINGS
    price = price_sar(seconds, output_type, tier, prices, s)
    return {
        "seconds": seconds,
        "output_type": output_type,
        "video_tier": tier,
        "price_sar": price,  # before VAT
        **with_vat(price, s),
        "cost_usd": cost_usd(seconds, output_type, tier, prices),
        "overridden": cell_key(seconds, output_type, tier) in (s.get("overrides") or {}),
        "currency": "SAR",
        "vat_included": False,
    }


def tier_quotes(seconds: int, output_type: str = "both", prices: dict | None = None,
                settings: dict | None = None) -> list[dict]:
    """Both video tiers for the builder (PDF-only orders have no video tier)."""
    tiers = VIDEO_TIERS if output_type in ("video", "both") else {DEFAULT_VIDEO_TIER: VIDEO_TIERS[DEFAULT_VIDEO_TIER]}
    return [{**quote(seconds, output_type, t, prices, settings), "label_ar": VIDEO_TIERS[t]["label_ar"]} for t in tiers]


def price_table(prices: dict, settings: dict) -> list[dict]:
    """Every (length, deliverable, tier) cell with its cost, computed price,
    manual price if any, and the margin left after the loaded cost."""
    rows = []
    for seconds in DURATION_SNAPS:
        for output_type in OUTPUT_TYPES:
            tiers = list(VIDEO_TIERS) if output_type != "pdf" else [DEFAULT_VIDEO_TIER]
            for tier in tiers:
                cost = cost_usd(seconds, output_type, tier, prices)
                loaded = loaded_cost_sar(cost, settings)
                computed = computed_price(loaded, settings)
                override = (settings.get("overrides") or {}).get(cell_key(seconds, output_type, tier))
                final = int(override) if override else computed
                rows.append({
                    "key": cell_key(seconds, output_type, tier),
                    "seconds": seconds,
                    "output_type": output_type,
                    "video_tier": None if output_type == "pdf" else tier,
                    "cost_usd": cost,
                    "cost_sar": round(cost * settings["usd_to_sar"], 2),
                    "loaded_cost_sar": round(loaded, 2),
                    "computed_price_sar": computed,
                    "override_sar": int(override) if override else None,
                    "price_sar": final,
                    "margin_pct": round((1 - loaded / final) * 100, 1) if final else None,
                })
    return rows


async def current_quote(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER) -> dict:
    return quote(seconds, output_type, tier, await current_prices(), await get_settings())


async def current_tier_quotes(seconds: int, output_type: str = "both") -> list[dict]:
    return tier_quotes(seconds, output_type, await current_prices(), await get_settings())
