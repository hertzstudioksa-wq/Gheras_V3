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

### Phase 5.1 — User-Facing Approval Page (Apr 21, 2026)
- New route: `/orders/{id}/production-ready` (`ProductionReady.jsx`).
- Arabic RTL, mobile-first, sticky bottom action bar on mobile.
- States: loading, `production_planning` skeleton, `production_ready` (summary+actions), `production_approved` (success), `failed` (retry guidance).
- Shows: title, story_summary, main_message, duration, scene_count, image_count, safety_check.
- Hides: all prompts, scenes, IDs, admin-only details.
- Actions: "موافق على الخطة" (with loader) + "إعادة إعداد الخطة" (1 attempt + confirm dialog).
- After scenario selection, users are now redirected to this page automatically.
- Dashboard deep-links directly to the right route based on status.

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
