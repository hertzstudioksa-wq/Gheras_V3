"""Public endpoints: categories, styles, content, plans."""
from fastapi import APIRouter
from db import db

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/categories")
async def list_categories():
    cats = await db.categories.find({"is_active": True}, {"_id": 0}).sort("sort_order", 1).to_list(100)
    # attach subcategories
    for c in cats:
        subs = await db.subcategories.find(
            {"category_id": c["id"], "is_active": True}, {"_id": 0}
        ).sort("sort_order", 1).to_list(100)
        c["subcategories"] = subs
    return cats


@router.get("/styles")
async def list_styles():
    return await db.story_styles.find({"is_active": True}, {"_id": 0}).sort("sort_order", 1).to_list(100)


@router.get("/content")
async def list_content():
    items = await db.content.find({}, {"_id": 0}).to_list(500)
    return {it["key"]: it["value"] for it in items}


@router.get("/plans")
async def list_plans():
    return await db.plans.find({"is_active": True}, {"_id": 0}).sort("sort_order", 1).to_list(50)


@router.get("/settings")
async def list_settings():
    items = await db.settings.find({}, {"_id": 0}).to_list(200)
    return {it["key"]: it["value"] for it in items}
