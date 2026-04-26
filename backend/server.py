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
from routes.admin_preset_stacks_routes import router as admin_preset_stacks_router  # noqa: E402
from routes.admin_audit_routes import router as admin_audit_router  # noqa: E402
from routes.admin_assets_routes import router as admin_assets_router  # noqa: E402
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
api_router.include_router(admin_preset_stacks_router)
api_router.include_router(admin_audit_router)
api_router.include_router(admin_assets_router)
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
    from db import db
    try:
        from services.secret_overrides_service import apply_overrides_to_env
        n = await apply_overrides_to_env()
        if n:
            logger.info(f"applied {n} secure secret overrides at startup")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"secret overrides apply skipped: {e}")
    try:
        from services.preset_stacks_service import seed_default_presets
        n = await seed_default_presets()
        if n:
            logger.info(f"seeded {n} preset stacks")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"preset seeding skipped: {e}")
    try:
        from services.config_service import DEFAULT_PIPELINE
        existing = await db.pipeline_config.find_one({"id": "default"})
        if existing:
            # Phase I — sync any missing stages from DEFAULT_PIPELINE without
            # disturbing admin's customizations on existing stages.
            cur_order = existing.get("order") or []
            cur_stages = existing.get("stages") or {}
            patch = {}
            new_order = list(cur_order)
            # Phase I — drop legacy stages no longer in SUPPORTED_STAGES.
            from services.stage_lab_service import SUPPORTED_STAGES as _SUPPORTED
            new_order = [s for s in new_order if s in _SUPPORTED]
            for s in DEFAULT_PIPELINE["order"]:
                if s not in new_order:
                    new_order.append(s)
            new_stages = {k: v for k, v in cur_stages.items() if k in _SUPPORTED}
            for s, cfg in DEFAULT_PIPELINE["stages"].items():
                if s not in new_stages:
                    new_stages[s] = cfg
                else:
                    # Forward-fill new flags introduced in Phase I (gated_by_output_type, etc.)
                    merged = dict(cfg)
                    merged.update(new_stages[s])
                    new_stages[s] = merged
            if new_order != cur_order or new_stages != cur_stages:
                await db.pipeline_config.update_one(
                    {"id": "default"},
                    {"$set": {"order": new_order, "stages": new_stages}},
                )
                logger.info(f"pipeline_config migrated to include all {len(DEFAULT_PIPELINE['order'])} stages")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"pipeline_config migration skipped: {e}")
    try:
        init_storage()
    except Exception as e:
        logger.warning(f"Storage init deferred: {e}")
    logger.info("Gheras v2 backend ready")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
