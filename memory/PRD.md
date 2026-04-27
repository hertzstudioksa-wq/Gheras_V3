# Gheras (غِراس) — PRD

## Problem Statement
Arabic-first (RTL) AI storytelling platform for children. Multi-step Story Builder → Claude Sonnet 4.5 generates 3 scenarios → parent selects one → **Production Planning Engine** (Phase 5) produces a complete blueprint (scenes, narration, image/animation prompts, book pages, character profiles) → parent approves → (future Phase 6: actual image/video/PDF production).

## Architecture
- **Backend**: FastAPI + MongoDB (Motor). Auth: JWT. LLM: Claude Sonnet 4.5 via `emergentintegrations`.
- **Frontend**: React + Tailwind + Shadcn UI. RTL Arabic.
- **Storage**: Emergent Object Storage for image uploads.

## Implemented Phases
### Phase 1-3 (earlier)
- JWT auth, admin seed, drafts auto-save, 6-step Story Builder, Claude scenarios + fallback, scenario selection + admin panel.

### Phase 4 (Apr 20, 2026)
- Scenario batches (archive, not delete).
- Video Duration slider (30..180s → scene_target + cost_tier).
- `why_this_fits` per scenario.
- 3-regen user cap + admin bypass.
- Admin batches accordion.

### Phase 5 — Production Planning Engine (Apr 21, 2026)
- Auto-triggered when an order reaches `ready_for_ai`.
- ONE mega-JSON Claude call produces: production_plan + scenes + book_pages + character_profiles.
- Deterministic fallback preserves UX if LLM fails.
- Arabic narration & book text; English prompts for image/animation.
- User sees summary + "موافق" button (consent before media generation).
- User regen = 1 attempt; admin regen = unlimited.
- Admin panel tab: **خطة الإنتاج** (view plan, view/edit scenes incl. narration + prompts, regenerate).

### Phase 6A.1 — Audio Background Preference (Apr 21, 2026)
- User-facing selector in Story Builder Step 5: "الخلفية الصوتية" with 3 options (`music` / `human_rhythm` / `none`). Default `music`.
- Stored in `order.data.audio_background.mode` + propagated to Claude prompt + `production_plans.audio_background` + visible in admin production tab + user summary.

### Phase 6B — Final Assembly & Delivery (Apr 21, 2026)
- **Trigger**: After `user_approve_production`, once asset pipeline reaches `assets_ready`, final assembly auto-fires → `assembling` → `delivered` | `media_failed`.
- **Tools**:
  - Video: **ffmpeg** (installed system-wide). Concatenates cover (2s) + N scene clips (duration from narration word count). 1280×720, H.264, silent audio track (placeholder).
  - PDF: **reportlab + arabic-reshaper + python-bidi**. A5 landscape, Arabic RTL, cover page + per-scene image+text pages + back page with main_message.
- **Assembly jobs**: `final_video_assembly`, `final_pdf_assembly` (same `generation_jobs` collection, retry 3×, backoff [1,3,7]s).
- **Audio background respected**: `music` / `human_rhythm` / `none` stored on `final_videos.audio_background_mode` + in `assembly_metadata`. Real music mixing deferred.
- **User page** `/orders/{id}/production-ready` handles `assembling` (progress card) + `delivered` (video player + PDF download + completion card).
- **Admin media tab**: "التسليم النهائي" section at top shows inline video player + PDF link + job statuses + "إعادة تجميع" button.
- **Sample output**: ~2MB 65s MP4 + ~10MB 9-page Arabic RTL PDF generated in < 20 seconds each for a 7-scene story.

## New Collections (Phase 6B)
- `final_videos`: id, order_id, production_plan_id, generation_job_id, video_url, thumbnail_url, duration_seconds, audio_background_mode, provider, source_type, assembly_metadata, created_at.
- `final_pdfs`: id, order_id, production_plan_id, generation_job_id, pdf_url, page_count, cover_image_url, provider, assembly_metadata, created_at.

## New Endpoints (Phase 6B)
### User
- `GET /api/orders/{id}/delivery` → status, progress, plan brief + `{video, pdf}` URLs (only for the owner).

### Admin
- `GET /api/admin/orders/{id}/delivery` → full video + PDF records + assembly jobs.
- `POST /api/admin/orders/{id}/delivery/regenerate` → re-run final assembly from existing assets.
- `POST /api/admin/jobs/{id}/retry` now routes assembly jobs to `retry_single_assembly_job`.

### Phase 5.1 — User-Facing Approval Page (Apr 21, 2026)
- New route: `/orders/{id}/production-ready` (`ProductionReady.jsx`).
- Arabic RTL, mobile-first, sticky bottom action bar on mobile.
- States: loading, `production_planning` skeleton, `production_ready` (summary+actions), `production_approved` (success), `assets_generating` (progress bar), `assets_ready` (success), `media_failed`, `failed`.
- Shows: title, story_summary, main_message, duration, scene_count, image_count, safety_check + live progress percent when media generating.
- Hides: all prompts, scenes, IDs, admin-only details.
- Actions: "موافق على الخطة" (with loader) + "إعادة إعداد الخطة" (1 attempt + confirm dialog).

### Phase 6A — Media Generation Pipeline (Apr 21, 2026)
- **Trigger**: `user_approve_production` fires `trigger_asset_generation` → `run_asset_generation(order_id, run_id)` in background.
- **Jobs** (per order): 1 cover_image + N scene_images + N narration_audio + N book_page_asset → total 3N+1.
- **Providers**:
  - Images: Nano Banana (`gemini-3.1-flash-image-preview`) via emergentintegrations — saves base64 PNG → Emergent Object Storage → `/api/uploads/file/{id}`. Fallback = 1×1 PNG placeholder.
  - Audio: **MOCKED** in Phase 6A (`provider=mock`). Duration estimated from word count (2.2 WPS for Arabic). Real TTS (ElevenLabs/OpenAI) requires external key.
  - Book assets: reuse scene_image by scene_index (`provider=reused`).
- **Orchestration**: sequential, cover → scenes → narration → book. `max_attempts=3` per job with backoff [1,3,7]s.
- **Statuses**: `production_approved` → `assets_generating` → (`assets_ready` | `media_failed`). All transitions recorded in `status_history`.
- **Admin tab** "الوسائط": counts, cover preview, scene grid, narration list with per-scene `<audio>` (mock shows note), book page list, full jobs log with per-row retry, "إعادة توليد كامل" button.
- **User view**: minimal progress card + progress bar + "الخطوة التالية" messaging. No technical details.

## New Collections (Phase 6A)
- `generation_jobs`: id, order_id, run_id, job_type, target_id, meta, status, provider, attempt_count, max_attempts, error_message, output_url, output_metadata, created_at, updated_at.
- `scene_images`: id, order_id, production_plan_id, scene_plan_id (null for cover), generation_job_id, kind (cover/scene), scene_index, image_url, prompt_used, provider, source_type, created_at.
- `narration_assets`: id, order_id, production_plan_id, scene_plan_id, generation_job_id, scene_index, text, voice_type, language, audio_url (null in mock), duration_seconds, provider, created_at.
- `book_assets`: id, order_id, production_plan_id, book_page_id, generation_job_id, page_number, scene_index, illustration_url, page_text, provider, created_at.

## New Endpoints (Phase 6A)
### User
- `GET /api/orders/{id}/media-status` → `{status, status_ar, progress_percent, summary}`.

### Admin
- `GET /api/admin/orders/{id}/media` → full job board + previews.
- `POST /api/admin/orders/{id}/media/regenerate` → nukes assets + starts fresh run.
- `POST /api/admin/jobs/{id}/retry` → retry a single failed job.

## Order Status Machine
```
draft → pending → (scenarios_generating ↔ scenarios_ready) → scenario_selected →
ready_for_ai → production_planning → production_ready → production_approved →
generating (Phase 6) → completed
```

## Key Schema — Phase 5 Additions

### orders (new fields)
- `production_plan_id`
- `production_plan_snapshot: {plan_id, run_id, source, target_scene_count, generated_at}`
- `production_generation: {run_id, source, error, completed_at}`
- `production_approved: bool`
- `production_approved_at`
- `production_regeneration_count`
- `max_user_production_regenerations` (=1)

### production_plans (new collection)
`id, order_id, run_id, source, is_archived, title, story_summary, main_message, emotional_arc, style_guide{palette,lighting,art_direction}, cover_prompt, safety_check, target_scene_count, estimated_image_count, total_word_count, duration_seconds, duration_label, tone, setting, language, ai_plan_snapshot_json, created_at`

