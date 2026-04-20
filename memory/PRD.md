# Gheras (غِراس) — PRD

## Problem Statement
Arabic-first (RTL) AI storytelling platform for children. The Story Builder collects structured inputs, Claude Sonnet 4.5 generates 3 personalized scenarios, the parent selects one, and the selection is stored for future AI video/image/PDF production (Phase 5 — NOT built yet).

## Architecture
- **Backend**: FastAPI + MongoDB (Motor). Auth: JWT. LLM: Claude Sonnet 4.5 via `emergentintegrations`.
- **Frontend**: React + Tailwind + Shadcn UI. RTL Arabic.
- **Storage**: Emergent Object Storage for image uploads.

## Implemented (through Phase 4 — Apr 20, 2026)
### Phase 1–3 (earlier sessions)
- JWT auth, admin seed, drafts auto-save.
- 6-step Story Builder wizard.
- Order state machine with `status_history`.
- Scenario generation via Claude Sonnet 4.5 (`claude-sonnet-4-5-20250929`) with deterministic Arabic fallback.
- Parent Scenario Selection UI + Admin panel with manual regenerate/select/delete.

### Phase 4 (current session — Apr 20, 2026)
1. **Scenario batches**: every regeneration creates a new `scenario_batch_id`; prior scenarios are archived (`is_archived=true`) not deleted. Users see only the current batch; admin sees all batches.
2. **Video Duration slider** (Step 5): snap points 30/45/60/90/120/150/180s (default 90 = "دقيقة ونصف"). Maps to `scene_target` (3–9) and `cost_tier` (low/medium/high).
3. **`why_this_fits` field** on every scenario, shown on parent selection cards and admin view.
4. **Max 3 user regenerations** enforced server-side (429 with Arabic detail). Last-attempt confirm dialog on UI. Admin bypass with badge `Max reached`.
5. **Admin batches accordion**: latest batch auto-expanded, per-batch source badge (AI/Fallback), `N / 3` counter, bypass regenerate button.
6. **Selection guard**: user cannot select from archived batch (400); admin can (auto-promotes batch to current).

## Key Schema
### orders (new/updated fields)
- `duration`: `{seconds, label, scene_target, cost_tier}`
- `current_scenario_batch_id: str`
- `selected_scenario_batch_id: str | null`
- `regeneration_count: int` (default 0)
- `max_regenerations: int` (default 3)
- existing: `data`, `enriched`, `status`, `status_history`, `ai_prompt_snapshot`, `selected_scenario_id`, `selected_scenario_snapshot`, `scenarios_generation`.

### scenarios (new/updated fields)
- `scenario_batch_id: str`
- `why_this_fits: str`
- `is_archived: bool`
- `source: "ai" | "fallback"`
- existing: `title, short_summary, emotional_angle, learning_goal, visual_style_hint, estimated_scene_count, scenario_index, is_selected, created_at`.

## Key Endpoints
### User
- `POST /api/orders` — accepts `data.duration.seconds`, stores normalized duration + initial batch_id.
- `GET /api/orders/{id}/scenarios` — returns only current-batch scenarios + `regeneration_count`, `max_regenerations`, `regenerations_remaining`, `duration`.
- `POST /api/orders/{id}/scenarios/regenerate` — 200 w/ new batch_id; 429 after 3 uses (Arabic detail).
- `POST /api/orders/{id}/scenarios/{sid}/select` — 400 if scenario is from an archived batch.

### Admin (unchanged routes, richer responses)
- `GET /api/admin/orders/{id}/scenarios` — returns `batches[]` (grouped, latest first, `is_current` flag) + counters + duration.
- `POST /api/admin/orders/{id}/scenarios/regenerate` — bypasses 3-limit, still bumps counter.
- `POST /api/admin/orders/{id}/scenarios/{sid}/select` — admin can select from any batch; auto-promotes that batch to current.

## Affected Files
### Backend
- `/app/backend/models.py` — added `DURATION_SNAPS`, `duration_meta()`, `DurationPayload`, `StoryData.duration`.
- `/app/backend/services/scenario_service.py` — new system prompt w/ `why_this_fits`, scene_target injection, `_clamp_scene_count`, `build_scenario_docs(order_id, items, batch_id, source)`.
- `/app/backend/routes/order_routes.py` — batch-aware `run_scenario_generation`, `MAX_REGENERATIONS=3`, list/select guards, duration normalization in `create_order`.
- `/app/backend/routes/admin_routes.py` — `admin_list_scenarios` returns grouped batches; `admin_regenerate_scenarios` bypasses limit; `admin_select_scenario` promotes old batch.

### Frontend
- `/app/frontend/src/pages/StoryBuilder.jsx` — added `DurationPicker` component in Step 5 (testids: `duration-picker`, `duration-slider`, `duration-snap-{s}`, `duration-scene-target`, `duration-cost-tier`). `blankData` initializes `duration:{seconds:90}`. Review Step 6 shows duration field.
- `/app/frontend/src/pages/ScenarioSelection.jsx` — renders `why-fits-{id}`, `regen-counter`, `last-attempt-warning`, `limit-reached-warning`; regenerate button disabled + tooltip when limit reached; confirm dialog on last attempt.
- `/app/frontend/src/pages/admin/AdminOrders.jsx` — new `AdminScenariosTab` with accordion per batch (`admin-batch-{bid}`, `admin-batch-toggle-{bid}`), `admin-regen-counter`, `admin-max-reached-badge`, bypass-enabled `admin-regen-scenarios`.

## Testing Status
- Backend: smoke-validated end-to-end via curl (duration mapping, batches, 3-regen cap + 429 Arabic, admin bypass, archived-batch select 400).
- Testing agent Phase 4 pass: 14/14 targeted tests green; 3 long-running regression tests not run (timed out).
- Frontend: loads; full interactive testids not yet end-to-end tested.

## Backlog / Future
- **P0 — Phase 5**: Image, Video, PDF production using `selected_scenario_snapshot` (user explicitly asked to defer).
- **P1**: Unique index on `(order_id, scenario_batch_id, scenario_index)` in `scenarios`.
- **P1**: Transaction / insert-first-then-archive to avoid rare partial states on regeneration failure.
- **P2**: Per-child/per-order cost tracking & dashboard using `duration.cost_tier`.
- **P2**: Email/notification when scenarios are ready.

## Known Issues / Caveats
- `admin bypass regeneration` still bumps user `regeneration_count` — spec-intentional but causes `regenerations_remaining=0` for user after any admin regen.
- Very brief race: if user polls `/scenarios` before background LLM insert finishes, they see empty list + `scenarios_generating` status (UI already handles this with polling skeleton).
- `duration_meta` snaps nearest if an unknown value is sent; zero is treated as default 90 (intentional fail-safe).
