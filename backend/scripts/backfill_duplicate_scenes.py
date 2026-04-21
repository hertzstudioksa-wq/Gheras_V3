"""One-shot backfill: regenerate production plans for legacy orders whose
scene_plans contain duplicate narration or book text.

Idempotent: safe to re-run. Only touches orders that still have dupes.
"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import db  # noqa
from services.production_service import generate_production_plan, build_docs  # noqa


async def find_duplicated_orders() -> list[str]:
    cursor = db.scene_plans.aggregate([
        {"$match": {"is_archived": False}},
        {"$group": {
            "_id": "$order_id",
            "narrs": {"$addToSet": "$narration_text"},
            "books": {"$addToSet": "$book_text"},
            "count": {"$sum": 1},
        }},
    ])
    ids = []
    async for g in cursor:
        if len(g["narrs"]) < g["count"] or len(g["books"]) < g["count"]:
            ids.append(g["_id"])
    return ids


async def regenerate_one(order_id: str) -> None:
    order = await db.orders.find_one({"id": order_id}, {"_id": 0})
    if not order:
        print(f"  [skip] {order_id} — order missing")
        return
    scenario_id = order.get("selected_scenario_id")
    if not scenario_id:
        print(f"  [skip] {order_id} — no selected scenario")
        return
    scenario = await db.scenarios.find_one({"id": scenario_id}, {"_id": 0})
    if not scenario:
        print(f"  [skip] {order_id} — scenario missing")
        return
    duration = order.get("duration") or {}
    scene_target = int(duration.get("scene_target") or 6)

    payload, src, err = await generate_production_plan(order, scenario, scene_target)
    run_id = str(uuid.uuid4())
    docs = build_docs(order, payload, run_id, src)

    # Archive old plan/scenes/pages (preserve history) and insert fresh ones.
    await db.production_plans.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})
    await db.scene_plans.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})
    await db.book_pages.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})
    await db.character_profiles.update_many({"order_id": order_id}, {"$set": {"is_archived": True}})

    await db.production_plans.insert_one(docs["plan"])
    if docs["scenes"]:
        await db.scene_plans.insert_many(docs["scenes"])
    if docs["book_pages"]:
        await db.book_pages.insert_many(docs["book_pages"])
    if docs["character_profiles"]:
        await db.character_profiles.insert_many(docs["character_profiles"])

    await db.orders.update_one(
        {"id": order_id},
        {"$set": {"production_plan_id": docs["plan"]["id"]}},
    )

    # Verify
    sp = await db.scene_plans.find({"order_id": order_id, "is_archived": False}).to_list(20)
    nset = {s.get("narration_text", "") for s in sp}
    bset = {s.get("book_text", "") for s in sp}
    print(f"  [done] {order_id[:12]} source={src} scenes={len(sp)} unique_narr={len(nset)} unique_book={len(bset)}")


async def main():
    orders = await find_duplicated_orders()
    print(f"=== Found {len(orders)} orders with duplicated scene content ===")
    for oid in orders:
        await regenerate_one(oid)
    # Re-verify
    remaining = await find_duplicated_orders()
    print(f"\n=== Remaining duplicated orders after backfill: {len(remaining)} ===")


if __name__ == "__main__":
    asyncio.run(main())