### scene_plans (new collection)
`id, order_id, production_plan_id, run_id, scene_index, arc_beat, title, scene_goal, narration_text(ar), book_text(ar), emotional_tone, visual_description(en), characters_in_scene[{character_profile_id, role_in_scene}], key_objects[], background_setting, continuity_notes, image_prompt{prompt_text(en), style_reference, character_reference_note}, animation_prompt{start_frame_description, end_frame_description, motion_hint, camera_style}, word_count, is_archived, created_at, edited_at, edited_by_admin`

### book_pages (new collection)
`id, order_id, production_plan_id, run_id, page_number, scene_index, scene_reference, text(ar), illustration_prompt(en), is_archived, created_at, edited_at, edited_by_admin`

### character_profiles (new collection)
`id, order_id, production_plan_id, run_id, type, name, name_en, visual_description(en), clothing_style(en), key_features(en), reference_image_url, is_archived, created_at, edited_at, edited_by_admin`

## Key Endpoints — Phase 5

### User
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/orders/{id}/production-summary` | Title, summary, scene_count, duration + approval state |
| POST | `/api/orders/{id}/production/approve` | Sets production_approved=true, transitions to `production_approved` |
| POST | `/api/orders/{id}/production/regenerate` | 1 attempt; 429 Arabic error after |

### Admin
| Method | Path | Purpose |
|---|---|---|
| GET  | `/api/admin/orders/{id}/production` | Full plan + scenes + book_pages + character_profiles |
| POST | `/api/admin/orders/{id}/production/regenerate` | Unlimited, archives previous |
| PATCH | `/api/admin/scene-plans/{id}` | Edit narration_text / book_text / visual_description / image_prompt_text / animation.* |
| PATCH | `/api/admin/book-pages/{id}` | Edit text / illustration_prompt |
| PATCH | `/api/admin/character-profiles/{id}` | Edit visual_description / clothing_style / key_features |

## Arc Templates (per scene_target)
- 3 scenes → intro / problem / resolution
- 4 → intro / problem / turn / ending
- 5 → intro / problem / escalation / resolution / ending
- 6 → intro / problem / escalation / climax / resolution / ending
- 7 → setup / intro / problem / escalation / climax / resolution / ending
- 8 → setup / intro / problem / esc₁ / esc₂ / climax / resolution / ending
- 9 → setup / intro / problem / esc₁ / esc₂ / climax / resolution / reflection / ending

## Known Issues / Caveats
- Emergent Claude endpoint has been returning 502s intermittently during testing — fallback works reliably and produces a full valid plan every time.
- Admin bypass still bumps user regen counter (consistent with Phase 4 design).
- Plan regeneration archives all previous scenes/pages/characters (via `is_archived=true`), not deleted.
- Scenes/pages/characters are served filtered by `is_archived=false` in admin view.

### Stabilization pass — Feb 2026
- Root-caused 2 production bugs in the delivery pipeline:
  (1) `ffmpeg` was missing from the container (auto-reinstalled via `apt install ffmpeg`).
  (2) Amiri font file was an HTML error page (TTFError on PDF assembly). Replaced with
      `fonts-hosny-amiri` Debian package; valid TTF now lives at `/app/backend/fonts/`.
- Added `services/progress_service.py` — unified 0..100 progress across the whole pipeline.
- User-endpoint sanitization + race-condition guard + video/PDF assembly hardening.
- Phase A/B admin config layer (models + pipeline + prompts) with safe `string.Template` rendering.

### Phase C REAL — OpenAI gpt-image-1 I2I (Feb 22, 2026) ✅
- **Replaced MOCK with real provider**. `/app/backend/services/child_character_service.py`:
  - `_openai_generate()` → `AsyncOpenAI.images.edit(model="gpt-image-1", image=file, prompt=..., size="1024x1024", background="transparent")`
  - Source bytes fetched internally from `files` collection + object storage (no HTTP loopback, no auth juggling)
  - Generated PNG persisted via `storage.put_object` → new file record → `/api/uploads/file/{id}` URL
  - OPENAI_API_KEY read from env only; never logged, never exposed to frontend
  - MOCK fallback retained: activates when key missing, provider fails, or `fallback_allowed=True` and real call fails — pipeline never breaks
- `config_service.DEFAULT_MODELS["child_character_i2i"]` → `openai / gpt-image-1` (env_key=`OPENAI_API_KEY`)
- `PROVIDER_ENV_MAP["openai"]` → `OPENAI_API_KEY` (direct, no Emergent key); Admin API status page now reflects real configured state
- `seed.py::seed_prompt_templates()` seeds an editable default template for `child_character_i2i` on startup (active, v1) — admin can edit via `/admin/prompts`
- Admin UI: REAL (green) vs MOCK (amber) badges wired in both AdminOrders media card (`data-testid="child-character-mode-badge"`) and AdminStoryboard output block
- End-to-end tests (all ✅):
  - **A** disabled stage → clean skip, no DB write
  - **B** enabled + real provider → `mock=false, provider=openai, model_name=gpt-image-1, source_url ≠ generated_url`, 1024×1024 RGBA transparent PNG (~1.8 MB), ~50s latency
  - **C** missing `OPENAI_API_KEY` → `_openai_generate` returns `None`, service falls back safely
  - **D** provider failure (invalid model / bad bytes) → error swallowed, MOCK fallback used when `fallback_allowed=true`, pipeline continues
  - **E** admin visibility → REAL badge visible in Storyboard, prompt editor at `/admin/prompts` supports `child_character_i2i`, `prompt_source=admin` confirmed

### Phase D — Admin Storyboard / Pipeline Trace (Feb 22, 2026) — READ-ONLY debug view
- New endpoint: `GET /api/admin/orders/{id}/storyboard` aggregates 8 pipeline stages
  (scenario → production → child_character → scene_images → narration → book_assets →
  video_assembly → pdf_assembly) into a single response.
- Per stage: status, latency_ms_estimate (+`latency_is_estimate=true`), attempts, provider,
  model_name, model_source (admin|fallback|local|n/a), prompt_source, prompt_template_id/version,
  prompt_used, prompt_hash (sha256:<16>), fallback_used, error_message, mock_mode,
  input_summary, output_summary, events (from status_history + job errors), actions.
- Scene-level debug array per image (prompt_hash, provider, fallback_used, latency, attempts).
- Rules enforced: NO invented fields (`request_id` absent), NO new collections, NO business-
  logic changes. Disabled stages show `status="skipped"` (never hidden).
- New frontend page `/admin/orders/:orderId/storyboard` + "Storyboard" button in admin order
  modal (opens in new tab). Timeline bar at top with clickable nodes; expand/collapse per
  stage card with copy-prompt, download, and per-stage regenerate actions.
- Tests: 17/17 pytest cases green (`/app/backend/tests/test_storyboard.py`) + frontend smoke pass.

## Backlog (Phase 6 — NOT built yet)
- Fixed recurring "جاري تحميل حالة الطلب… هناك تعطّل مؤقت في الاتصال" flicker on page load.
- Root cause: a single transient 502/504/timeout during the INITIAL fetch immediately set
  `loadError` and hid the loading skeleton — even though the 3s polling would recover within
  seconds.
- Fix (frontend only, no business logic change):
  1. Added `consecutiveFailuresRef` counter (threshold = 3) — only surfaces the error card
     after 3 consecutive failures during initial load.
  2. Added quick backoff retries at 1s and 3s on mount (on top of the 3s polling loop) so the
     first hiccup is always re-attempted before any error UI appears.
  3. 401 is treated as permanent ONLY when a response body exists (transient 401s from
     gateway/timeout now fall through to the retry path, matching the api.js interceptor).
  4. Kept `loading=true` between transient failures so the pretty skeleton stays visible.
- Verified via Playwright route-interception: 2 injected 502s → UI stays on skeleton, 3rd call
  succeeds and renders content with zero flash of error text. 5 consecutive 502s → error card
  appears only after the 3rd failure. 404 permanent error card appears immediately.

### Phase D.5 — Story Depth & scene_target buckets (Feb 2026) ✅
- **Duration → scene_target** is now bucket-based and **dynamic within a range**:
  - 30–45s   → bucket **"short"**,  range **[3, 4]** scenes (picks 3 for 30s, 4 for 45s)
  - 60–90s   → bucket **"medium"**, range **[5, 6]** scenes (picks 5 for 60s, 6 for 90s)
  - 120–180s → bucket **"long"**,   range **[7, 9]** scenes (picks 7/8/9 for 120/150/180s)
- `models.duration_meta()` now emits `scene_target_min`, `scene_target_max`, `scene_target_bucket`
  alongside the existing `scene_target`/`label`/`cost_tier`. Persisted on new orders only.
- `models.duration_scene_range()` safely returns `None` for legacy orders persisted before D.5,
  so their exact-match validation is preserved (no DB migration, no regression).
- `services/scenario_service._clamp_scene_count` now honours the bucket range when provided;
  legacy callers fall through to the old `target ± 1` clamp.
- `services/production_service._generate_via_claude` enforces the range:
  `min ≤ len(scenes) ≤ max` for new orders, exact-match for legacy orders.
- **Final-scene quality guard** (`_enforce_final_scene_quality`) added in `build_docs`:
  ensures last scene `narration_text ≥ 12` words and `book_text ≥ 8` words.
- Tests: 14/14 unit tests green; E2E verified via REAL AI path (45s→4, 60s→5, 150s→8 scenes).

### Wave 1 — Product Ops (Feb 2026) ✅
**Scenario History (return to previous ideas)**
- New endpoint: `GET /api/orders/{id}/scenarios/batches` lists ALL batches with sanitized scenarios.
- `POST /api/orders/{id}/scenarios/{sid}/select` now allows selecting from a previous batch
  (was rejected before). Selecting from an old batch promotes it to current so downstream
  pipeline (filtered on `current_scenario_batch_id`) keeps working unchanged.
- Frontend `ScenarioSelection.jsx`: collapsible "أفكار سابقة" section appears whenever the
  user has ≥2 batches. Per-batch expander shows all 3 scenarios with a one-click select.
- Verified E2E on a real 6-batch order: select from oldest batch → `promoted_batch=true`,
  `current_batch_id` flipped, `selected_scenario_id` set correctly.

**Output Type Selection (video / pdf / both)**
- New `data.delivery.output_type` (one of `video`, `pdf`, `both`; default `both` for backward
  compat). Persisted on new orders, ignored on legacy orders.
- `models.get_order_output_type()` helper handles legacy + invalid + missing values.
- **Pipeline gating**:
  - `services/generation_orchestrator._plan_jobs`: `pdf`-only skips `narration_audio`;
    `video`-only skips `book_page_asset`; `both` runs full pipeline (legacy default).
  - Mandatory job set is computed dynamically per output_type.
  - `services/final_delivery_service.run_final_assembly`: only enqueues the assembly jobs
    needed for the requested deliverable; "delivered" status is granted when every
    requested deliverable assembled.
  - `retry_single_assembly_job` re-evaluates DELIVERED status using the same gating.
- Frontend `StoryBuilder.jsx`: new `OutputTypePicker` in Step 5 with 3 options, plus a
  Review-step field showing the chosen deliverable.
- `routes/admin_routes.admin_list_scenarios`: returns `output_type`. AdminOrders modal renders
  a badge ("نوع التسليم: فيديو + كتاب / فيديو / كتاب PDF").
- `routes/admin_storyboard_routes` injects `output_type` and `scene_target_bucket` into both
  `scenario_generation` and `production_planning` `input_summary`.
- Tests: 9/9 new unit tests green (`/app/backend/tests/test_wave1_output_type.py`).
- Backward compat: existing 6-batch order showed `output_type=both` automatically; new
  pdf-only order persisted `delivery.output_type=pdf`; admin endpoints expose both correctly.

**Prompt Inventory Audit**
- All 7 admin-editable stages already exist: `child_character_i2i`, `scenario_generation`,
  `production_planning`, `scene_image_generation`, `narration_generation`,
  `video_generation`, `music_generation` — seeded by `seed_prompt_templates()`.
- `extra_character_i2i` deliberately reuses the `child_character_i2i` template
  (no separate seed needed; verified in `services/extra_characters_service:128`).
- No new prompt seeds required for Wave 1.

### Wave 2 — Product Ops II (Feb 2026) ✅
**Pricing snapshot + internal cost visibility**
- New collection `pricing_config` (single doc id="default"). Built-in defaults
  override missing fields gracefully; admin edits are deep-merged.
- New collection `order_pricing` with two snapshot kinds per order: `estimate`
  + `actual`. Mirrored as compact `pricing_estimate` / `pricing_actual` on the
  `orders` doc for fast reads.
- Service: `services/pricing_service.py` — `estimate_cost()` derives from
  production_plan + delivery + characters; `actual_cost()` derives from
  `generation_jobs` aggregated by `job_type` with retry-attempt cost fraction.
- Hooks (best-effort, never block pipeline):
  * `production_routes.run_production_generation` → `snapshot_estimate`.
  * `final_delivery_service.run_final_assembly` (DELIVERED branch) →
    `snapshot_actual`.
- Admin endpoints: `GET/PUT /api/admin/pricing/config`,
  `GET /api/admin/orders/{id}/pricing`,
  `POST /api/admin/orders/{id}/pricing/snapshot?kind=estimate|actual`.
- Default config: SAR currency, 35% markup, SAR 49 minimum, 11 stage costs,
  `pdf` modifier 0.65 vs `both`/`video` 1.0, `high` tier modifier 1.15.
- Pricing math: `sell = max(min_price, cost * (1+markup%))` with rounding
  step. `pdf`-only orders are ~35% cheaper internally.

**Stage Testing Lab**
- New collection `stage_test_runs`. Service: `services/stage_lab_service.py`.
- Admin endpoints under `/api/admin/lab`: `GET /stages`, `POST /run`,
  `GET /runs[/{id}]`.
- Real-call stages: `scenario_generation`, `production_planning`,
  `child_character_i2i` — gated behind explicit `acknowledged_cost: true`
  flag (the API rejects with 400 in Arabic if missing).
- Preview-only stages: `scene_image_generation`, `narration_generation`,
  `video_generation`, `music_generation` — render the live admin prompt and
  return provider/model metadata WITHOUT calling the provider.
- Records: stage_key, provider, model_name, model_source, transport,
  env_key, prompt_source, prompt_hash, prompt_preview, latency_ms,
  estimated_cost, fallback_used, status, error_message, output_preview.

**Secret Management (read-only + masked)**
- New routes: `GET /api/admin/secrets/status` (READ-ONLY by design — there is
  NO POST/PUT/PATCH).
- Reports per known env key: `configured` (bool), `masked` (`***ABCD`),
  `purpose`, full `rotation_instructions` in Arabic, `system` flag for
  non-rotatable keys (e.g. `MONGO_URL`).
- Curated keys: `OPENAI_API_KEY`, `EMERGENT_LLM_KEY`, `MONGO_URL`.
- No plaintext storage in DB. No `.env` editing from admin. Direct admin
  contract: rotate at the deployment layer, then verify status here.

**Frontend**
- New admin pages: `AdminPricing.jsx`, `AdminStageLab.jsx`, `AdminSecrets.jsx`.
- Admin order modal: new `pricing` tab with both snapshots + fresh recompute
  + manual snapshot triggers.
- Admin nav: 3 new entries (Lab / Pricing / Secrets) with proper icons.
- Tests: 9 new + 25 existing = **34/34 unit tests pass**.

### Wave 3 — Bundles + Audit Trail + Payment-Ready (Feb 2026) ✅
**Bundles / Packages**
- Collections: `bundles` (admin SKUs) + `bundle_purchases` (per-user inventory
  with embedded reservations array).
- 3 default seeded bundles (idempotent on virgin install): "5 فيديوهات" 199 SAR,
  "10 كتب PDF" 249 SAR, "حزمة كاملة 5+5" 449 SAR.
- Lifecycle states (per reservation): `reserved` → `consumed` | `refunded` | `expired`.
- Idempotent reserve/consume/refund — race-safe via Mongo `$inc` + array filter
  guards, and explicit "already-or-never" no-op response.
- Pipeline hooks (best-effort, never block):
  * `production_routes.trigger_production_planning` → `reserve_for_order` at
    start of production (matches user spec: consume at start, refund on failure).
  * `final_delivery_service.run_final_assembly` (DELIVERED) → `consume_for_order`.
  * `final_delivery_service.run_final_assembly` (MEDIA_FAILED) → `refund_for_order`.
- Admin endpoints: `GET/POST/PUT/DELETE /api/admin/bundles`,
  `POST /api/admin/bundles/{id}/grant`, `GET /api/admin/bundles/users/{id}/purchases`.
- User endpoints: `GET /api/bundles` (active SKUs), `GET /api/bundles/me`
  (own inventory with computed `quantity_remaining` + `status`).
- Frontend: `AdminBundles.jsx` (CRUD + grant modal) + `MyBundles.jsx` (customer
  inventory + buy button → checkout or 503 if Stripe not configured).
- `pricing_service` now emits `payment_source ∈ {bundle, paid, pending}` on every
  estimate/actual snapshot — bundle wins over payment when both present.

**Audit Trail**
- Collection: `audit_log`. Service: `services/audit_service.py`.
- Endpoint: `GET /api/admin/audit/log?entity_type=&actor_id=&action=&limit=`.
- Tracked entity_types: `pricing_config`, `model_registry`, `pipeline_config`,
  `prompt_template`, `bundle`, `bundle_purchase`, `payment_settings`, `payment`.
- Tracked actions: `create`, `update`, `delete`, `grant`, `reserve`, `consume`,
  `refund`, `expire`, `config_change`, `secret_rotation_attempt`.
- Snapshots: `before` + `after` are auto-trimmed (drop `_id`, truncate strings
  > 400 chars) so audit rows stay compact.
- Hooks: pricing config update + bundle CRUD + bundle reservation lifecycle +
  payment settings update + payment creation/finalization.
- Frontend: `AdminAuditLog.jsx` with entity/action filters and per-row diff
  expansion (before/after side-by-side).

**Payment Architecture (Stripe — architecture-ready, sk_test_emergent active)**
- Used `integration_playbook_expert_v2`. SDK used:
  `emergentintegrations.payments.stripe.checkout.StripeCheckout`.
- `STRIPE_API_KEY=sk_test_emergent` added to `backend/.env` for testing; LIVE key
  swap is the only step remaining for production.
- Collections: `payment_settings` (single doc, NON-secret values only) +
  `payments` (full transaction log).
- Service: `services/payment_service.py`. Endpoints:
  * Admin: `GET/PUT /api/admin/payment/settings`, `GET /admin/payment/status`,
    `GET /admin/payment/payments`.
  * User: `POST /api/checkout/bundle/{id}` (returns Stripe session URL),
    `GET /api/checkout/status/{session_id}` (polling — security-required).
  * Webhook: `POST /api/webhook/stripe`.
- 503 graceful guard — every payment endpoint returns
  `503 الدفع غير مفعّل بعد` when `STRIPE_API_KEY` is missing.
- Apple Pay handled correctly: appears as a CHECKOUT METHOD inside Stripe's
  Payment Element on Apple devices when `card` is in `payment_methods`. NOT
  a payout destination — `payout_destination_label` is informational text
  describing the merchant bank. Verified by playbook + a unit test.
- Idempotency: `_finalize_paid_payment` checks `bundle_purchase_id` before
  granting, preventing double-credit on parallel webhook + status-poll.
- Backend NEVER accepts amounts from frontend — bundle prices read from DB.
- E2E verified: real Stripe test session created via `sk_test_emergent`
  (returned `cs_test_a1ViGt4hUEeN...` URL).

**Tests**
- 13 new unit cases (`test_wave3_bundles_audit_payment.py`).
- **47/47 unit tests pass** (47 = 14 D.5 + 9 W1 + 12 W2 + 13 W3 — total).

### Wave 4 — Asset Library + Retention (Feb 2026) ✅
**Asset Library**
- Service `services/asset_service.py` aggregates `final_videos` + `final_pdfs`
  with per-asset metadata (age_days, order_status, user_email, has_active_bundle).
- Endpoints (admin only):
  * `GET /api/admin/assets` — filters: `asset_type`, `lifecycle_status`,
    `order_status`, `user_id`, `min_age_days`, `max_age_days`, `limit`.
  * `POST /api/admin/assets/{type}/{id}/archive[?force=true]`
  * `POST /api/admin/assets/{type}/{id}/restore`
  * `POST /api/admin/assets/{type}/{id}/purge[?force=true]`
- New field `lifecycle_status` on `final_videos` & `final_pdfs` (defaults
  to `live` for legacy assets via projection logic — no migration needed).

**Lifecycle (`live` → `archived` → `purged`)**
- `archive` — sets `lifecycle_status="archived"` + records `archived_at/by`.
  Reversible via `restore`.
- `restore` — flips back to `live`. NEVER works on `purged` assets.
- `purge` — sets `lifecycle_status="purged"`, clears `*_url` fields (app stops
  handing out URLs), preserves `*_url_pre_purge` for forensic audit only.
  Storage caveat documented honestly: Emergent Object Storage exposes no
  public delete API, so files may persist remotely; the application treats
  them as gone.
- All actions audited with full before/after.

**Retention Policy**
- Collection `retention_policy` (single doc, admin-tunable):
  * `protect_recent_delivered_days: 30` (HARD guard — never archive/purge
    within this window after DELIVERED).
  * `protect_active_bundle_orders: true` (skip orders with reserved bundle).
  * `min_age_for_archive_days: 30` (manual archive guard).
  * `min_archived_days_before_purge: 30` (manual purge guard).
  * `auto_archive_after_delivered_days: 30` (enforce rule).
  * `auto_purge_after_archived_days: 60` (enforce rule).
- Endpoints: `GET/PUT /admin/retention/config`, `GET /admin/retention/preview`,
  `POST /admin/retention/enforce`.
- **Preview** returns `to_archive`, `to_purge`, `skipped` lists with
  `matched_rule` / `reason` per row — admin can inspect EXACTLY what would
  happen before clicking enforce.
- **Enforce** writes a `retention_runs` summary doc (archived_count,
  purged_count, failed_count + per-failure reasons).
- All guards bypassable per-asset only via explicit `force=true` (audited
  with `forced: true` in metadata).

**Frontend**
- `AdminAssetLibrary.jsx` — filter bar + table + per-row archive/restore/
  purge actions with confirmation + `needs_force` re-prompt.
- `AdminRetention.jsx` — 6 config fields + preview button + enforce button
  + side-by-side preview/skipped sections.
- Storage transparency note rendered in admin UI.

**Tests**
- 7 new unit cases (`test_wave4_assets_retention.py`).
- **54/54 unit tests pass** (14 D.5 + 9 W1 + 12 W2 + 13 W3 + 7 W4).

### Phase E — Scene Reference Injection (Feb 2026) ✅
**What was built**
- New service `services/scene_reference_service.py` resolves which existing reference
  images (child portrait, extra-character portraits, toy/object) belong in EACH scene
  based on `scene_plans.characters_in_scene[].role_in_scene` (matched against
  `extra_character_assets.character_type`) and `scene_plans.key_objects` (matched
  against `personalization.toy_image_url` + favorites.toy.name).
- Hard caps per scene: child=1, extras≤2, toy=1 (max 4 reference images per call).
- Granular `skipped_reasons` codes: `scene_not_relevant`, `missing_asset`,
  `too_many_references_trimmed`, `reference_fetch_failed` (orchestrator),
  `provider_no_reference_support` (image service).

**Multi-provider safe path** — `services/image_generation_service.generate_image()`
now accepts `references=list[dict{image_bytes,mime_type,kind,name}]`,
`support_true_refs=True`, and `prompt_augmentation=str`:
  1. With references → Nano Banana call with `ImageContent(image_base64=...)` list.
  2. On failure → retry text-only; record `fallback_path="text-only"` + reason.
  3. `support_true_refs=False` → text-only from start (`provider-no-image-input`).
  4. Total failure → 1×1 PNG placeholder (`placeholder`).

**Orchestrator wiring** — `_execute_scene_image()`:
  * Resolves refs per scene, fetches bytes via `_fetch_source_bytes()`.
  * Writes `scene_reference_log` per scene_plans (available, child_reference_used,
    extra_character_reference_ids_used, extra_character_reference_indexes_used,
    toy_reference_used, references_injected_count, references_attempted,
    references_used, fallback_path, fallback_reason, skipped_reasons,
    final_effective_image_prompt).
  * Mirrors `references_used / references_count / reference_fallback_path` on `scene_images`.

**Pricing (actual_cost only)** — new stage `scene_reference_injection` (0.05 SAR/ref).
Counted ONLY when `scene_plans.scene_reference_log.references_used==true` AND
`references_injected_count>0`. Estimate snapshot intentionally excludes it.

**Admin Storyboard** — `_stage_scene_image_generation`:
  * Aggregates: `references_total_injected`, `references_used_scene_count`,
    `references_skipped_total`.
  * Per-scene `references` object surfaced for the UI.
  * `AdminStoryboard.jsx` `OutSceneImages` shows `refs×N` badge + collapsible
    panel with skipped reasons table.

**Admin Stage Lab — Reference Dry-Run**:
  * `scene_image_generation` preview accepts `order_id` + `scene_index` and
    returns `output_preview.reference_dry_run` (no provider call).
  * `AdminStageLab.jsx` shows a contextual inputs block for that stage.

**Backward compatibility verified**:
  * Legacy delivered orders (no scene_reference_log) → references default to
    false/0/empty/null. Storyboard returns 200 (verified 14-scene order 4c357bfc).
  * `pricing_actual.items` excludes `scene_reference_injection` for legacy orders.
  * Old `generate_image(scene_prompt, style_guide, character_note, session_hint)`
    signature preserved; new params are keyword-only with safe defaults.

**Tests** — 12 unit tests + 13 live-API tests = 25 new green for Phase E.
**87/88 total** (1 unrelated pre-existing async-pytest config fail).

### Phase F — Effective Prompt Preview (Feb 2026) ✅
**Goal**: admin productivity / debug tool — preview the FINAL effective
prompt for any of the 7 admin-controlled stages WITHOUT calling the
provider, WITHOUT consuming API credit, WITHOUT requiring `acknowledged_cost`.

**Backend**
- New service function `services/stage_lab_service.build_effective_prompt_preview(stage_key, input_payload)`.
  Loads the active admin template, builds the FULL variable context (real
  order data when `order_id`+`scene_index` provided, synthetic otherwise),
  renders via `string.Template.safe_substitute`, and returns:
  * `stage_key, provider, model_name, model_source, transport, env_key`
  * `prompt_source` (admin/default), `template_id`, `template_version`,
    `template_text_preview`, `render_note`, `fallback_would_happen`
  * `effective_prompt` (final string, with `${var}` left in place when missing)
  * `prompt_hash` (sha256:<16>)
  * `unresolved_placeholders` (list of `${var}` left unrendered)
  * `warnings` (Arabic, e.g. "القالب موجود لكنه لم يُستخدم: required_missing:child")
  * `context_source` (real_order / synthetic), `context_used`
  * `scene_image_extras` (for scene_image_generation: full reference dry-run)
  * `estimated_cost`, `currency`
- Two endpoint surfaces:
  * `POST /api/admin/lab/preview` — returns the preview directly, no DB write.
  * `POST /api/admin/lab/run` with `preview_only=true` — same payload but also
    persists a `stage_test_runs` row for the history. Bypasses the
    `acknowledged_cost` gate even for REAL_CALL_STAGES.
- Backwards-compatible: existing `/run` calls without `preview_only` still
  enforce `acknowledged_cost` for `scenario_generation`, `production_planning`,
  and `child_character_i2i` exactly as before.

**Frontend** — `pages/admin/AdminStageLab.jsx`
- New "معاينة Prompt الفعّال" button next to "تشغيل المرحلة" (admin chooses).
- Dedicated preview result panel surfaces every debug field + warnings +
  unresolved placeholder pills + copy-prompt button + collapsible
  "Scene References (dry-run)" + "السياق المُستخدَم في الـ render".
- Existing "تشغيل المرحلة" path unchanged.

**Stages supported (7)**
  scenario_generation, production_planning, scene_image_generation,
  child_character_i2i, narration_generation, video_generation, music_generation.

**Tests**
  * 10 new unit tests (`tests/test_phase_f_prompt_preview.py`):
    placeholder detector / required stages / debug fields shape /
    fallback when no admin template / template-present-but-unused /
    unsupported stage / estimated_cost.
  * 5 live API tests (curl) verified end-to-end on preview environment:
    TEST 1 scenario_generation OK · TEST 2 production_planning fallback
    surfaces correct `required_missing:child` warning · TEST 3
    scene_image_generation with real order shows scene_image_extras +
    references resolved · TEST 4 (broken/missing template) renders raw
    `${var}` and surfaces unresolved_placeholders + warnings · TEST 5
    REAL_CALL stage (`child_character_i2i`) preview returns in 120ms
    without `acknowledged_cost`, regression intact (without `preview_only`
    still 400s without ack).

**97/98 total** (10 new Phase F + 25 Phase E + 54 Wave 1-4 + 8 D.5/D.3 — 1
unrelated pre-existing async-pytest config fail).

### Phase G — Lab Control Gaps Closure (Feb 2026) ✅
**Stages added** (4 new): `extra_character_i2i`, `book_page_image_generation`,
`video_assembly`, `pdf_assembly`. Total `SUPPORTED_STAGES` = **11**.

**`executor_status` taxonomy** (5 categories):
  * `real-call` (4) — scenario_generation, production_planning,
    child_character_i2i, extra_character_i2i. Burns API.
  * `preview-only` (1) — scene_image_generation. Real exec but lab can't
    drive without real order context.
  * `not-yet-wired` (3) — narration_generation, video_generation,
    music_generation. Templates editable; provider exec lands later.
  * `local-binary` (2) — video_assembly (ffmpeg), pdf_assembly (reportlab).
    No LLM, no API cost; templates are informational settings docs.
  * `reuse-from-other-stage` (1) — book_page_image_generation. Today reuses
    scene_image; template ready when admin wants distinct illustrations.

**Prompt inventory** — 4 new seed templates with REAL editable defaults:
  * `extra_character_i2i` — character-aware prompt (live extra service still
    reuses child template; admin can override here).
  * `book_page_image_generation` — A5 RTL print-friendly illustration prompt.
  * `video_assembly` — informational ffmpeg settings + audio_background_mode.
  * `pdf_assembly` — informational reportlab + Amiri font settings.

**Audio choice propagation** — `narration_generation` and `music_generation`
templates **bumped to v2** (old v1 deactivated, archived for audit). Both now:
  * Read `$audio_background_mode` from order context.
  * Branch behavior per mode in the prompt itself: `music` keeps storytelling
    rhythm, `human_rhythm` shortens pauses + clap-only beats, `none` slower
    pacing + empty composition.
  * Verified: each of the 3 modes produces a DIFFERENT prompt_hash.

**`/api/admin/lab/stages` enriched** — every stage now exposes:
  `name_ar, name_en, real_call, executor_status, prompt_driven (bool),
   estimated_cost, currency, notes_ar`.

**Frontend** — `pages/admin/AdminStageLab.jsx`:
  * Selector now lists all 11 stages with `• executor_status` suffix.
  * Status badge (color-coded per category) + `prompt-driven` pill +
    Arabic explanation panel under the selector explaining WHY a stage
    is preview-only / local-binary / not-yet-wired.

**Tests**
  * 9 new unit tests (`tests/test_phase_g_lab_gaps.py`):
    new stages added / executor_status coverage / executor_status values valid /
    extra_character_i2i is real-call / video_assembly+pdf_assembly local-binary /
    book_page_image_generation reuse / not-yet-wired set / Arabic notes presence.
  * 5 live API tests via curl:
    TEST 1 stages catalogue (11 stages, all classified) ✅
    TEST 2 4 new templates have prompt_source=admin, version=1, 0 unresolved ✅
    TEST 3 5 distinct executor_status buckets correctly populated ✅
    TEST 4 audio_background_mode produces distinct hashes for music/human_rhythm/none in BOTH narration + music ✅
    TEST 5 Phase F regression: all 7 original stages still respond unchanged ✅

**Files modified**
  * `services/stage_lab_service.py` (+ EXECUTOR_STATUS, STAGE_NOTES_AR,
    extended SUPPORTED_STAGES + REAL_CALL_STAGES; richer
    `_build_stage_context` for new stages).
  * `routes/admin_lab_routes.py` (`/stages` returns full classification).
  * `services/config_service.py` (added 4 new STAGE_DISPLAY_NAMES).
  * `seed.py` (4 new prompt template seeds + narration/music templates
    documented as audio-aware in `notes`).
  * `pages/admin/AdminStageLab.jsx` (status badges + notes panel).
  * `tests/test_phase_g_lab_gaps.py` (NEW, 9 tests).
  * Live DB migration: narration_generation v1 deactivated → v2 active +
    music_generation v1 deactivated → v2 active.

**106/107 total** (9 G + 10 F + 25 E + 54 W1-4 + 8 D.5/D.3 — 1 pre-existing
async-pytest config fail).

### Phase H — Operations Readiness + Preset Stacks (Feb 2026) ✅

**Part 1 — Encrypted Secret Overrides (`secret_overrides_service.py`)**
- New `secret_overrides` MongoDB collection. Encryption uses **Fernet** with key
  derived from `SECRETS_ENCRYPTION_KEY` env (recommended) or fallback derived
  from `MONGO_URL` (always present in this pod). `encryption_available()`
  surfaces availability to the UI.
- Resolution precedence: **secure_override → process .env → None**.
- At backend startup, `apply_overrides_to_env()` decrypts every override and
  injects it into `os.environ` so legacy `os.environ.get(...)` paths transparently
  pick up the latest value without code changes.
- API:
  * `GET /api/admin/secrets/status` — per-key `source` (`override|env|missing`),
    `masked` (`***ABCD`), `override_present`, `override_updated_at`, `optional`,
    `test_provider_key`, `encryption_available`.
  * `PUT /api/admin/secrets/{env_key}` — accepts `{value}`, encrypts, returns
    only `{rotated, masked}`. **Raw value never echoed.**
  * `DELETE /api/admin/secrets/{env_key}` — falls back to .env.
- Audit on every set/delete (action `secret_override.set` / `secret_override.delete`).

**Part 2 — Provider Connectivity (`provider_test_service.py`)**
- 4 providers supported: `openai`, `emergent` (Gemini/Claude path),
  `elevenlabs`, `stripe`. Each tester returns
  `{ok, auth_ok, reachable, model_reachable, latency_ms, secret_source,
   secret_masked, error}` — never the raw secret.
- API:
  * `POST /api/admin/secrets/test/{provider}` — single test (audited).
  * `POST /api/admin/secrets/test-all` — parallel test of all 4.
- Live verified: OpenAI 572ms ✓, Emergent path ✓, ElevenLabs `missing` ✗ (correctly),
  Stripe present-but-key-format-invalid ✗ (correctly).

**Preset Stacks (`preset_stacks_service.py`, `admin_preset_stacks_routes.py`)**
- New `preset_stacks` collection. Schema: `id, name, slug, description,
  intended_use, is_seeded, is_active, is_archived, stage_map,
  created_at/by, updated_at/by, applied_at/by`.
- `_validate_stage_map` rejects any field that smells like a raw secret
  (`api_key`, `secret`, `value`, `raw`) → presets can ONLY reference `env_key`
  names that the secret system already manages.
- 5 seeded presets: **OpenAI Full Stack**, **Gemini Visual Stack**,
  **Low-Cost Stack**, **High-Fidelity Stack**, **Safe Production Stack**.
- API:
  * `GET /api/admin/presets` — list
  * `GET /api/admin/presets/active` — currently applied preset
  * `GET /api/admin/presets/{id}` — single
  * `POST /api/admin/presets` — create
  * `PUT /api/admin/presets/{id}` — update
  * `POST /api/admin/presets/{id}/clone` — clone
  * `DELETE /api/admin/presets/{id}` — delete (or archive if seeded)
  * `POST /api/admin/presets/{id}/dry-run` — diff before apply, with
    `executor_status`, `secret_status` per stage + Arabic warnings + summary
    of `missing_secrets` and `non_executable_stages`.
  * `POST /api/admin/presets/{id}/apply` — writes preset's stage_map into
    `model_registry`, sets `applied_by_preset_id/name`, marks preset
    `is_active=True` and deactivates others.
- Audit on every preset action (`preset.create/update/delete/apply`).

**Lab integration**
- `GET /api/admin/lab/stages` now returns `active_preset` plus per-stage
  `applied_by_preset_id`, `applied_by_preset_name`, `config_source`
  (`preset` | `manual_or_default`). Admin instantly sees provenance.

**Frontend**
- `pages/admin/AdminSecrets.jsx` rebuilt: shows `source` badge per secret +
  password input for safe override + "حفظ آمن" + "حذف override" + per-key
  "اختبار اتصال" button + live test result panel.
- `pages/admin/AdminPresets.jsx` (NEW): 2-col grid of all presets with
  active banner, preview (dry-run) + apply + clone + archive, full diff
  panel underneath with executor_status/secret_status badges and Arabic
  warnings per stage. Wired into `/admin/presets` route + sidebar.

**Tests** — 12 new unit tests (`tests/test_phase_h_secrets_presets.py`):
encryption availability + round-trip + masking, slug helpers, stage_map
validation rejects raw secrets, seeded preset shape, executor warnings.
All 7 live API tests pass:
  TEST 1 secure override: raw never echoed in PUT response or /status; DELETE
  reverts to env. ✅
  TEST 2 provider connectivity: OpenAI 572ms ✓, all 4 return safe payloads. ✅
  TEST 3 5 seeded presets exist with stage_map. ✅
  TEST 4 dry-run gemini-visual: 5 changed + 1 unchanged + non_executable
  warnings + secret_status per stage. ✅
  TEST 5 apply safe-production: 4 stages updated in model_registry,
  applied_by_preset_name set, is_active flipped. ✅
  TEST 6 lab/stages exposes active_preset banner + per-stage `config_source`. ✅
  TEST 7 regression: 31/31 unit tests + Effective Prompt Preview for all 11
  stages still works unchanged. ✅

**Files added/modified**
- `backend/services/secret_overrides_service.py` (NEW, 200+ lines)
- `backend/services/provider_test_service.py` (NEW, 165 lines)
- `backend/services/preset_stacks_service.py` (NEW, 380 lines)
- `backend/routes/admin_secrets_routes.py` (rewritten with secure CRUD)
- `backend/routes/admin_preset_stacks_routes.py` (NEW)
- `backend/routes/admin_lab_routes.py` (active_preset + config_source)
- `backend/services/audit_service.py` (new entity_types + actions)
- `backend/server.py` (startup hooks for overrides + preset seed + new router)
- `frontend/src/pages/admin/AdminSecrets.jsx` (rewritten)
- `frontend/src/pages/admin/AdminPresets.jsx` (NEW)
- `frontend/src/pages/admin/AdminLayout.jsx` (sidebar entry)
- `frontend/src/App.js` (route)
- `backend/tests/test_phase_h_secrets_presets.py` (NEW, 12 tests)

**118/119 total** (12 H + 9 G + 10 F + 25 E + 54 W1-4 + 8 D.5/D.3 — 1 pre-existing async-pytest config fail).

**Operator readiness — confirmed**
The admin can now, without any code edits or deployment:
  ✅ rotate provider credentials safely (encrypted, source-aware)
  ✅ verify provider auth with one click (4 providers wired)
  ✅ inspect the true final prompt before execution (Phase F)
  ✅ know which stages are real-call / preview-only / not-yet-wired / local-binary / reuse-from-other-stage (Phase G)
  ✅ switch between 5 named provider/model stacks safely (Phase H Presets)
  ✅ see exactly what will change (dry-run) before applying any preset
  ✅ audit every config action (audit_log)
  ✅ trust pricing/cost for actual references injected (Phase E)

**Intentionally still preview-only / not-yet-wired** (executor not implemented):
  • narration_generation (TTS) • video_generation • music_generation
  • book_page_image_generation (reuses scene image)
  • video_assembly + pdf_assembly (local binaries)

### Phase I — System Consistency / Pipeline Sync (Feb 2026) ✅

**What was incomplete before**
- `/admin/pipeline` knew only 6 stages (with legacy `final_assembly`) — completely
  out of sync with the 11-stage reality after Phase G/H.
- `DEFAULT_PIPELINE` in `services/config_service.py` still had `final_assembly`
  and was missing book_page_image_generation, video_generation,
  music_generation, video_assembly, pdf_assembly.
- `pipeline_service.per_stage_costs` was missing `book_page_image_generation`.
- No single-source-of-truth endpoint that joins lab + pipeline + presets +
  models + secrets + prompts.

**What was added**
- `services/config_service.DEFAULT_PIPELINE` rewritten:
  * 11 stages (legacy `final_assembly` removed)
  * Per-stage flags: `audio_aware`, `reference_aware`, `local_binary`,
    `reuses_scene_image_today`, `runs_before_scene_generation`,
    `gated_by_output_type` (`video`/`pdf`/`both`).
- Auto-migration on startup (`server.py`): existing `pipeline_config` doc is
  upgraded — new stages added, legacy `final_assembly` purged, admin
  customizations preserved per existing stage.
- `services/pipeline_readiness_service.build_readiness()` — new SSoT joining:
  SUPPORTED_STAGES + EXECUTOR_STATUS + STAGE_NOTES_AR + pipeline_config +
  model_registry (with DEFAULT_MODELS fallback) + prompt_templates +
  pricing.per_stage_costs + secret_overrides_service.secret_source +
  active preset.
- New endpoint `GET /api/admin/pipeline-readiness` exposes the consolidated
  payload with integrity check (`orphan_stages_in_pipeline` /
  `missing_stages_in_pipeline`) + `audio_aware_stages` /
  `reference_aware_stages` summaries + active preset + per-stage flags.
- `pages/admin/AdminPipeline.jsx` rewritten to consume the readiness endpoint:
  shows all 11 stages with executor_status badge, prompt-driven badge with
  version, preset provenance badge, provider/model/env/cost line,
  Arabic flag pills, executor_notes, enabled/fallback/max_retries
  controls (disabled honestly for `local-binary` / `reuse-from-other-stage`).

**Cross-page consistency proof**
The new `/admin/pipeline-readiness` and the existing `/admin/lab/stages`
return EXACT SAME provider/model/preset/executor_status/secret_source for
all 11 stages — verified diff-by-diff in TEST 2.

**Tests** — 11 new unit tests (`tests/test_phase_i_pipeline_readiness.py`):
DEFAULT_PIPELINE coverage (no orphans / no missing) · order matches stage
set · no legacy final_assembly · all 11 stages present · local-binary flags
on assembly · audio_aware on narration+music · reference_aware on
scene_image · output_type gating on video chain + pdf chain · `_flags`
helper correctness.

7 live API tests:
  TEST 1 pipeline-readiness: 11 supported/11 stages, integrity_ok=True. ✅
  TEST 2 cross-page consistency: lab vs pipeline diff = 0 mismatches across
  all 11 stages, active preset matches. ✅
  TEST 3 output_type gating visible per stage: narration/music/video/
  video_assembly → `gated:video,both`; book_page/pdf_assembly →
  `gated:pdf,both`. duration propagated through context_used. ✅
  TEST 4 references_aware + child_ref injected for real_order. ✅
  TEST 5 all real-call/preview-only/not-yet-wired stages have
  provider+prompt+secret. ✅
  TEST 6 manual readiness checklist: 5 secrets visible, 4 providers
  testable, 5 presets, 11 lab stages, 11 pipeline stages with active
  preset reflected everywhere. ✅
  TEST 7 zero regression: 54/54 unit tests + 11/11 stages preview ✅.

**Files modified (5)**
- `backend/services/config_service.py` (DEFAULT_PIPELINE rewritten)
- `backend/services/pipeline_readiness_service.py` (NEW, 140 lines)
- `backend/routes/admin_config_routes.py` (new endpoint)
- `backend/services/pricing_service.py` (book_page_image_generation cost)
- `backend/server.py` (auto-migration on startup)
- `frontend/src/pages/admin/AdminPipeline.jsx` (rewritten consuming readiness)
- `backend/tests/test_phase_i_pipeline_readiness.py` (NEW, 11 tests)

**129/130 total** (11 I + 12 H + 9 G + 10 F + 25 E + 54 W1-4 + 8 D.5/D.3 — 1
pre-existing async-pytest config fail).

**Manual operator readiness — final state**
The admin can now confidently begin manual testing because:
  ✅ /admin/pipeline reflects 100% of the real backend structure
  ✅ /admin/lab + /admin/pipeline + /admin/presets + /admin/secrets are diff-equal
  ✅ Every stage's executor honesty is preserved (real-call vs preview-only vs
    not-yet-wired vs local-binary vs reuse-from-other-stage)
  ✅ Active preset is shown identically across pages
  ✅ Provider/model/env_key/secret_source/prompt_source all aligned
  ✅ Output_type gating + audio mode awareness + reference awareness are
    visible flags, not hidden behaviors
  ✅ Pricing structure matches the 11-stage reality
  ✅ Zero regression — 54 unit tests + 11/11 preview stages green


### Phase K — TTS Executor + Unified Stage Control (Feb 27, 2026) ✅

**What landed**
1. **Real ElevenLabs TTS adapter** — `services/tts_service.py` (provider-adapter
   pattern). Default model `eleven_multilingual_v2`, default voice `EXAVITQu4vr4xnSDxMaL`.
   Resolves `ELEVENLABS_API_KEY` via `secret_overrides_service` (encrypted DB
   override wins over `.env`). On any failure or missing key, gracefully
   degrades to mock and surfaces the truth in `meta.fallback_to_mock`.
2. **Audio service rewired** — `services/audio_generation_service.py` is now a
   thin re-export wrapper over `tts_service.generate_tts`; legacy callers in
   `generation_orchestrator` are unchanged.
3. **Lab executor for narration** — `_run_narration_generation` in
   `stage_lab_service.py` makes a real TTS call when key is present, saves the
   resulting MP3 to internal storage, returns a playable `/api/uploads/file/{id}`
   URL. Hard cap of 600 chars on lab text to control spend.
4. **Honest status** — `EXECUTOR_STATUS["narration_generation"] = "real-call-when-keyed"`.
   Pipeline readiness exposes `executor_callable` (bool) and `prompt_editable`
   (bool) per stage. `narration_real_call_available()` collapses provider +
   key resolution into a single source of truth.
5. **Unified `/admin/stage-control`** — new page covering all 11 canonical
   stages on a single screen. Per stage shows: executor_status badge,
   executor_callable indicator, provider/model/env/fallback editors,
   secret source (with link to `/admin/secrets` when missing), config_source
   (preset/manual/default), prompt-driven badge with version, cost line,
   notes, plus Save / Reset / Test-in-Lab actions. KPI strip surfaces
   callable/total, missing keys, not-yet-wired count, prompt count, and
   narration-real-call status. Active preset banner + integrity warning are
   inherited from pipeline_readiness.
6. **New backend routes** — `POST /api/admin/stage-control/state` (read),
   `PATCH /api/admin/stage-control/{stage_key}` (upsert provider/model/env/active),
   `POST /api/admin/stage-control/{stage_key}/reset` (back to DEFAULT_MODELS).
   All actions audited under `entity_type=stage_control`.
7. **Pricing audit** — `narration_generation` cost now 0.20 SAR (was 0.05);
   added `video_generation` (1.20) and `music_generation` (0.40) defaults so
   future executor wiring already has cost lines. `narration_audio` kept in
   sync (used by the live orchestrator).

**Acceptance — Phase K objectives delivered**
  ✅ `narration_generation` executor is REAL-CALL when ELEVENLABS_API_KEY is
     present (override or env). No code change needed to flip — admin adds
     the key under `/admin/secrets` and the stage flips to `executor_callable=True`.
  ✅ Provider-adapter shape — `_tts_via_openai` registered as a stub for the
     follow-up phase; one-function replacement is enough to wire it.
  ✅ `/admin/stage-control` covers ALL 11 stages, not only real-call ones.
  ✅ Each stage card shows executor_status, provider, model, secret source,
     config source, prompt editable/not, and executable-now indicator.
  ✅ `audio_background_mode` behaviour preserved (no regressions in
     orchestrator; readiness still flags audio_aware stages).
  ✅ Unified state endpoint reports `stages_remaining_to_wire` —
     today: `["music_generation", "video_generation"]`. Final video can be
     produced with real narration as soon as ELEVENLABS_API_KEY is set
     (cover + scene images + narration mp3 + ffmpeg assembly).

**Tests**
  Unit (Phase K): 13/13 passing
  (`tests/test_phase_k_tts_stage_control.py`)
  API (Phase K, written by testing agent): 10/10 passing
  (`tests/test_phase_k_api.py`)
  Adjusted snapshot tests: test_phase_g_lab_gaps, test_phase_e_api,
  test_wave2_pricing_lab_secrets, test_wave3_bundles_audit_payment all
  updated to reflect Phase K reality. Total unit suite: 116/116 passing
  (excluding 3 pre-existing pytest-asyncio config failures unrelated to K).

**Files added**
  - `backend/services/tts_service.py`
  - `backend/routes/admin_stage_control_routes.py`
  - `backend/tests/test_phase_k_tts_stage_control.py`
  - `frontend/src/pages/admin/AdminStageControl.jsx`

**Files updated**
  - `backend/services/audio_generation_service.py` (now wraps tts_service)
  - `backend/services/stage_lab_service.py` (executor + status update + REAL_CALL_STAGES)
  - `backend/services/pipeline_readiness_service.py` (executor_callable + prompt_editable)
  - `backend/services/pricing_service.py` (narration cost bump + new defaults)
  - `backend/services/audit_service.py` (stage_control entity + actions)
  - `backend/server.py` (router include)
  - `frontend/src/App.js` (route)
  - `frontend/src/pages/admin/AdminLayout.jsx` (sidebar nav entry)


## Backlog (Phase 6 — NOT built yet)
- Image generation (GPT Image 1 or Nano Banana) using the `image_prompt.prompt_text` + reference image.  ✅ Done
- Video animation (Sora 2 or equivalent) using `animation_prompt`.  (still pending real-call wiring)
- Narration audio (OpenAI TTS/ElevenLabs) using `narration_text`.  ✅ Done — ElevenLabs wired Phase K
- PDF storybook using `book_pages.text` + generated illustrations.  ✅ Done

## Active Backlog (post-Phase L)
**P1 (next up)**
- `music_generation` real executor (Suno or ElevenLabs Music) — only stage left as `not-yet-wired`. Adapter slot exists in `tts_service` family.
- Prompt Diff Viewer + Prompt Health Dashboard UI (deferred from Phase H).
- AdminStoryboard surfacing `video_clips` per scene (provider/model/strategy/clip_url/state) — orchestrator already persists; UI binding pending.

**P2**
- Audio background mixing in `ffmpeg` using actual audio tracks (`audio_background_mode`).
- Pipeline config caps editor UI (editable reference caps).
- PDF size shrink (~10MB → ~2MB via JPEG recompression).
- OpenAI TTS adapter — single-function wire-up in `tts_service._tts_via_openai`.
- Sora 2 / Luma video adapters — single-function wire-up in `video_generation_service._video_via_sora` / `_video_via_luma`.


### Phase L — fal.ai Kling Video Executor + Hybrid Assembly (Feb 27, 2026) ✅

**What landed**
1. **Real fal.ai Kling adapter** — `services/video_generation_service.py` with
   provider-adapter pattern. Default: `fal-ai/kling-video/v2.1/standard/image-to-video`
   (admin-overridable from Stage Control). Submit→poll→download via
   `https://queue.fal.run/{slug}` using `Authorization: Key FAL_KEY`. Sora &
   Luma slots reserved as one-function-wire-up stubs.
