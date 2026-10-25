"""Public endpoints."""
from fastapi import APIRouter, Header, HTTPException, Response
from db import db

router = APIRouter(prefix="/public", tags=["public"])
# Admin prompt direction stays server-side.
HIDDEN = {"_id": 0, "prompt_fragment": 0}


@router.get("/media/{file_id}")
async def public_media(file_id: str, range_header: str | None = Header(None, alias="Range")):
    """Homepage media the admin uploaded (scope "site"). Nothing else is served
    here: customers' photos and stories stay behind their own tokens."""
    from routes.upload_routes import file_response

    rec = await db.files.find_one({"id": file_id, "scope": "site", "is_deleted": False}, {"_id": 0})
    if not rec:
        raise HTTPException(status_code=404, detail="الملف غير موجود")
    return await file_response(rec, range_header, cache="public, max-age=86400")


@router.get("/payment-methods")
async def payment_methods():
    """What the homepage may promise: card payments only once Moyasar has a key."""
    from services import moyasar

    return {"card": bool(await moyasar.secret_key()), "wallet": True}


@router.get("/categories")
async def list_categories():
    cats = await db.categories.find({"is_active": True}, HIDDEN).sort("sort_order", 1).to_list(100)
    for c in cats:
        subs = await db.subcategories.find(
            {"category_id": c["id"], "is_active": True}, HIDDEN
        ).sort("sort_order", 1).to_list(100)
        c["subcategories"] = subs
    return cats


@router.get("/story-options")
async def list_story_options():
    items = await db.story_options.find(
        {"is_active": True, "is_hidden": False}, HIDDEN
    ).sort("sort_order", 1).to_list(500)
    grouped: dict[str, list] = {"type": [], "tone": [], "setting": [], "language": [], "voice": []}
    for it in items:
        k = it.get("kind")
        if k in grouped:
            grouped[k].append(it)
    return grouped


@router.get("/art-styles")
async def list_art_styles():
    """The art styles a parent can pick in the builder (the default one first)."""
    items = await db.style_presets.find(
        {"active": True}, {"_id": 0, "key": 1, "name_ar": 1, "description_ar": 1, "is_default": 1, "version": 1}
    ).sort("sort_order", 1).to_list(50)
    for s in items:
        # The version busts browser caches when the admin changes the style's image.
        s["thumbnail"] = f"/api/public/art-styles/{s['key']}/thumbnail?v={s.pop('version', 1)}"
    return sorted(items, key=lambda s: not s.get("is_default"))


_thumb_cache: dict[tuple[str, int], bytes] = {}


@router.get("/art-styles/{key}/thumbnail")
async def art_style_thumbnail(key: str):
    """A small JPEG of the style for the builder: its thumbnail if the admin
    uploaded one, else its reference image (made-up characters, never a customer's photo)."""
    import io
    from PIL import Image
    from services import engine_config

    style = await db.style_presets.find_one({"key": key, "active": True}, {"_id": 0})
    if not style:
        raise HTTPException(status_code=404, detail="غير موجود")
    cache_key = (key, int(style.get("version") or 1))
    if cache_key not in _thumb_cache:
        src = await engine_config.style_reference_bytes(
            {"reference_image": style.get("thumbnail_url") or style.get("reference_image")})
        if not src:
            raise HTTPException(status_code=404, detail="لا توجد صورة")
        with Image.open(io.BytesIO(src)) as img:
            img = img.convert("RGB")
            img.thumbnail((720, 720))
            out = io.BytesIO()
            img.save(out, format="JPEG", quality=85)
        _thumb_cache[cache_key] = out.getvalue()
    return Response(content=_thumb_cache[cache_key], media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=3600"})


@router.get("/content")
async def list_content():
    items = await db.content.find({}, {"_id": 0}).to_list(500)
    return {it["key"]: it["value"] for it in items}


@router.get("/settings")
async def list_settings():
    """Only the settings marked public (the rest stay server-side)."""
    from routes.admin_routes import KNOWN_SETTINGS

    public = {k: meta for k, meta in KNOWN_SETTINGS.items() if meta.get("public")}
    stored = {s["key"]: s.get("value") async for s in db.settings.find({"key": {"$in": list(public)}}, {"_id": 0})}
    return {k: stored.get(k, meta["default"]) for k, meta in public.items()}


@router.get("/story-price")
async def story_price(seconds: int = 60, output_type: str = "both"):
    """Price per video tier for the builder (same quote the order stores)."""
    from models import duration_meta
    from services.story_pricing import current_tier_quotes

    seconds = duration_meta(seconds)["seconds"]  # snap to an allowed length
    # Our cost per tier stays internal (it showed every visitor the margin).
    tiers = [{k: v for k, v in t.items() if k not in ("cost_usd", "overridden")}
             for t in await current_tier_quotes(seconds, output_type)]
    return {"seconds": seconds, "output_type": output_type, "tiers": tiers}
