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

## Backlog (Phase 6 — NOT built yet)
- Image generation (GPT Image 1 or Nano Banana) using the `image_prompt.prompt_text` + reference image.
- Video animation (Sora 2 or equivalent) using `animation_prompt`.
- Narration audio (OpenAI TTS/ElevenLabs) using `narration_text`.
- PDF storybook using `book_pages.text` + generated illustrations.

## P1 Enhancements (later)
- Per-user character_profiles (reuse across stories for the same child).
- Transaction/insert-first-then-archive on regeneration to avoid rare partial states.
- Unique index on `(order_id, production_plan_id, scene_index)`.
- Cost dashboard using `duration.cost_tier` + `total_word_count`.
