"""Gheras — v2 main entry."""
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI, APIRouter  # noqa: E402
from starlette.middleware.cors import CORSMiddleware  # noqa: E402

from db import client, ensure_indexes  # noqa: E402
from seed import seed_all  # noqa: E402
from storage import init_storage  # noqa: E402
from routes.auth_routes import router as auth_router  # noqa: E402
from routes.public_routes import router as public_router  # noqa: E402
from routes.order_routes import router as order_router  # noqa: E402
from routes.draft_routes import router as draft_router  # noqa: E402
from routes.upload_routes import router as upload_router  # noqa: E402
from routes.admin_routes import router as admin_router  # noqa: E402
from routes.production_routes import user_router as production_user_router, admin_router as production_admin_router  # noqa: E402
from routes.media_routes import user_router as media_user_router, admin_router as media_admin_router  # noqa: E402
from routes.admin_config_routes import router as admin_config_router  # noqa: E402
from routes.admin_storyboard_routes import router as admin_storyboard_router  # noqa: E402
from routes.admin_pricing_routes import router as admin_pricing_router, order_router as admin_pricing_orders_router  # noqa: E402
from routes.admin_lab_routes import router as admin_lab_router  # noqa: E402
from routes.admin_secrets_routes import router as admin_secrets_router  # noqa: E402
from routes.admin_audit_routes import router as admin_audit_router  # noqa: E402
from routes.bundle_routes import admin_router as admin_bundle_router, user_router as bundle_user_router  # noqa: E402
from routes.payment_routes import (  # noqa: E402
    admin_router as admin_payment_router,
    checkout_router as checkout_router,
    webhook_router as stripe_webhook_router,
)

app = FastAPI(title="Gheras API v2", description="Arabic AI storytelling platform")
api_router = APIRouter(prefix="/api")


@api_router.get("/")
async def health():
    return {"ok": True, "service": "gheras", "version": "2", "status": "healthy"}


api_router.include_router(auth_router)
api_router.include_router(public_router)
api_router.include_router(order_router)
api_router.include_router(draft_router)
api_router.include_router(upload_router)
api_router.include_router(admin_router)
api_router.include_router(production_user_router)
api_router.include_router(production_admin_router)
api_router.include_router(media_user_router)
api_router.include_router(media_admin_router)
api_router.include_router(admin_config_router)
api_router.include_router(admin_storyboard_router)
api_router.include_router(admin_pricing_router)
api_router.include_router(admin_pricing_orders_router)
api_router.include_router(admin_lab_router)
api_router.include_router(admin_secrets_router)
api_router.include_router(admin_audit_router)
api_router.include_router(admin_bundle_router)
api_router.include_router(bundle_user_router)
api_router.include_router(admin_payment_router)
api_router.include_router(checkout_router)
api_router.include_router(stripe_webhook_router)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("gheras")


@app.on_event("startup")
async def on_startup():
    await ensure_indexes()
    await seed_all()
    try:
        init_storage()
    except Exception as e:
        logger.warning(f"Storage init deferred: {e}")
    logger.info("Gheras v2 backend ready")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
