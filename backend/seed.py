"""Seed database with initial data — v2."""
import os
import uuid
from datetime import datetime, timezone

from db import db
from auth import hash_password
from models import UserRole


def _now():
    return datetime.now(timezone.utc).isoformat()


CATEGORIES = [
    {"slug": "daily-behavior", "name_ar": "السلوك اليومي", "icon": "sun", "color": "#D4A373",
     "description": "قصص تساعد على تعديل السلوكيات اليومية بحب ولطف", "sort_order": 1,
     "subcategories": ["الاستماع للوالدين", "التوقف عن الضرب", "ترتيب الألعاب", "قول الحقيقة", "المشاركة"]},
    {"slug": "emotions", "name_ar": "المشاعر", "icon": "heart", "color": "#E07A5F",
     "description": "فهم المشاعر والتعبير عنها بطريقة صحية", "sort_order": 2,
     "subcategories": ["الغضب", "الخوف", "الغيرة", "الحزن", "الثقة بالنفس"]},
    {"slug": "values", "name_ar": "القيم والأخلاق", "icon": "award", "color": "#87A96B",
     "description": "غرس القيم والأخلاق الحميدة في قلب طفلك", "sort_order": 3,
     "subcategories": ["الصدق", "الأمانة", "الرحمة", "الاحترام", "المسؤولية", "التعاون", "التواضع"]},
    {"slug": "positive-habits", "name_ar": "العادات الإيجابية", "icon": "sparkles", "color": "#729352",
     "description": "بناء عادات يومية إيجابية تدوم مدى الحياة", "sort_order": 4,
     "subcategories": ["النظافة", "النوم المبكر", "العناية بالأسنان", "النظام", "الانضباط"]},
    {"slug": "islamic-values", "name_ar": "القيم الإسلامية", "icon": "moon", "color": "#8B5A2B",
     "description": "تعليم القيم الإسلامية بأسلوب مبسّط ومحبب", "sort_order": 5,
     "subcategories": ["الصلاة", "بر الوالدين", "الشكر", "حسن الظن بالله", "آداب الكلام", "الرحمة", "الأمانة"]},
    {"slug": "imagination", "name_ar": "الخيال والطموح", "icon": "rocket", "color": "#D4A373",
     "description": "قصص تلهم طفلك ليحلم ويطمح ويصبح بطل غده", "sort_order": 6,
     "subcategories": ["طبيب", "شرطي", "رائد فضاء", "بطل", "مستكشف"]},
    {"slug": "bedtime", "name_ar": "قصص قبل النوم", "icon": "moon-star", "color": "#5A677D",
     "description": "قصص هادئة تساعد طفلك على نوم عميق وآمن", "sort_order": 7,
     "subcategories": ["الطمأنينة", "الهدوء", "التغلب على الخوف", "النوم بسهولة"]},
    {"slug": "custom", "name_ar": "حالة خاصة / مخصصة", "icon": "pen-tool", "color": "#87A96B",
     "description": "اكتب بنفسك القيمة أو السلوك الذي تريد تعليمه لطفلك", "sort_order": 8,
     "subcategories": []},
]

STORY_OPTIONS = [
    # kind, name_ar, value, sort
    ("type", "واقعية", "realistic", 1),
    ("type", "خيالية", "fantasy", 2),
    ("type", "مرحة", "funny", 3),
    ("type", "مغامرات", "adventure", 4),
    ("type", "قبل النوم", "bedtime", 5),

    ("tone", "عاطفية", "emotional", 1),
    ("tone", "تعليمية", "educational", 2),
    ("tone", "هادئة", "calm", 3),
    ("tone", "مشوّقة", "exciting", 4),

    ("setting", "البيت", "home", 1),
    ("setting", "المدرسة", "school", 2),
    ("setting", "الحديقة", "park", 3),
    ("setting", "عالم خيالي", "fantasy-world", 4),
    ("setting", "تلقائي", "auto", 5),

    ("language", "عربية فصحى مبسّطة", "arabic-simple", 1),
    ("language", "لهجة خليجية", "gulf", 2),
    ("language", "لهجة مصرية", "egyptian", 3),

    ("voice", "صوت ولد", "boy", 1),
    ("voice", "صوت بنت", "girl", 2),
    ("voice", "تلقائي", "auto", 3),
]

