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


async def seed_all():
    await seed_admin()
    await seed_categories()
    await seed_story_options()
    await seed_content()
    await seed_prompts()
    await seed_plans()
    await seed_settings()