2. **Hybrid I2V/T2V strategy** — `submit_clip` picks the I2V endpoint when a
   scene image URL is provided, otherwise auto-converts to the matching
   `/text-to-video` slug. The strategy is reflected per-scene in
   `db.video_clips.clip_strategy`.
3. **Submit-all-then-poll-parallel orchestration** — new
   `_run_video_generation_stage` in `generation_orchestrator` runs after
   asset jobs when `output_type` includes video AND `pipeline_config` has
   `video_generation.enabled=True` AND `video_real_call_available()`. Submits
   every scene first, then polls with `asyncio.gather` (poll_interval=10s,
   max_wait=900s). Persists clips in `db.video_clips` and a per-order
   `video_generation_summary`.
4. **Hybrid video assembly** — `video_assembly_service` now prefers real
   per-scene Kling clips when present (re-encodes to 1280x720 24fps for
   safe concat), falls back to slideshow per missing clip. New `assembly_mode`
   ∈ `{real_clips, hybrid, slideshow}` exposed in meta. ffmpeg remains the
   authoritative final-cut path; native audio mixing still slated for next phase.
5. **Stage Lab executor for video** — `_run_video_generation` in
   `stage_lab_service`: single-scene synchronous submit→poll→download with
   max_wait=240s and 5s duration cap. Saves clip to internal storage,
   returns playable `/api/uploads/file/{id}` URL. Cost-ack gated.
