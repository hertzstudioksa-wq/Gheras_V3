# PRD — غِراس (Gheras) v2

## Phase 2 Scope (this iteration)
Upgraded Story Builder to 6 steps with structured JSON data model, integrated Emergent Object Storage, server-side drafts, and fully dynamic Step-5 story options.

## Architecture
- **Frontend**: React 19 + React Router + Tailwind + Shadcn + Sonner (RTL).
- **Backend**: FastAPI + Motor (MongoDB) + JWT + bcrypt. All routes `/api/*`.
- **Storage**: Emergent Object Storage (managed). Only URLs stored in DB.
- **LLM key**: `EMERGENT_LLM_KEY` configured (ready for future AI hookup).

## Database Schema
| Collection | Purpose |
|---|---|
| `users` | accounts + admin role |
| `categories` / `subcategories` | dynamic taxonomy |
| `story_options` | polymorphic Step-5 options (kind ∈ type\|tone\|setting\|language\|voice) with `is_active`, `is_hidden`, `sort_order` |
| `orders` | **structured JSON** `{id, user_id, status, data, enriched, ai_prompt_snapshot, prompt_edited, admin_note, created_at, updated_at}` |
| `drafts` | one-per-user `{user_id, current_step, data, updated_at}` — auto-upsert |
| `files` | uploaded file index `{id, user_id, scope, storage_path, content_type, size}` |
| `content` | CMS key/value blocks |
| `prompts` | reference AI templates |
| `plans` | subscription tiers |
| `settings` | incl. `characters.max_count=3`, `upload.max_mb=6` |

`story_styles` collection dropped.

## Story Builder — 6 Steps (final)
1. **Goal** — category card + subcategory chips + "أخرى" inline text + **required** "موقف حقيقي" textarea.
2. **Child** — name, age, gender, **required image upload**, appearance notes, hijab toggle (female only).
3. **Characters** — add up to `characters.max_count` (default 3). Each: type chips (mother/father/sibling/friend/teacher/grandparent/other), optional name, role (mentioned/visible), optional image upload revealed when role=visible.
4. **Personalization** — multi-select favorites (toy/place/character/hobby/other) → dynamic name field + optional toy image upload + custom notes.
5. **Style** — 5 dynamic chip groups from `/public/story-options` (type, tone, setting, language, voice). Admin-editable.
6. **Review** — visual summary + expandable raw JSON.

Mobile: sticky bottom action bar (السابق / التالي / إرسال).

## Structured JSON (stored in `order.data`)
```json
{
  "goal": {
    "category_id": "<uuid>",
    "subcategory_id": "<uuid|null>",
    "custom_subcategory": "نص حر لو اختار أخرى",
    "context": "أمس رفض يوسف مشاركة لعبته مع أخيه"
  },
  "child": {
    "name": "يوسف",
    "age": 5,
    "gender": "male",
    "image_url": "/api/uploads/file/<uuid>",
    "appearance_notes": "شعر أسود قصير",
    "hijab": false
  },
  "characters": [
    { "type": "sibling", "name": "أحمد", "role": "visible", "image_url": "/api/uploads/file/<uuid>" }
  ],
  "personalization": {
    "favorites": {
      "toy":   { "selected": true,  "name": "دب أبيض" },
      "place": { "selected": false, "name": null }
    },
    "toy_image_url": "/api/uploads/file/<uuid>",
    "custom_notes": "يحب كلمة 'حبيبي' في النهاية"
  },
  "style": {
    "type_id":     "<uuid>",
    "tone_id":     "<uuid>",
    "setting_id":  "<uuid>",
    "language_id": "<uuid>",
    "voice_id":    "<uuid>"
  }
}
```
Alongside `data`, `enriched` carries resolved Arabic names (category_name, subcategory_name, type_name, tone_name, setting_name, language_name, voice_name).

## Prompt Engine
`build_prompt(data, enriched)` produces an Arabic prompt including:
- child identity + gender + hijab state
- goal: category → subcategory/custom + **real-life context**
- appearance notes + reference image URL
- characters list with role labels
- favorites (comma-joined Arabic labels)
- style line (نوع/نبرة/بيئة/لغة/راوٍ)
- narrative instructions (warmth, age-appropriate, values woven not preached)

Stored in `order.ai_prompt_snapshot`. Admin can:
- **edit manually** → `PATCH /admin/orders/{id}/prompt` (sets `prompt_edited=true`)
- **regenerate from JSON** → `POST /admin/orders/{id}/regenerate-prompt`

## Storage System
- Uses Emergent Object Storage (no external setup).
- Paths: `gheras/users/{user_id}/{scope}s/{file_id}.{ext}` where scope ∈ {child, character, toy}.
- Max 6 MB. Allowed: png, jpg, jpeg, webp, gif.
- Access: backend proxies via `GET /api/uploads/file/{id}` — owner OR admin only. Authentication via `Authorization: Bearer` header OR `?auth=<token>` query (for `<img src>` tags).
- DB stores only the backend-proxy URL; raw storage path kept internal.

## Drafts System
- **Logged-in user**: every change debounced 600 ms → `PUT /api/drafts/current` (one-per-user upsert).
- **Guest**: same payload written to `localStorage["gheras_story_draft_v2"]`.
- Hydration priority: logged-in → server draft first, else localStorage.
- On successful order creation → draft cleared (server + local).

## Admin Dashboard (v2 capabilities)
- View all orders + full JSON + prompt editor tab with regenerate.
- Story-options CRUD grouped by kind + show/hide toggle.
- Settings CRUD (edit `characters.max_count`, `upload.max_mb`, any key).
- Content blocks CMS.
- Categories + subcategories CRUD.
- Users, plans, prompts CRUD.
- 5-state order workflow (pending → in_review → ready_for_ai → generating → completed).

## Testing
- **iteration_2.json: 33/33 passed** (uploads w/ 401/403/admin-override, orders full lifecycle, drafts lifecycle, admin overrides, RBAC, no _id leaks).

## P1 Backlog
- Google OAuth (Emergent-managed) alongside JWT.
- AI generation: Claude Sonnet to consume `ai_prompt_snapshot` on `ready_for_ai`.
- Nano Banana for scene images + Sora2 for video at `generating`.
- PDF export on `completed`.
- Payment (Stripe) for plan subscription.

## P2 Backlog
- English i18n.
- Child profiles reuse.
- Audio narration.
- Showcase gallery ("قصصنا").
