"""Customer price for a story by length, deliverable and video tier.

Cost comes from what one story actually uses (measured on the Yaman test order
against fal's invoice, 2026-10-24), then a retry buffer, payment fees and the
target margin are added and the result is rounded up to a price ending in 9.
The admin pricing page (M6) will make these numbers editable; until then they
live here so the builder and the order use the same quote.
"""
from __future__ import annotations

import math

from services.config_service import DEFAULT_VIDEO_TIER, VIDEO_TIERS
from services.house_style import SHOT_SECONDS

USD_TO_SAR = 3.75
# Unit costs (USD) observed on fal.
IMAGE_HIGH = 0.17      # character sheets + cover (GPT Image 2 high)
IMAGE_MEDIUM = 0.06    # shot keyframes (GPT Image 2 medium)
MUSIC_PER_MINUTE = 0.60
TEXT_PER_STORY = 0.35  # scenarios + production plan (Claude via fal)
CAST_SHEETS = 3        # child + one relative + one other (horse, pet...) on average
# Clip seconds paid per story second: line gaps, the end tail and 5/10 s rounding.
CLIP_SECONDS_FACTOR = 1.33

RETRY_BUFFER = 0.15    # regenerated shots, failed takes
PAYMENT_FEE = 0.03     # card / mada processing
TARGET_MARGIN = 0.50
MIN_PRICE_SAR = 39


def _ends_in_9(sar: float) -> int:
    return int(math.ceil((sar + 1) / 10.0) * 10 - 1)


def cost_usd(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER) -> float:
    shots = max(1, round(seconds / SHOT_SECONDS))
    cost = TEXT_PER_STORY + (CAST_SHEETS + 1) * IMAGE_HIGH + shots * IMAGE_MEDIUM
    if output_type in ("video", "both"):
        per_second = VIDEO_TIERS.get(tier, VIDEO_TIERS[DEFAULT_VIDEO_TIER])["cost_per_second_usd"]
        cost += seconds * CLIP_SECONDS_FACTOR * per_second
        cost += (seconds + 8) / 60 * MUSIC_PER_MINUTE
    return round(cost, 3)


def price_sar(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER) -> int:
    loaded = cost_usd(seconds, output_type, tier) * USD_TO_SAR * (1 + RETRY_BUFFER) / (1 - PAYMENT_FEE)
    return max(MIN_PRICE_SAR, _ends_in_9(loaded / (1 - TARGET_MARGIN)))


def quote(seconds: int, output_type: str = "both", tier: str = DEFAULT_VIDEO_TIER) -> dict:
    tier = tier if tier in VIDEO_TIERS else DEFAULT_VIDEO_TIER
    return {
        "seconds": seconds,
        "output_type": output_type,
        "video_tier": tier,
        "price_sar": price_sar(seconds, output_type, tier),
        "cost_usd": cost_usd(seconds, output_type, tier),
        "currency": "SAR",
        "vat_included": False,
    }


def tier_quotes(seconds: int, output_type: str = "both") -> list[dict]:
    """Both video tiers for the builder (PDF-only orders have no video tier)."""
    tiers = VIDEO_TIERS if output_type in ("video", "both") else {DEFAULT_VIDEO_TIER: VIDEO_TIERS[DEFAULT_VIDEO_TIER]}
    return [{**quote(seconds, output_type, t), "label_ar": VIDEO_TIERS[t]["label_ar"]} for t in tiers]