CONTENT_BLOCKS = [
    {"section": "hero", "key": "hero.title", "value": "نَغرِس القِيَم بقِصصٍ بَطلُها طِفلُك"},
    {"section": "hero", "key": "hero.subtitle",
     "value": "منصة غِراس تصنع لطفلك قصصاً شخصيّة بصوته واسمه وصورته، تُعلّمه القيم الجميلة وتُعدّل سلوكياته بحُب."},
    {"section": "hero", "key": "hero.cta_primary", "value": "ابدأ أول قصة لطفلك"},
    {"section": "hero", "key": "hero.cta_secondary", "value": "كيف تعمل غِراس؟"},
    {"section": "how", "key": "how.title", "value": "كيف تعمل غِراس؟"},
    {"section": "how", "key": "how.subtitle", "value": "ست خطوات بسيطة تفصلك عن قصة لن ينساها طفلك"},
    {"section": "how", "key": "how.step1.title", "value": "اختر الهدف"},
    {"section": "how", "key": "how.step1.desc", "value": "حدّد القيمة أو السلوك واذكر موقفاً حقيقياً"},
    {"section": "how", "key": "how.step2.title", "value": "أخبرنا عن طفلك"},
    {"section": "how", "key": "how.step2.desc", "value": "الاسم والعمر وصورة ليصبح بطلاً حقيقياً"},
    {"section": "how", "key": "how.step3.title", "value": "أضف الشخصيات"},
    {"section": "how", "key": "how.step3.desc", "value": "أم، أب، صديق... لتكتمل عائلة القصة"},
    {"section": "how", "key": "how.step4.title", "value": "خصّصها"},
    {"section": "how", "key": "how.step4.desc", "value": "أضف مفضّلات طفلك ليشعر أنها قصته"},
    {"section": "values", "key": "values.title", "value": "لماذا غِراس؟"},
    {"section": "values", "key": "values.items", "value": [
        {"icon": "heart", "title": "مصممة بحب", "desc": "كل تفصيلة تراعي قلب طفلك وبراءته"},
        {"icon": "shield", "title": "محتوى آمن", "desc": "نراجع كل قصة قبل توصيلها لطفلك"},
        {"icon": "sprout", "title": "تربية بالقصة", "desc": "القيم تُغرس بحنان لا بأمر"},
        {"icon": "sparkles", "title": "تجربة فريدة", "desc": "طفلك بطل القصة باسمه وملامحه"},
    ]},
    {"section": "footer", "key": "footer.tagline", "value": "نَغرِس القيَم بقِصصٍ بَطلُها طِفلُك"},
    {"section": "footer", "key": "footer.copyright", "value": "© غِراس ٢٠٢٦ — جميع الحقوق محفوظة"},
]

PROMPTS = [
    {
        "key": "story.generate.master",
        "title_ar": "برومبت توليد القصة الرئيسي",
        "description": "القالب المرجعي الذي ستعتمد عليه محركات التوليد مستقبلاً. يُبنى البرومبت الفعلي لكل طلب ديناميكياً من JSON.",
        "template": "يتم بناء البرومبت تلقائياً من البيانات المهيكلة للطلب. راجع ai_prompt_snapshot في كل طلب.",
        "variables": [],
    },
]

