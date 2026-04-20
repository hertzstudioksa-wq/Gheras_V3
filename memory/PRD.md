# PRD — غِراس (Gheras) AI Storytelling Platform

## Problem Statement
Arabic-first (RTL) production-level AI storytelling platform for children. Parents create personalized stories where their child is the hero, to teach values and behaviors. Includes dynamic admin system — every piece of content editable from an admin panel.

## User Personas
1. **الوالدان (Parents / End Users)** — Arabic-speaking parents of children 1–14 y/o who want tailored educational stories.
2. **المدير (Admin / Content Operator)** — Edits landing copy, categories, story styles, AI prompts, pricing, reviews orders, manages users.
3. **(Future) محرر محتوى** — Reviews AI-generated stories before they ship.

## Architecture
- **Frontend**: React 19 + React Router 7 + TailwindCSS + Shadcn + Sonner. RTL globally (`<html dir="rtl" lang="ar">`). Fonts: El Messiri (heading) + Tajawal (body).
- **Backend**: FastAPI + Motor (async MongoDB) + JWT (PyJWT) + bcrypt. All routes `/api/*`.
- **Database**: MongoDB collections — `users`, `children`, `orders`, `categories`, `subcategories`, `story_styles`, `content`, `prompts`, `plans`, `settings`. All IDs are UUID strings, `_id` excluded from every response.

## What's Been Implemented (Phase 1 — 2026-04-20)
### Public website
- Landing (hero + values + how-it-works preview + categories preview + CTA), all content **pulled from CMS content blocks**.
- How It Works detail page.
- Categories browse page (dynamic from DB).
### Auth
- Email/password signup + login, JWT stored in localStorage (`gheras_token`).
- Protected routes + admin-only routes via `ProtectedRoute`.
- Seeded admin `admin@gheras.com / Admin@1234` with `role=admin`, `must_change_password=true`.
### Story Builder (5-step card wizard)
1. Goal (category → subcategory chips; custom text for free-form)
2. Child info (name, age, gender, personality, interests, appearance)
3. Personalization (color, toy, parent message, sibling toggle)
4. Style (5 seeded styles — card selection)
5. Review + final notes → submit creates an Order
- Draft auto-saved to localStorage; if user is anonymous they're routed to login and draft restored.
### User Dashboard
- List of orders with Arabic status badges, links to order detail with full snapshot.
### Order System
- `status ∈ {pending, in_review, ready_for_ai, generating, completed}`
- Every order stores `child_snapshot` + `personalization` + **pre-computed `ai_prompt_snapshot`** ready for future AI hookup.
### Admin Dashboard (`/admin`)
- Overview (stats + recent orders)
- Orders (filter by status, view modal, change status, admin note)
- Users (toggle active, promote/demote admin)
- Categories & subcategories CRUD (icons + colors)
- Story Styles CRUD
- Content Blocks CMS (edit any text on landing page)
- AI Prompts CRUD (template + variables)
- Plans & Pricing CRUD
- Settings (generic key/value)
### Seeded Data
- 8 categories + full subcategory tree exactly per spec (السلوك اليومي, المشاعر, القيم والأخلاق, العادات الإيجابية, القيم الإسلامية, الخيال والطموح, قصص قبل النوم, حالة خاصة)
- 5 story styles, 3 plans, 2 AI prompt templates, 4 system settings, ~20 content blocks.

## Testing
- **33/33 backend tests passed** (pytest) covering auth, public endpoints, orders full lifecycle, admin CRUD, admin guards, status workflow, _id exclusion, child_snapshot persistence.

## Design System
- Palette: `#FDFBF7` (page), `#F8F1E7` (cards), `#87A96B` (brand sage), `#D4A373` (gold), `#E07A5F` (coral), `#8B5A2B` (brown).
- Components: rounded-3xl cards, pill buttons, stepper circles with connecting progress line, animated blob shapes, grain-free warm aesthetic.

## P0 Backlog (Next)
- **Google OAuth** (Emergent-managed) alongside JWT for faster parent signups.
- **AI generation wiring**: call Claude/GPT using `prompts.story.generate.master` template on status → `ready_for_ai`.
- **Image + video generation** via Nano Banana / Sora when order → `generating`.
- **PDF export** of finished story + shareable link.

## P1 Backlog
- Email notifications on order status change (Resend).
- Child profiles reuse (instead of re-entering child data per story).
- Payment + plan subscription (Stripe).
- Analytics dashboard for admin (completion rate, avg time per status).

## P2 Backlog
- Arabic + English i18n (infrastructure already in place via content blocks).
- Audio narration.
- Parent collaborative editing/approval before final publish.

## Known Minor Issues (non-blocking, see iteration_1.json)
- `POST /api/auth/register` returns 422 (Pydantic) for malformed email instead of 400 with Arabic message.
- `GET /api/auth/me` without token returns 403 instead of 401 (FastAPI HTTPBearer default).
- `POST /api/orders` inserts a new child doc each time (no de-dup).
- Admin PATCH endpoints require full payload (not true PATCH semantics yet).
