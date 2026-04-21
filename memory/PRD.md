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
- Added `services/progress_service.py` — unified 0..100 progress across the whole pipeline
  (plan 0-20 → assets 20-80 → assembly 80-100 → delivered 100). All user endpoints
  (`/production-summary`, `/media-status`, `/delivery`) expose the same `{stage, stage_ar, percent, message_ar}` object.
- User-endpoint sanitization: `order_routes._sanitize_user_order` + `_PUBLIC_SCENARIO_KEYS`
  strip `ai_prompt_snapshot`, `prompt_edited`, `scenarios_generation`, `production_generation`,
  `status_history`, `admin_note`, `*_run_id`, `production_plan_id`, and internal batch ids.
  Scenario snapshot is trimmed to a strict allow-list (title/summary/angles/…).
- Race-condition guard in `get_production_summary`: when `status == production_ready` but
  the plan document isn't saved yet, the endpoint downgrades to `production_planning` so the
  UI never shows a "ready" header with a null summary.
- Video assembly hardening (`_make_placeholder_png` in `video_assembly_service.py`):
  missing scene images are substituted with a warm-toned placeholder PNG so the pipeline
  NEVER fails because of one missing frame. `assembly_metadata.placeholder_frames` reports how many.
- New user endpoint `POST /api/orders/{id}/retry-delivery` — resumes from whichever phase
  failed (assets vs assembly). Requires cover + ≥1 scene image to retry assembly-only;
  else retries full pipeline.
- Frontend `ProductionReady.jsx`: unified progress bar + `StagePill` indicator,
  retry button on `media_failed`, skeleton respects unified message.
- Frontend `ScenarioSelection.jsx`: removed "مصدر التوليد" banner (was leaking internal info).
- Test suite `/app/backend/tests/test_stabilization.py` — 9/9 green.

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
