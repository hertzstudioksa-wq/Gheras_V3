"""Gheras — v2 main entry."""
import logging
import os
from datetime import datetime, timezone
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
from routes.admin_video_recovery_routes import router as admin_video_recovery_router  # noqa: E402
from routes.admin_pricing_routes import router as admin_pricing_router, order_router as admin_pricing_orders_router  # noqa: E402
from routes.admin_lab_routes import router as admin_lab_router  # noqa: E402
from routes.admin_secrets_routes import router as admin_secrets_router  # noqa: E402
from routes.admin_preset_stacks_routes import router as admin_preset_stacks_router  # noqa: E402
from routes.admin_audit_routes import router as admin_audit_router  # noqa: E402
from routes.admin_engine_routes import router as admin_engine_router  # noqa: E402
from routes.admin_assets_routes import router as admin_assets_router  # noqa: E402
from routes.admin_stage_control_routes import router as admin_stage_control_router  # noqa: E402
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
api_router.include_router(admin_video_recovery_router)
api_router.include_router(admin_pricing_router)
api_router.include_router(admin_pricing_orders_router)
api_router.include_router(admin_lab_router)
api_router.include_router(admin_secrets_router)
api_router.include_router(admin_preset_stacks_router)
api_router.include_router(admin_audit_router)
api_router.include_router(admin_engine_router)
api_router.include_router(admin_assets_router)
api_router.include_router(admin_stage_control_router)
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


