"""MongoDB connection singleton + indexes."""
import os
from motor.motor_asyncio import AsyncIOMotorClient

_mongo_url = os.environ["MONGO_URL"]
_db_name = os.environ["DB_NAME"]

client = AsyncIOMotorClient(_mongo_url)
db = client[_db_name]


async def ensure_indexes():
    await db.users.create_index("email", unique=True)
    await db.users.create_index("id", unique=True)
    await db.orders.create_index("user_id")
    await db.orders.create_index("status")
    await db.drafts.create_index("user_id", unique=True)
    await db.categories.create_index("slug", unique=True)
    await db.subcategories.create_index("category_id")
    await db.story_options.create_index([("kind", 1), ("sort_order", 1)])
    await db.content.create_index("key", unique=True)
    await db.prompts.create_index("key", unique=True)
    await db.settings.create_index("key", unique=True)
    await db.files.create_index("storage_path")
    await db.files.create_index("user_id")