PLANS = [
    {"name_ar": "الباقة المجانية", "price": 0, "currency": "SAR", "story_limit": 1,
     "features": ["قصة مصوّرة واحدة", "ملف PDF", "مراجعة أساسية"], "sort_order": 1, "is_active": True},
    {"name_ar": "الباقة العائلية", "price": 99, "currency": "SAR", "story_limit": 10,
     "features": ["١٠ قصص شهرياً", "فيديو مع مؤثرات", "تخصيص كامل", "أولوية في التوليد"], "sort_order": 2, "is_active": True},
    {"name_ar": "الباقة المميزة", "price": 249, "currency": "SAR", "story_limit": 999,
     "features": ["قصص غير محدودة", "صوت احترافي", "شخصية مخصصة للطفل", "دعم مخصص"], "sort_order": 3, "is_active": True},
]

SETTINGS = [
    {"key": "free_tier.story_limit", "value": 1},
    {"key": "brand.primary_color", "value": "#87A96B"},
    {"key": "site.name", "value": "غِراس"},
    {"key": "site.tagline", "value": "نَغرِس القيَم بقِصصٍ بَطلُها طِفلُك"},
    {"key": "characters.max_count", "value": 3},
    {"key": "upload.max_mb", "value": 6},
]


async def seed_admin():
    email = os.environ.get("ADMIN_EMAIL", "admin@gheras.com")
    password = os.environ.get("ADMIN_PASSWORD", "Admin@1234")
    existing = await db.users.find_one({"email": email})
    if existing:
        return
    await db.users.insert_one({
        "id": str(uuid.uuid4()),
        "email": email,
        "full_name": "مدير غِراس",
        "hashed_password": hash_password(password),
        "role": UserRole.ADMIN.value,
        "is_active": True,
        "must_change_password": True,
        "created_at": _now(),
    })


async def seed_categories():
    if await db.categories.count_documents({}) > 0:
        return
    for c in CATEGORIES:
        cat_id = str(uuid.uuid4())
        await db.categories.insert_one({
            "id": cat_id, "slug": c["slug"], "name_ar": c["name_ar"],
            "description": c["description"], "icon": c["icon"], "color": c["color"],
            "sort_order": c["sort_order"], "is_active": True, "created_at": _now(),
        })
        for idx, sub in enumerate(c["subcategories"]):
            await db.subcategories.insert_one({
                "id": str(uuid.uuid4()), "category_id": cat_id, "name_ar": sub,
                "description": None, "sort_order": idx, "is_active": True, "created_at": _now(),
            })


async def seed_story_options():
    if await db.story_options.count_documents({}) > 0:
        return
    for kind, name_ar, value, sort in STORY_OPTIONS:
        await db.story_options.insert_one({
            "id": str(uuid.uuid4()), "kind": kind, "name_ar": name_ar, "value": value,
            "description": None, "icon": None, "sort_order": sort,
            "is_active": True, "is_hidden": False, "created_at": _now(),
        })


async def seed_content():
    for block in CONTENT_BLOCKS:
        await db.content.update_one(
            {"key": block["key"]},
            {"$setOnInsert": {**block, "updated_at": _now()}},
            upsert=True,
        )


async def seed_prompts():
    for p in PROMPTS:
        exists = await db.prompts.find_one({"key": p["key"]})
        if exists:
            continue
        await db.prompts.insert_one({
            "id": str(uuid.uuid4()), **p, "is_active": True,
            "created_at": _now(), "updated_at": _now(),
        })


async def seed_plans():
    if await db.plans.count_documents({}) > 0:
        return
    for p in PLANS:
        await db.plans.insert_one({"id": str(uuid.uuid4()), **p, "created_at": _now()})


async def seed_settings():
    for s in SETTINGS:
        await db.settings.update_one(
            {"key": s["key"]},
            {"$setOnInsert": {**s, "updated_at": _now()}},
            upsert=True,
        )