6. **Stage Control UI** — new green video banner with Arabic guidance,
   `kpi-video` ("فيديو Kling حقيقي: نعم/لا"), `video_generation` row defaults
   to `kling`/Kling-default with provider menu `[kling, sora, luma, ffmpeg]`.
7. **Provider Connectivity Test** — `provider_test_service.test_fal()` added;
   secrets page exposes a working `Test connection` button via
   `POST /api/admin/secrets/test/fal`.
8. **Secrets registry** — `FAL_KEY` added to `KNOWN_ENV_KEYS`
   (label="fal.ai (Kling Video)", providers=["kling","luma"], optional=True).
9. **Pricing audit** — `per_stage_costs.video_generation = 2.50` SAR, plus
   new `video_generation_per_model` map (v2.1 standard 1.20 → v3 pro 3.60
   per scene clip).
10. **Default model registry update** — `DEFAULT_MODELS.video_generation`
    flipped from `ffmpeg/local-slideshow` to `kling/Kling-default`. **One-time
    auto-migration** in `server.py` startup updates legacy rows.
11. **Seed prompt template** — `video_generation` template rewritten to
    drive Kling I2V/T2V with cinematic camera + emotional_tone + character
    consistency hints.

**Acceptance — Phase L objectives delivered**
  ✅ video_generation real-call when FAL_KEY present (no code edit needed).
  ✅ Provider-adapter shape; Sora/Luma stubs ready for one-function wire-up.
  ✅ /admin/stage-control + /admin/secrets + /admin/lab + /admin/pipeline all reflect Kling truthfully.
  ✅ Honest fallback to ffmpeg slideshow when key missing or any clip fails.
  ✅ Per-model pricing override admin-tunable.
  ✅ Cost-ack gate enforced for lab runs.
  ✅ Final video honestly states `assembly_mode` (real_clips / hybrid / slideshow).
  ✅ ffmpeg remains authoritative for final assembly — native audio from
     Kling NOT used in the final path (documented honestly).

