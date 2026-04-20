"""MongoDB connection singleton."""
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
    await db.categories.create_index("slug", unique=True)
    await db.subcategories.create_index("category_id")
    await db.content.create_index("key", unique=True)
    await db.prompts.create_index("key", unique=True)
    await db.settings.create_index("key", unique=True)
