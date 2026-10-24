"""What an order actually cost (M6): the work its records show was done, priced
with the catalog price of the model each record names.

Counted from the records the pipeline writes: scenario batches and plans
(including regenerations), character sheets, covers (including redraws), shot
keyframes, clip seconds per clip model, narration and music minutes. Text
stages don't record tokens, so a run is priced at the stage's measured token
budget × the model it uses now. Takes that failed before writing a record are
not counted; the estimate's retry buffer covers them.
"""
from __future__ import annotations

from db import db
from services import model_catalog, story_pricing


async def _price_by_model(model_name: str | None, quality: str | None = None) -> float | None:
    if not model_name:
        return None
    entry = await db.model_catalog.find_one({"model_name": model_name}, {"_id": 0})
    return model_catalog.unit_price(entry, quality)


async def actual_cost(order: dict) -> dict:
    from services import engine_config
    from services.config_service import resolve_model

    order_id = order["id"]
    settings = await story_pricing.get_settings()
    quality = (await engine_config.get_pacing())["image_quality"]
    items: list[dict] = []

    def add(key, label, quantity, unit, unit_usd, note=None):
        if not quantity:
            return
        items.append({
            "key": key, "label_ar": label, "quantity": round(quantity, 2), "unit": unit,
            "unit_usd": None if unit_usd is None else round(unit_usd, 4),
            "cost_usd": round(quantity * (unit_usd or 0), 4), "priced": unit_usd is not None, "note": note,
        })

    # Text: one scenario run per batch, one planning run per plan (regenerations included).
    for stage, label, quantity in (
        ("scenario_generation", "سيناريوهات", len(await db.scenarios.distinct("scenario_batch_id", {"order_id": order_id}))),
        ("production_planning", "خطة الإنتاج", await db.production_plans.count_documents({"order_id": order_id})),
    ):
        provider, model, _src = await resolve_model(stage, "", "")
        entry = await model_catalog.find_model(provider, model)
        add(stage, label, quantity, "تشغيلة", await story_pricing.text_stage_cost(stage, entry), note=model)

    # Character sheets: the child, uploaded extras, generated cast.
    sheet_quality = quality.get("child_character_i2i", "high")
    sheets: dict[str, int] = {}
    async for d in db.child_character_assets.find({"order_id": order_id, "mock": {"$ne": True}, "status": "completed"},
                                                  {"_id": 0, "model_name": 1}):
        sheets[d.get("model_name")] = sheets.get(d.get("model_name"), 0) + 1
    async for d in db.extra_character_assets.find({"order_id": order_id, "mock": {"$ne": True}, "status": "completed"},
                                                  {"_id": 0, "model_name": 1}):
        sheets[d.get("model_name")] = sheets.get(d.get("model_name"), 0) + 1
    async for d in db.character_sheets.find({"order_id": order_id}, {"_id": 0, "model": 1}):
        sheets[d.get("model")] = sheets.get(d.get("model"), 0) + 1
    for model, n in sheets.items():
        unit = await _price_by_model(model, sheet_quality)
        add("character_sheets", "شيتات الشخصيات", n, "صورة", unit if unit is not None else story_pricing.IMAGE_HIGH, note=model)

    covers = await db.scene_images.count_documents({"order_id": order_id, "kind": "cover", "source_type": {"$ne": "mock"}})
    add("cover", "الغلاف", covers, "صورة", story_pricing.IMAGE_HIGH,
        note="شامل إعادة الرسم" if covers > 1 else None)

    # Keyframes and clips (shot engine); older orders drew one image per scene.
    shot_quality = quality.get("scene_image_generation", "high")
    keyframes: dict[str, int] = {}
    clip_seconds: dict[str, float] = {}
    async for s in db.shot_assets.find({"order_id": order_id}, {"_id": 0, "keyframe_url": 1, "image_model": 1,
                                                                "clip_seconds": 1, "clip_model": 1, "clip_url": 1}):
        if s.get("keyframe_url"):
            keyframes[s.get("image_model")] = keyframes.get(s.get("image_model"), 0) + 1
        if s.get("clip_url") and s.get("clip_seconds"):
            clip_seconds[s.get("clip_model")] = clip_seconds.get(s.get("clip_model"), 0) + float(s["clip_seconds"])
    if not keyframes:
        n = await db.scene_images.count_documents({"order_id": order_id, "kind": "scene", "source_type": {"$ne": "mock"}})
        if n:
            keyframes[None] = n
    for model, n in keyframes.items():
        unit = await _price_by_model(model, shot_quality)
        add("keyframes", "صور اللقطات", n, "صورة", unit if unit is not None else story_pricing.IMAGE_MEDIUM, note=model)
    for model, seconds in clip_seconds.items():
        add("clips", "مقاطع الفيديو", seconds, "ثانية", await _price_by_model(model), note=model)

    narration: dict[str, float] = {}
    async for n in db.narration_assets.find({"order_id": order_id}, {"_id": 0, "model": 1, "duration_seconds": 1}):
        narration[n.get("model")] = narration.get(n.get("model"), 0) + float(n.get("duration_seconds") or 0) / 60
    for model, minutes in narration.items():
        add("narration", "السرد الصوتي", minutes, "دقيقة", await _price_by_model(model), note=model)

    async for m in db.music_tracks.find({"order_id": order_id, "real_call": True, "skipped": {"$ne": True}},
                                        {"_id": 0, "model": 1, "duration_seconds": 1}):
        unit = await _price_by_model(m.get("model"))
        add("music", "الموسيقى", float(m.get("duration_seconds") or 0) / 60, "دقيقة",
            unit if unit is not None else story_pricing.MUSIC_PER_MINUTE, note=m.get("model"))

    total_usd = round(sum(i["cost_usd"] for i in items), 3)
    total_sar = round(total_usd * settings["usd_to_sar"], 2)
    quote = order.get("price_quote") or {}
    payment = order.get("payment") or {}
    price = payment["amount_sar"] if payment.get("status") == "paid" else quote.get("price_sar")
    return {
        "items": items,
        "unpriced": [i["note"] or i["label_ar"] for i in items if not i["priced"]],
        "total_usd": total_usd,
        "total_sar": total_sar,
        "estimate_usd": quote.get("cost_usd"),
        "estimate_sar": round(quote["cost_usd"] * settings["usd_to_sar"], 2) if quote.get("cost_usd") else None,
        "price_sar": price,
        # What is left of the pre-VAT price after the actual cost and payment fees.
        "margin_sar": round(price * (1 - settings["payment_fee"]) - total_sar, 2) if price else None,
        "margin_pct": round((1 - total_sar / (price * (1 - settings["payment_fee"]))) * 100, 1) if price else None,
        "vs_estimate_pct": (round((total_usd / quote["cost_usd"] - 1) * 100, 1)
                            if quote.get("cost_usd") and total_usd else None),
    }