**Tests**
  Unit (Phase L): 16/16 (`tests/test_phase_l_video_kling.py`)
  API (live, Phase L): 10/10 (testing agent generated `tests/test_phase_l_api.py`)
  Adjusted snapshot tests: `test_phase_g_lab_gaps`, `test_phase_k_api`,
  `test_wave2_pricing_lab_secrets` updated to reflect Phase L reality.
  Total unit suite: 142/142 passing.

**Files added**
  - `backend/services/video_generation_service.py`
  - `backend/tests/test_phase_l_video_kling.py`

**Files updated**
  - `backend/services/generation_orchestrator.py` (+`_run_video_generation_stage`, os import)
  - `backend/services/video_assembly_service.py` (real-clip path + assembly_mode)
  - `backend/services/stage_lab_service.py` (`_run_video_generation`, EXECUTOR_STATUS, REAL_CALL_STAGES)
  - `backend/services/pipeline_readiness_service.py` (video_real_call_available wiring)
  - `backend/services/pricing_service.py` (per_stage_costs + video_generation_per_model)
  - `backend/services/config_service.py` (DEFAULT_MODELS.video_generation, PROVIDER_ENV_MAP.kling)
  - `backend/services/provider_test_service.py` (`test_fal`)
  - `backend/routes/admin_secrets_routes.py` (FAL_KEY entry)
  - `backend/routes/admin_stage_control_routes.py` (video_real_call_available, video_defaults, _VIDEO_PROVIDERS)
  - `backend/server.py` (Phase L migration on startup)
  - `backend/seed.py` (video_generation prompt template)
  - `frontend/src/pages/admin/AdminStageControl.jsx` (video KPI + banner + Clapperboard)


## Active Backlog (post-Phase L)
**P1 (next up)**
- `music_generation` real executor (Suno or ElevenLabs Music) — only stage left as `not-yet-wired`.
- Prompt Diff Viewer + Prompt Health Dashboard UI.
- AdminStoryboard surfacing `video_clips` per scene with strategy/state.

**P2**
- Audio background mixing in `ffmpeg` using actual audio tracks.
- Sora 2 / Luma video adapters — single-function wire-up.
- OpenAI TTS adapter — single-function wire-up.
- Pipeline config caps editor UI.
- PDF size shrink (~10MB → ~2MB).

## P1 Enhancements (later)
- Per-user character_profiles (reuse across stories for the same child).
- Transaction/insert-first-then-archive on regeneration to avoid rare partial states.
- Unique index on `(order_id, production_plan_id, scene_index)`.
- Cost dashboard using `duration.cost_tier` + `total_word_count`.