async def seed_prompt_templates():
    """Seed editable admin prompt templates — one default per stage.

    These templates can be edited later via /admin/prompts UI.
    Only inserts if no template exists for that stage; never overwrites.
    """
    seeds = await _build_prompt_template_seeds()
    for s in seeds:
        exists = await db.prompt_templates.find_one({"stage_key": s["stage_key"]})
        if exists:
            continue
        doc = {
            "id": str(uuid.uuid4()),
            "stage_key":     s["stage_key"],
            "name":          s["name"],
            "template_text": s["template_text"],
            "variables":     s["variables"],
            "notes":         s["notes"],
            "version":       1,
            "active":        True,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await db.prompt_templates.insert_one(doc)


async def _build_prompt_template_seeds():
    """Returns the canonical list of prompt template seeds — used by both the
    initial seeder and Phase N strict-2D migration."""
    from services.child_character_service import DEFAULT_PROMPT as CC_DEFAULT_PROMPT
    seeds = [
        {
            "stage_key": "child_character_i2i",
            "name": "Child Character (Phase N — strict 2D cartoon)",
            "template_text": CC_DEFAULT_PROMPT,
            "variables": [
                "child_name", "child_age", "child_gender",
                "art_direction", "palette", "lighting",
            ],
            "notes": "OpenAI gpt-image-1 identity-preserving prompt. "
                     "Variables are optional (default prompt does not use them).",
        },
        {
            "stage_key": "scenario_generation",
            "name": "Scenario Generation (GPT-5 default)",
            "template_text": (
                "You are a professional Arabic children's story planner. Produce 3 distinct "
                "scenario options in Arabic for a $child_age-year-old $child_gender named "
                "$child_name. Category: $goal_category. Sub-goal: $goal_subcategory. Context: "
                "$context. Story type: $story_type. Tone: $tone. Setting: $setting. Language: "
                "$language. Duration: $duration_label ($duration_seconds s, $scene_target scenes). "
                "Characters around the child: $characters_summary. Toy/object context: "
                "$toy_summary. Appearance notes: $child_appearance_notes. Hijab: $child_hijab. "
                "Favorites: $favorites_summary. Extra notes: $extra_notes.\n\n"
                "For each scenario return JSON with: title (Arabic), short_summary (Arabic, "
                "2-3 sentences), emotional_angle (Arabic), learning_goal (Arabic), "
                "visual_style_hint (English)."
            ),
            "variables": [
                "child_name", "child_age", "child_gender", "child_appearance_notes",
                "child_hijab", "goal_category", "goal_subcategory", "context",
                "story_type", "tone", "setting", "language", "voice",
                "favorites_summary", "characters_summary", "toy_summary",
                "duration_label", "duration_seconds", "scene_target", "extra_notes",
            ],
            "notes": "Default Arabic scenario generator prompt. Edit to change story angle style.",
        },
        {
            "stage_key": "production_planning",
            "name": "Production Planning (GPT-5.2 default)",
            "template_text": (
                "Produce the full Gheras mega-JSON for scenario $scenario_title "
                "(target scenes = $target_scene_count, duration ≈ $duration_seconds s). "
                "Include: production_plan with story_keywords + story_music_prompt + "
                "story_voice_prompt; per-scene video_prompt + voice_prompt + music_prompt + "
                "music_keywords + camera_motion_hint + estimated_duration_seconds; "
                "final scene MUST have ≥3 flowing sentences in narration_text and ≥2 in "
                "book_text and emotional closure. No duplicate scene texts. Character arcs: "
                "$arc_list. Child: $child_name ($child_age), appearance: "
                "$child_appearance_notes. Toy/object hint: $toy_summary. Follow the JSON "
                "schema from SYSTEM_MSG exactly. All prompts in English; narration/book in Arabic."
            ),
            "variables": [
                "scenario_title", "target_scene_count", "duration_seconds",
                "arc_list", "child_name", "child_age",
                "child_appearance_notes", "toy_summary",
            ],
            "notes": "Default production planning prompt. Edits override only the USER body; "
                     "the SYSTEM_MSG schema stays as-is.",
        },
        {
            "stage_key": "scene_image_generation",
            "name": "Scene Image Prompt (Phase N — strict 2D cartoon)",
            "template_text": (
                "STRICT STYLE — soft pastel 2D children's storybook illustration. "
                "Use a soft pastel 2D children's storybook style with warm colors, "
                "gentle shading, charming proportions, and a premium illustrated "
                "cartoon look. The result MUST feel clearly animated / illustrated, "
                "NOT photorealistic, NOT live-action, NOT semi-real human rendering, "
                "NOT 3D-CGI render, NOT a photo filter — suitable for ages 3-9. "
                "Use the SAME cartoon character identity already established in the "
                "child_character reference image (do NOT redesign the character — "
                "preserve face, hair, outfit, palette).\n\n"
                "Art direction: $art_direction. Palette: $palette. Lighting: warm "
                "golden-hour, soft. Scene: $scene_title. Visual: $visual_description. "
                "Child: $child_name, $child_age years old, $child_gender. Appearance: "
                "$child_appearance_notes. Hijab: $child_hijab. "
                "Characters in frame: $characters_in_scene. Extra characters visual "
                "hints: $extra_characters_visuals. Key objects: $key_objects. "
                "Toy/object reference: $toy_summary. Emotional tone: $emotional_tone. "
                "Camera/motion hint: $camera_motion_hint. Aspect 16:9.\n\n"
                "FORBIDDEN: photorealism, realistic skin texture, photographic depth-"
                "of-field, real-life human faces, uncanny realism, plastic 3D-render "
                "look. The illustrated world must stay coherent across all scenes."
            ),
            "variables": [
                "art_direction", "palette", "scene_title", "visual_description",
                "child_name", "child_age", "child_gender", "child_appearance_notes",
                "child_hijab", "characters_in_scene", "extra_characters_visuals",
                "key_objects", "toy_summary", "emotional_tone", "camera_motion_hint",
            ],
            "notes": "Phase N — strict cartoon 2D enforcement + character consistency. "
                     "Sent to fal.ai gemini-25-flash-image / Nano Banana when ref image "
                     "is provided.",
        },
        {
            "stage_key": "narration_generation",
            "name": "Narration / Voice (default)",
            "template_text": (
                "Narrate the following Arabic scene text with warmth, gentle pace, and "
                "clear diction suitable for a $child_age-year-old child. Emotional "
                "delivery: $emotional_tone. Pacing: $pacing. Voice style: $voice_style. "
                "Audio background mode for this story: $audio_background_mode. "
                "Adjust pacing slightly to: when audio_background_mode='music' keep a "
                "steady storytelling rhythm; when 'human_rhythm' shorten pauses and "
                "feel more like a parent reading aloud; when 'none' speak slower with "
                "longer pauses since there is no music or rhythm under the voice. "
                "Scene text:\n$narration_text"
            ),
            "variables": [
                "child_age", "emotional_tone", "pacing", "voice_style",
                "audio_background_mode", "narration_text",
            ],
            "notes": "Narration/voice generation prompt. Consumed when a real TTS executor is wired. "
                     "Honors order.data.audio_background.mode (music | human_rhythm | none).",
        },
        {
            "stage_key": "video_generation",
            "name": "Video per-scene (Phase N — strict 2D cartoon over fal.ai Kling)",
            "template_text": (
                "STRICT STYLE — preserve the soft pastel 2D children's storybook "
                "cartoon style of the input image. The output video clip MUST stay "
                "in 2D illustrated / animated style — do NOT morph into "
                "photorealism, do NOT add live-action faces, do NOT change the "
                "character identity, outfit, or scene composition. Keep the same "
                "cartoon character from the input frame consistent in face, hair, "
                "and outfit throughout the clip.\n\n"
                "Children's storybook scene $scene_index, $estimated_duration_seconds-"
                "second cinematic shot for ages 3-9. Subject: $scene_title. Visual: "
                "$visual_description. Camera/motion: $camera_motion_hint. Mood: "
                "$emotional_tone. Style: $art_direction, warm pastel tones, soft "
                "lighting, child-safe, no text overlay.\n\n"
                "Motion: gentle child-safe motion only — slow camera dolly/parallax, "
                "subtle character expression changes, ambient micro-motion (sparkles, "
                "leaves, fabric drift). Avoid fast cuts, harsh whips, action-movie "
                "motion, or realistic physical impact. Per-scene cue: $video_prompt.\n\n"
                "FORBIDDEN: photorealism, live-action, semi-real human rendering, "
                "3D-CGI photo realism, realistic skin pores, photographic lighting."
            ),
            "variables": [
                "estimated_duration_seconds", "scene_index", "scene_title",
                "visual_description", "camera_motion_hint", "emotional_tone",
                "art_direction", "toy_summary", "video_prompt",
            ],
            "notes": "Phase N — Used by fal.ai Kling adapter (I2V when scene image "
                     "exists, T2V fallback). Strict 2D cartoon style enforcement. "
                     "Edit freely; admin-overridable model from /admin/stage-control.",
        },
        {
            "stage_key": "music_generation",
            "name": "Music per-story (ElevenLabs Music)",
            "template_text": (
                "Background music for a children's story video, total length "
                "$estimated_total_duration_seconds seconds. "
                "Story value: $value_label. Theme keywords: $story_keywords. "
                "Emotional arc: $emotional_arc. "
                "Mode: $audio_background_mode. "
                "Style: warm, gentle, family-friendly, no vocals (when mode=music), "
                "vocal-percussion only (when mode=human_rhythm), "
                "low-mid dynamics so narration sits above the music in the mix."
            ),
            "variables": [
                "estimated_total_duration_seconds", "value_label",
                "story_keywords", "emotional_arc", "audio_background_mode",
            ],
            "notes": "Phase M — Used by ElevenLabs Music adapter (per-story). "
                     "Mode 'human_rhythm' is prompt-biased only (no native API support). "
                     "Mode 'none' skips this stage entirely.",
        },
        {
            "stage_key": "extra_character_i2i",
            "name": "Extra Character (Phase N — strict 2D cartoon, identity-preserving)",
            "template_text": (
                "STRICT STYLE — soft pastel 2D children's storybook cartoon. Convert "
                "the uploaded real photo into a clearly illustrated 2D cartoon "
                "character that matches the SAME visual world as the main child "
                "character. The result must NOT be photorealistic, NOT semi-real, "
                "NOT live-action — it must read instantly as a hand-drawn / digitally "
                "painted storybook character suitable for ages 3-9.\n\n"
                "This is a supporting character for a children's storybook "
                "($character_role). Apply the same storybook transformation rules "
                "used for the main child character so all characters share one "
                "consistent visual style: soft pastel colors, gentle shading, "
                "charming proportions, premium illustrated cartoon look.\n\n"
                "Identity preservation (mandatory): preserve recognizable identity "
                "from the source photo — face shape, hair, gender, age impression, "
                "skin tone, expression, outfit family. Respect hijab if present.\n\n"
                "Character name: $character_name. Type: $character_type. Visible "
                "details: $character_visual_description.\n\n"
                "Generate ONE single full-body standing version centered in frame, "
                "transparent background, clean PNG, expressive but simple, "
                "animation-ready, consistent palette: $palette, art_direction: "
                "$art_direction.\n\n"
                "FORBIDDEN: photorealism, live-action, realistic skin pores, "
                "real-life human rendering, 3D-CGI render, plastic doll look."
            ),
            "variables": [
                "character_name", "character_type", "character_role",
                "character_visual_description", "palette", "art_direction",
            ],
            "notes": "Phase N — strict 2D cartoon enforcement. The live "
                     "extra_characters_service currently reuses the "
                     "child_character_i2i template at runtime. Editing this "
                     "template lets admin diverge later without touching the child template.",
        },
        {
            "stage_key": "book_page_image_generation",
            "name": "Book Page Illustration (Phase N — strict 2D cartoon, scene-consistent)",
            "template_text": (
                "STRICT STYLE — soft pastel 2D children's storybook print "
                "illustration. Use the SAME identity, outfit, palette, and art "
                "direction as the corresponding scene image. The output MUST be a "
                "clearly illustrated 2D cartoon page — NOT photorealistic, NOT "
                "live-action, NOT semi-real human rendering, NOT 3D-CGI render. "
                "Preserve the cartoon character identity already established in "
                "the scene image (face, hair, outfit, palette).\n\n"
                "Page text (Arabic, will be overlaid or printed beside the "
                "illustration): $book_text. Page number: $page_number of "
                "$total_pages. Scene index: $scene_index. Scene title: "
                "$scene_title. Visual: $visual_description. Key objects: "
                "$key_objects. Background setting: $background_setting.\n\n"
                "Compose as a portrait-friendly print page (A5 landscape), "
                "generous negative space on the right for the Arabic text block, "
                "RTL-safe layout. Style: $art_direction, $palette, $lighting. "
                "Slightly more detailed than a video frame (print quality), "
                "soft pastel storybook 2D, warm child-friendly premium "
                "illustrated cartoon look.\n\n"
                "FORBIDDEN: photorealism, live-action, realistic skin texture, "
                "photographic depth-of-field, real-life human faces."
            ),
            "variables": [
                "book_text", "page_number", "total_pages", "scene_index", "scene_title",
                "visual_description", "key_objects", "background_setting",
                "art_direction", "palette", "lighting",
            ],
            "notes": "Phase N — strict 2D cartoon enforcement + scene-character "
                     "consistency. Today the pipeline reuses the corresponding "
                     "scene_image (provider=reused). This template is editable now "
                     "and consumed when the orchestrator switches to a dedicated pass.",
        },
        {
            "stage_key": "video_assembly",
            "name": "Video Assembly (ffmpeg, local, no LLM)",
            "template_text": (
                "[INFORMATIONAL — ffmpeg local binary, no LLM provider, no API cost]\n\n"
                "Cover (2s) + N scene clips back-to-back, 1280×720, H.264, "
                "audio_background_mode=$audio_background_mode "
                "(music | human_rhythm | none). Scene clip duration computed from "
                "narration word count at 2.2 WPS for Arabic. Output: MP4 in "
                "$output_dir. Audio mixing for music/human_rhythm is deferred until a "
                "real TTS+music pipeline is wired."
            ),
            "variables": ["audio_background_mode", "output_dir"],
            "notes": "ffmpeg is a local binary, not a provider. This template documents "
                     "the assembly settings for admin visibility — not used at runtime.",
        },
        {
            "stage_key": "pdf_assembly",
            "name": "PDF Assembly (reportlab, local, no LLM)",
            "template_text": (
                "[INFORMATIONAL — reportlab local, no LLM provider, no API cost]\n\n"
                "A5 landscape, Arabic RTL. Cover page (cover_image + title) → per-scene "
                "pages (illustration on one half, RTL Arabic text on the other) → back "
                "page with main_message. Font: Amiri (loaded from "
                "/app/backend/fonts/Amiri-Regular.ttf). Arabic shaping via "
                "arabic-reshaper + python-bidi. Output: PDF in $output_dir."
            ),
            "variables": ["output_dir"],
            "notes": "reportlab local. This template documents the layout choices for "
                     "admin visibility — not consumed at runtime.",
        },
    ]
    return seeds


async def seed_all():
    await seed_admin()
    await seed_categories()
    await seed_story_options()
    await seed_content()
    await seed_prompts()
    await seed_plans()
    await seed_settings()
    await seed_prompt_templates()
    # Wave 3 — default bundles (only inserted on a virgin install).
    try:
        from services.bundle_service import seed_default_bundles
        await seed_default_bundles()
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger("seed").warning(f"bundle seed failed: {e}")
