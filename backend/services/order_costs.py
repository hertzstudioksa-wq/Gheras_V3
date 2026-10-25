"""What an order actually cost (M6): the work its records show was done, priced
with the catalog price of the model each record names.

Counted from the records the pipeline writes: scenario batches and plans
(including regenerations), character sheets, covers (including redraws), shot
keyframes, clip seconds per clip model, narration and music minutes. Text
stages don't record tokens, so a run is priced at the stage's measured token
budget × the model it uses now. Takes that failed before writing a record are
not counted; the estimate's retry buffer covers them.

Comfy Cloud bills GPU time, not images or seconds of video: its keyframes,
covers and Wan clips cost the GPU seconds their jobs ran (failed jobs too) ×
the setting comfy.usd_per_gpu_second. The catalog's per-image / per-second
Comfy prices only feed the customer price.
"""
from __future__ import annotations

from db import db
from services import model_catalog, story_pricing

REVIEW_USD = 0.005  # one automatic review look (Haiku vision via fal)


async def _price_by_model(model_name: str | None, quality: str | None = None) -> float | None:
    if not model_name:
        return None
    entry = await db.model_catalog.find_one({"model_name": model_name}, {"_id": 0})
    return model_catalog.unit_price(entry, quality)


async def actual_cost(order: dict) -> dict:
    from services import engine_config
    from services.config_service import resolve_model

    from services.ai.comfy import usd_per_gpu_second

    order_id = order["id"]
    settings = await story_pricing.get_settings()
    gpu_usd = await usd_per_gpu_second()
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

    covers, comfy_covers, cover_gpu = 0, 0, 0.0
    async for c in db.scene_images.find({"order_id": order_id, "kind": "cover", "source_type": {"$ne": "mock"}},
                                        {"_id": 0, "model": 1, "gpu_seconds": 1}):
        if str(c.get("model") or "").startswith("comfy/") and c.get("gpu_seconds"):
            comfy_covers, cover_gpu = comfy_covers + 1, cover_gpu + float(c["gpu_seconds"])
        else:
            covers += 1
    add("cover", "الغلاف", covers, "صورة", story_pricing.IMAGE_HIGH,
        note="شامل إعادة الرسم" if covers > 1 else None)
    add("cover", "الغلاف (Comfy)", cover_gpu, "ثانية GPU", gpu_usd, note=f"{comfy_covers} صورة")

    # Keyframes and clips (shot engine); older orders drew one image per scene.
    shot_quality = quality.get("scene_image_generation", "high")
    keyframes: dict[str, int] = {}
    clip_seconds: dict[str, float] = {}
    comfy_keyframes = [0, 0.0]   # images, GPU seconds
    comfy_clips = [0.0, 0.0]     # video seconds, GPU seconds
    reviews = 0
    async for s in db.shot_assets.find({"order_id": order_id}, {"_id": 0, "keyframe_url": 1, "image_model": 1,
                                                                "clip_seconds": 1, "clip_model": 1, "clip_url": 1,
                                                                "keyframe_review": 1, "clip_review": 1,
                                                                "clip_calm_redo": 1, "paid_keyframes": 1,
                                                                "paid_clip_seconds": 1, "comfy_clip_seconds": 1,
                                                                "comfy_clip_model": 1, "keyframe_gpu_seconds": 1,
                                                                "clip_gpu_seconds": 1}):
        # Every attempt sent is paid: the review's redos and the admin's
        # single-shot redos too. Shots made before the counters existed fall back
        # to what was kept (twice when the review sent it back).
        kr, cr = s.get("keyframe_review") or {}, s.get("clip_review") or {}
        if s.get("keyframe_url") or s.get("paid_keyframes"):
            drawn = s.get("paid_keyframes") or (2 if kr.get("redrawn") else 1)
            if str(s.get("image_model") or "").startswith("comfy/") and s.get("keyframe_gpu_seconds"):
                comfy_keyframes[0] += drawn
                comfy_keyframes[1] += float(s["keyframe_gpu_seconds"])
            else:
                keyframes[s.get("image_model")] = keyframes.get(s.get("image_model"), 0) + drawn
        if s.get("paid_clip_seconds") or (s.get("clip_url") and s.get("clip_seconds")):
            paid = s.get("paid_clip_seconds") or float(s["clip_seconds"]) * (2 if s.get("clip_calm_redo") else 1)
            # Seconds sent to Comfy are Comfy's (GPU time) even when Kling rescued the shot.
            on_comfy = float(s.get("comfy_clip_seconds") or 0)
            if on_comfy and s.get("clip_gpu_seconds"):
                comfy_clips[0] += on_comfy
                comfy_clips[1] += float(s["clip_gpu_seconds"])
            elif on_comfy:  # no GPU time recorded: the catalog's per-second estimate
                model = s.get("comfy_clip_model") or "comfy/clip_wan22"
                clip_seconds[model] = clip_seconds.get(model, 0) + on_comfy
            if float(paid) - on_comfy > 0:
                clip_seconds[s.get("clip_model")] = clip_seconds.get(s.get("clip_model"), 0) + float(paid) - on_comfy
        elif s.get("clip_gpu_seconds"):  # only failed Comfy jobs: their GPU time was still paid
            comfy_clips[1] += float(s["clip_gpu_seconds"])
        looks = [r for r in (kr, cr) if r and not r.get("skipped")]
        reviews += len(looks) + (1 if s.get("clip_calm_redo") else 0) + (1 if kr.get("redrawn") else 0)
    if not keyframes:
        n = await db.scene_images.count_documents({"order_id": order_id, "kind": "scene", "source_type": {"$ne": "mock"}})
        if n:
            keyframes[None] = n
    for model, n in keyframes.items():
        unit = await _price_by_model(model, shot_quality)
        add("keyframes", "صور اللقطات", n, "صورة", unit if unit is not None else story_pricing.IMAGE_MEDIUM, note=model)
    add("keyframes", "صور اللقطات (Comfy)", comfy_keyframes[1], "ثانية GPU", gpu_usd,
        note=f"comfy/keyframe_qwen21 — {comfy_keyframes[0]} صورة")
    for model, seconds in clip_seconds.items():
        add("clips", "مقاطع الفيديو", seconds, "ثانية", await _price_by_model(model), note=model)
    add("clips", "مقاطع الفيديو (Comfy)", comfy_clips[1], "ثانية GPU", gpu_usd,
        note=f"comfy/clip_wan22 — {comfy_clips[0]:g} ث فيديو")
    if reviews:
        # Haiku vision, a keyframe or four clip frames: about half a cent a look.
        add("reviews", "المراجعة الآلية", reviews, "مراجعة", REVIEW_USD, note="anthropic/claude-haiku-5.5")

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
