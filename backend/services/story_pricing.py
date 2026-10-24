"""Customer price for a story by length, deliverable and video tier.

Cost = what one story uses (counts measured on the Yaman test order against
fal's invoice and in the text bake-off, 2026-10-24) × the unit prices of the
models the stages use right now (model catalog, M4: text per token, images per
picture at the configured quality, video per second, music per minute), then a retry buffer, payment fees and the target
margin, rounded up to a price ending in 9. Switching a stage to a pricier model
in the admin therefore raises the price the parent sees. The admin pricing page
(M6) will make the margin/buffer/fees editable; until then they live here.
"""
from __future__ import annotations

import math

from services.config_service import DEFAULT_VIDEO_TIER, VIDEO_TIERS
from services.house_style import SHOT_SECONDS

USD_TO_SAR = 3.75
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

RETRY_BUFFER = 0.15    # regenerated shots, failed takes
PAYMENT_FEE = 0.03     # card / mada processing
TARGET_MARGIN = 0.50
MIN_PRICE_SAR = 39

DEFAULT_PRICES = {
    "text": TEXT_PER_STORY,
    "image_sheet": IMAGE_HIGH,
    "image_shot": IMAGE_MEDIUM,
    "music_per_minute": MUSIC_PER_MINUTE,
    "video_per_second": {t: v["cost_per_second_usd"] for t, v in VIDEO_TIERS.items()},
    "shot_seconds": SHOT_SECONDS,
}


def _ends_in_9(sar: float) -> int:
    return int(math.ceil((sar + 1) / 10.0) * 10 - 1)


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

    # Text: each stage's model price × the tokens that stage spends per story.
    text = 0.0
    for stage, (tokens_in, tokens_out) in TEXT_TOKENS.items():
        price = ((await stage_entry(stage)) or {}).get("price") or {}
        if isinstance(price.get("input_usd"), (int, float)) and isinstance(price.get("output_usd"), (int, float)):
            text += (tokens_in * price["input_usd"] + tokens_out * price["output_usd"]) / 1_000_000
        else:  # unpriced model: its share of the measured Claude cost
            text += TEXT_PER_STORY * (0.15 if stage == "scenario_generation" else 0.85)

    return {
        "text": round(text, 4),
        "image_sheet": pick(model_catalog.unit_price(await stage_entry("child_character_i2i"),
                                                     quality.get("child_character_i2i", "high")), IMAGE_HIGH),
        "image_shot": pick(model_catalog.unit_price(await stage_entry("scene_image_generation"),
                                                    quality.get("scene_image_generation", "high")), IMAGE_MEDIUM),
        "music_per_minute": pick(model_catalog.unit_price(await stage_entry("music_generation")), MUSIC_PER_MINUTE),
        "video_per_second": {t: pick(model_catalog.unit_price(await tier_entry(t)), v["cost_per_second_usd"])
                             for t, v in VIDEO_TIERS.items()},
        "shot_seconds": pacing["shot_seconds"],
    }


def cost_usd(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER,
             prices: dict | None = None) -> float:
    p = prices or DEFAULT_PRICES
    shots = max(1, round(seconds / (p.get("shot_seconds") or SHOT_SECONDS)))
    cost = p.get("text", TEXT_PER_STORY) + (CAST_SHEETS + 1) * p["image_sheet"] + shots * p["image_shot"]
    if output_type in ("video", "both"):
        per_second = p["video_per_second"].get(tier, p["video_per_second"][DEFAULT_VIDEO_TIER])
        cost += seconds * CLIP_SECONDS_FACTOR * per_second
        cost += (seconds + 8) / 60 * p["music_per_minute"]
    return round(cost, 3)


def price_sar(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER,
              prices: dict | None = None) -> int:
    loaded = cost_usd(seconds, output_type, tier, prices) * USD_TO_SAR * (1 + RETRY_BUFFER) / (1 - PAYMENT_FEE)
    return max(MIN_PRICE_SAR, _ends_in_9(loaded / (1 - TARGET_MARGIN)))


def quote(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER,
          prices: dict | None = None) -> dict:
    tier = tier if tier in VIDEO_TIERS else DEFAULT_VIDEO_TIER
    return {
        "seconds": seconds,
        "output_type": output_type,
        "video_tier": tier,
        "price_sar": price_sar(seconds, output_type, tier, prices),
        "cost_usd": cost_usd(seconds, output_type, tier, prices),
        "currency": "SAR",
        "vat_included": False,
    }


def tier_quotes(seconds: int, output_type: str = "both", prices: dict | None = None) -> list[dict]:
    """Both video tiers for the builder (PDF-only orders have no video tier)."""
    tiers = VIDEO_TIERS if output_type in ("video", "both") else {DEFAULT_VIDEO_TIER: VIDEO_TIERS[DEFAULT_VIDEO_TIER]}
    return [{**quote(seconds, output_type, t, prices), "label_ar": VIDEO_TIERS[t]["label_ar"]} for t in tiers]


async def current_quote(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER) -> dict:
    return quote(seconds, output_type, tier, await current_prices())


async def current_tier_quotes(seconds: int, output_type: str = "both") -> list[dict]:
    return tier_quotes(seconds, output_type, await current_prices())