class _SkipMigration(Exception):
    """Raised inside a startup migration block that was already applied."""


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

    # The two data migrations below rewrite admin-editable config, so they run
    # once per database (recorded in db.migrations). Re-running them on every
    # boot used to revert values that admins or presets had chosen on purpose.
    async def _already_applied(migration_id: str) -> bool:
        return bool(await db.migrations.find_one({"id": migration_id}, {"_id": 1}))

    async def _mark_applied(migration_id: str) -> None:
        await db.migrations.update_one(
            {"id": migration_id},
            {"$setOnInsert": {"id": migration_id, "applied_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True,
        )

    # Phase N migration — refresh model_registry rows that still hold a
    # pre-Phase-N default to the new canonical mapping.
    try:
        if await _already_applied("phase_n_model_registry"):
            raise _SkipMigration
        from services.config_service import DEFAULT_MODELS
        legacy_signatures = {
            "scenario_generation":         [("anthropic", "claude-sonnet-4-5-20250929")],
            "production_planning":         [("anthropic", "claude-sonnet-4-5-20250929")],
            "child_character_i2i":         [("gemini", "gemini-3.1-flash-image-preview"),
                                             ("openai", "gpt-image-1")],
            "extra_character_i2i":         [("gemini", "gemini-3.1-flash-image-preview"),
                                             ("openai", "gpt-image-1")],
            "scene_image_generation":      [("openai", "gpt-image-1"),
                                             ("gemini", "gemini-3.1-flash-image-preview")],
            "book_page_image_generation":  [("openai", "gpt-image-1"),
                                             ("gemini", "gemini-3.1-flash-image-preview")],
            "narration_generation":        [("mock", "mock-tts-v1")],
            "music_generation":            [("mock", "mock-music-v1"),
                                             ("elevenlabs", "eleven_music_v1")],
            "video_generation":            [("kling", "fal-ai/kling-video/v2.1/standard/image-to-video"),
                                             ("kling", "fal-ai/kling-video/v3/pro/image-to-video"),
                                             ("ffmpeg", "local-slideshow")],
        }
        for stage_key, sigs in legacy_signatures.items():
            row = await db.model_registry.find_one({"stage_key": stage_key}, {"_id": 0})
            if not row:
                continue
            current = (row.get("provider"), row.get("model_name"))
            if current in sigs:
                new = DEFAULT_MODELS.get(stage_key) or {}
                await db.model_registry.update_one(
                    {"stage_key": stage_key},
                    {"$set": {**new, "notes": "Phase N auto-migrated (per-capability fal.ai keys)"}},
                )
                logger.info(f"model_registry: Phase N migrated {stage_key} "
                            f"{current} → {new.get('provider')}/{new.get('model_name')} [{new.get('env_key')}]")
        await _mark_applied("phase_n_model_registry")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Phase N migration skipped: {e}")

    # Phase N — strict cartoon 2D prompt template migration. Bumps v1 → v2
    # for the visual stages so the new wording lands without manual seeding.
    try:
        if await _already_applied("phase_n_strict_2d_prompts"):
            raise _SkipMigration
        from seed import _build_prompt_template_seeds
        latest_seeds_list = await _build_prompt_template_seeds()
        latest_seeds = {s["stage_key"]: s for s in latest_seeds_list}
        STAGES_TO_BUMP = [
            "scene_image_generation",
            "book_page_image_generation",
            "extra_character_i2i",
            "video_generation",
            "child_character_i2i",
        ]
        import uuid as _uuid
        bumped = 0
        for stage in STAGES_TO_BUMP:
            current = await db.prompt_templates.find_one(
                {"stage_key": stage, "active": True}, {"_id": 0}
            )
            if current and "STRICT STYLE — soft pastel 2D" in (current.get("template_text") or ""):
                continue
            new_seed = latest_seeds.get(stage)
            if not new_seed:
                continue
            if current:
                await db.prompt_templates.update_one(
                    {"id": current["id"]},
                    {"$set": {"active": False,
                              "deactivated_at": datetime.now(timezone.utc).isoformat(),
                              "deactivated_reason": "phase_n_strict_cartoon_2d"}},
                )
            prev_versions = await db.prompt_templates.count_documents({"stage_key": stage})
            await db.prompt_templates.insert_one({
                "id":            str(_uuid.uuid4()),
                "stage_key":     stage,
                "name":          new_seed["name"],
                "template_text": new_seed["template_text"],
                "variables":     new_seed["variables"],
                "notes":         new_seed["notes"],
                "version":       prev_versions + 1,
                "active":        True,
                "created_at":    datetime.now(timezone.utc).isoformat(),
                "updated_at":    datetime.now(timezone.utc).isoformat(),
            })
            bumped += 1
        if bumped:
            logger.info(f"prompt_templates: Phase N strict-2D bumped {bumped} stages")
        await _mark_applied("phase_n_strict_2d_prompts")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Phase N prompt migration skipped: {e}")

    # Phase 1 — Emergent removed. Stored rows pointing at providers that no
    # longer have an executor (Emergent Claude/Gemini, fal_image) move to the
    # direct defaults; the child character stage is switched on because every
    # scene now relies on it for the child's likeness.
    try:
        if await _already_applied("phase1_direct_providers"):
            raise _SkipMigration
        from services.config_service import DEFAULT_MODELS
        for stage_key in ("scenario_generation", "production_planning", "child_character_i2i",
                          "extra_character_i2i", "scene_image_generation", "book_page_image_generation"):
            res = await db.model_registry.update_many(
                {"stage_key": stage_key},
                {"$set": {**DEFAULT_MODELS[stage_key], "notes": "Phase 1 auto-migrated (direct providers)"}},
            )
            if res.modified_count:
                logger.info(f"model_registry: Phase 1 migrated {stage_key} → "
                            f"{DEFAULT_MODELS[stage_key]['provider']}/{DEFAULT_MODELS[stage_key]['model_name']}")
        await db.pipeline_config.update_one(
            {"id": "default"}, {"$set": {"stages.child_character_i2i.enabled": True}},
        )
        await _mark_applied("phase1_direct_providers")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Phase 1 provider migration skipped: {e}")

    # Character sheets asked for a "transparent background"; image models draw
    # that as a grey checkerboard, which then leaks into every scene that uses
    # the sheet as reference. New template versions ask for plain white.
    try:
        if await _already_applied("character_white_background"):
            raise _SkipMigration
        import uuid as _uuid
        replacements = [
            ("with TRANSPARENT BACKGROUND", "on a plain pure white background (never a checkerboard or transparency pattern)"),
            ("Output: clean PNG, transparent background,", "Output: clean PNG on a plain pure white background,"),
            ("transparent background, clean PNG,", "plain pure white background (never a checkerboard), clean PNG,"),
        ]
        for stage in ("child_character_i2i", "extra_character_i2i"):
            current = await db.prompt_templates.find_one({"stage_key": stage, "active": True}, {"_id": 0})
            if not current or "transparent" not in (current.get("template_text") or "").lower():
                continue
            text = current["template_text"]
            for old, new in replacements:
                text = text.replace(old, new)
            now = datetime.now(timezone.utc).isoformat()
            await db.prompt_templates.update_one(
                {"id": current["id"]},
                {"$set": {"active": False, "deactivated_at": now, "deactivated_reason": "character_white_background"}},
            )
            await db.prompt_templates.insert_one({
                **{k: current[k] for k in ("stage_key", "name", "variables") if k in current},
                "id": str(_uuid.uuid4()),
                "template_text": text,
                "notes": "White background instead of transparent (avoids checkerboard artifacts).",
                "version": await db.prompt_templates.count_documents({"stage_key": stage}) + 1,
                "active": True,
                "created_at": now,
                "updated_at": now,
            })
            logger.info(f"prompt_templates: {stage} → white background version")
        await _mark_applied("character_white_background")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"character background prompt migration skipped: {e}")
    # Shot engine (M2): the child's character becomes a two-view reference sheet
    # in the house style, already wearing the story's outfit.
    try:
        if await _already_applied("house_style_character_sheet"):
            raise _SkipMigration
        import uuid as _uuid
        now = datetime.now(timezone.utc).isoformat()
        await db.prompt_templates.update_many(
            {"stage_key": "child_character_i2i", "active": True},
            {"$set": {"active": False, "deactivated_at": now, "deactivated_reason": "house_style_character_sheet"}},
        )
        await db.prompt_templates.insert_one({
            "id": str(_uuid.uuid4()),
            "stage_key": "child_character_i2i",
            "name": "Child character sheet (house style)",
            "variables": ["child_name", "child_age", "child_gender", "art_direction", "child_outfit"],
            "template_text": (
                "Turn the child in the uploaded photo into a character design reference sheet for an animated "
                "children's story. Art style: $art_direction Identity (mandatory): keep the child's real face shape, "
                "hairstyle, eyes, nose, smile, skin tone, age impression and gender recognizable; keep a hijab if the "
                "photo has one. Character: $child_name, $child_age years old ($child_gender), wearing $child_outfit. "
                "Full body front view standing, plus a smaller three-quarter view beside it, plain pure white "
                "background, no text, no labels."
            ),
            "notes": "M2 shot engine: two-view sheet in the house style with the story outfit.",
            "version": await db.prompt_templates.count_documents({"stage_key": "child_character_i2i"}) + 1,
            "active": True,
            "created_at": now,
            "updated_at": now,
        })
        await _mark_applied("house_style_character_sheet")
        logger.info("prompt_templates: child_character_i2i → house-style character sheet")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"house-style character sheet migration skipped: {e}")
    # Real-world photos (black-and-white, filtered, cropped, group shots): the
    # child's sheet gets the shared photo-handling rules too.
    try:
        if await _already_applied("character_sheet_photo_rules"):
            raise _SkipMigration
        import uuid as _uuid
        from services.house_style import PHOTO_RULES
        now = datetime.now(timezone.utc).isoformat()
        await db.prompt_templates.update_many(
            {"stage_key": "child_character_i2i", "active": True},
            {"$set": {"active": False, "deactivated_at": now, "deactivated_reason": "character_sheet_photo_rules"}},
        )
        await db.prompt_templates.insert_one({
            "id": str(_uuid.uuid4()),
            "stage_key": "child_character_i2i",
            "name": "Child character sheet (house style + photo rules)",
            "variables": ["child_name", "child_age", "child_gender", "art_direction", "child_outfit"],
            "template_text": (
                "Turn the child in the uploaded photo into a character design reference sheet for an animated "
                "children's story. Art style: $art_direction Character: $child_name, $child_age years old "
                f"($child_gender), wearing $child_outfit. {PHOTO_RULES} Full body front view standing, plus a smaller "
                "three-quarter view beside it, plain pure white background, no text, no labels."
            ),
            "notes": "Adds photo handling: black-and-white/filtered photos still give full natural color, cropped "
                     "photos get a full body, group photos use the main person, formal clothes replaced.",
            "version": await db.prompt_templates.count_documents({"stage_key": "child_character_i2i"}) + 1,
            "active": True,
            "created_at": now,
            "updated_at": now,
        })
        await _mark_applied("character_sheet_photo_rules")
        logger.info("prompt_templates: child_character_i2i → photo-handling rules")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"character sheet photo-rules migration skipped: {e}")
    # Owner-approved likeness approach (2026-10-24): their proven GPT 1.5 prompt,
    # fixed, run on GPT Image 2 with a neutral style reference; one tall figure in
    # the photo's own outfit unless the story needs other clothes.
    try:
        if await _already_applied("character_sheet_gpt2_style_ref"):
            raise _SkipMigration
        import uuid as _uuid
        from services.house_style import character_sheet_prompt
        text = character_sheet_prompt("$child_name, $child_age years old ($child_gender)", "__OUTFIT__").replace(
            "dress the character in __OUTFIT__", "$outfit_rule")
        now = datetime.now(timezone.utc).isoformat()
        await db.prompt_templates.update_many(
            {"stage_key": "child_character_i2i", "active": True},
            {"$set": {"active": False, "deactivated_at": now, "deactivated_reason": "character_sheet_gpt2_style_ref"}},
        )
        await db.prompt_templates.insert_one({
            "id": str(_uuid.uuid4()),
            "stage_key": "child_character_i2i",
            "name": "Child character (owner prompt + style reference)",
            "variables": ["child_name", "child_age", "child_gender", "outfit_rule"],
            "template_text": text,
            "notes": "Approved 2026-10-24 after the likeness bake-off: GPT Image 2 + neutral style reference image.",
            "version": await db.prompt_templates.count_documents({"stage_key": "child_character_i2i"}) + 1,
            "active": True,
            "created_at": now,
            "updated_at": now,
        })
        await _mark_applied("character_sheet_gpt2_style_ref")
        logger.info("prompt_templates: child_character_i2i → owner prompt + style reference")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"character sheet style-ref migration skipped: {e}")
    # M3: art styles, dialect profiles and pacing live in the database (seeded
    # once from the approved house style; admin edits are never overwritten).
    try:
        from services.engine_config import seed_engine_config
        await seed_engine_config()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"engine config seeding skipped: {e}")
    # M4: the model catalog (models a stage may use + their unit prices).
    try:
        from services.model_catalog import seed_catalog
        n = await seed_catalog()
        if n:
            logger.info(f"model catalog: seeded {n} models")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"model catalog seeding skipped: {e}")
    # M4: presets may only set catalog models. Archive the ones that point at
    # removed keys (EMERGENT_LLM_KEY) or untested models, bring "Gheras Default"
    # up to the current defaults, and drop stale "applied by preset" labels.
    try:
        if await _already_applied("presets_catalog_cleanup"):
            raise _SkipMigration
        from services.config_service import DEFAULT_MODELS
        from services.model_catalog import CAPABILITY_OF_STAGE, preset_is_valid
        now = datetime.now(timezone.utc).isoformat()
        default_map = {s: {k: DEFAULT_MODELS[s][k] for k in ("provider", "model_name", "env_key")}
                       for s in CAPABILITY_OF_STAGE}
        await db.preset_stacks.update_one(
            {"slug": "gheras-default"},
            {"$set": {"stage_map": default_map, "is_archived": False, "updated_at": now,
                      "description": "الإعدادات المعتمدة لكل المراحل (Claude عبر fal للنصوص، GPT Image 2 للصور، "
                                     "Gemini للصوت، Kling 2.5 Turbo للفيديو، ElevenLabs للموسيقى)."}})
        archived = []
        async for p in db.preset_stacks.find({"slug": {"$ne": "gheras-default"}, "is_archived": {"$ne": True}},
                                             {"_id": 0}):
            if not await preset_is_valid(p):
                await db.preset_stacks.update_one(
                    {"id": p["id"]}, {"$set": {"is_archived": True, "is_active": False, "updated_at": now,
                                               "archived_reason": "uses models outside the model catalog (M4)"}})
                archived.append(p.get("slug"))
        await db.model_registry.update_many({}, {"$set": {"applied_by_preset_id": None, "applied_by_preset_name": None}})
        await _mark_applied("presets_catalog_cleanup")
        logger.info(f"presets: archived {archived}; gheras-default refreshed")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"presets catalog cleanup skipped: {e}")
    # M3: the child sheet template takes the parent's art style preset
    # ($style_text / $sheet_rules) instead of the house style baked into its text.
    # An admin-rewritten template (without the baked text) is left alone.
    try:
        if await _already_applied("character_sheet_style_vars"):
            raise _SkipMigration
        import uuid as _uuid
        from services.house_style import SHEET_RULES, STYLE
        doc = await db.prompt_templates.find_one({"stage_key": "child_character_i2i", "active": True}, {"_id": 0})
        text = (doc or {}).get("template_text") or ""
        if STYLE in text and SHEET_RULES in text:
            now = datetime.now(timezone.utc).isoformat()
            await db.prompt_templates.update_one(
                {"id": doc["id"]},
                {"$set": {"active": False, "deactivated_at": now, "deactivated_reason": "character_sheet_style_vars"}},
            )
            await db.prompt_templates.insert_one({
                **{k: doc[k] for k in ("stage_key", "name", "notes") if k in doc},
                "id": str(_uuid.uuid4()),
                "variables": [*(doc.get("variables") or []), "style_text", "sheet_rules"],
                "template_text": text.replace(STYLE, "$style_text").replace(SHEET_RULES, "$sheet_rules"),
                "version": await db.prompt_templates.count_documents({"stage_key": "child_character_i2i"}) + 1,
                "active": True,
                "created_at": now,
                "updated_at": now,
            })
            logger.info("prompt_templates: child_character_i2i → art style preset variables")
        await _mark_applied("character_sheet_style_vars")
    except _SkipMigration:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning(f"character sheet style-vars migration skipped: {e}")
    try:
        init_storage()
    except Exception as e:
        logger.warning(f"Storage init deferred: {e}")
    logger.info("Gheras v2 backend ready")


@app.on_event("shutdown")
async def on_shutdown():
    client.close()
