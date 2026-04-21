"""Production planning service — Claude Sonnet 4.5 primary, deterministic fallback.

One mega-JSON call that produces: production_plan + scene_plans + book_pages + character_profiles.
"""
import os
import json
import logging
import uuid
from datetime import datetime, timezone

from emergentintegrations.llm.chat import LlmChat, UserMessage
from models import ARC_TEMPLATES

logger = logging.getLogger("production_service")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MODEL_PROVIDER = "anthropic"
MODEL_NAME = "claude-sonnet-4-5-20250929"


SYSTEM_MSG = """أنت مدير إنتاج قصص أطفال عربية محترف. مهمتك إنتاج **خطة إنتاج كاملة** لقصة مختارة، تتضمّن:

1. خطة عامة (production_plan)
2. مشاهد مُفصّلة (scenes) — عددها يساوي exactly target_scene_count
3. صفحات كتاب (book_pages) — صفحة لكل مشهد
4. ملفات شخصيات (character_profiles) — للطفل وكل الشخصيات البارزة

## القواعد الأساسية
- النصوص الموجّهة للقراءة/الصوت: **بالعربية** (narration_text, book_text, story_summary...).
- برومبتات الصور/الأنيميشن: **بالإنجليزية** (image_prompt_text, animation start/end, style_reference, visual_description). انقل أسماء الأطفال صوتياً (مثل Yusuf, Sara).
- لا عنف، لا أذى، لا خوف مفرط. النهاية دائماً إيجابية.
- consistency: استخدم نفس style_guide في كل المشاهد. نفس أوصاف الشخصيات في كل مرة.
- الطفل يظهر **بوجهه ومظهره الثابت** في كل مشهد. أشر إليه دائماً بـ "the child Yusuf (same appearance as reference image)".

## الـ arc_beats المستخدمة
سيصلك arc_template مرتّب. ألصق كل scene بالـ arc_beat المقابل لها بالترتيب.

## صيغة JSON المطلوبة (أرجع JSON فقط، بدون أي نص آخر)

{
  "production_plan": {
    "title": "عنوان عربي قصير للقصة الكاملة",
    "story_summary": "ملخص عربي 4-6 أسطر",
    "main_message": "الرسالة التربوية الواحدة المركزية",
    "emotional_arc": "وصف انجليزي قصير للمنحنى العاطفي (1-2 lines EN)",
    "style_guide": {
      "palette": "English palette description (e.g. warm earth tones with soft golden highlights)",
      "lighting": "English lighting description",
      "art_direction": "English art direction (e.g. whimsical watercolor illustration, soft edges, Pixar-like warmth)"
    },
    "cover_prompt": "English prompt for the book cover illustration — include child's name transliterated, mood, and visual anchor",
    "safety_check": "ok"
  },
  "characters": [
    {
      "type": "child|mother|father|sibling|friend|teacher|grandparent|other",
      "name": "Arabic name if any",
      "name_en": "Transliterated name",
      "visual_description": "English detailed appearance (face, hair, body type, eyes, skin tone)",
      "clothing_style": "English clothing",
      "key_features": "English 2-3 key memorable features",
      "reference_image_url": null
    }
  ],
  "scenes": [
    {
      "scene_index": 1,
      "arc_beat": "introduction",
      "title": "عنوان عربي قصير للمشهد",
      "scene_goal": "ماذا يحقّق هذا المشهد (عربي, سطر واحد)",
      "narration_text": "نص السرد كامل بالعربية للـ TTS (2-4 جمل متدفّقة، بدون علامات ترقيم مبالغ فيها)",
      "book_text": "نص الكتاب — أبسط من السرد، أقصر، مناسب لعمر الطفل (1-2 جملة بالعربية)",
      "emotional_tone": "English emotional tone descriptor (e.g. gentle curiosity, quiet tension, heartfelt warmth)",
      "visual_description": "English detailed visual description of what we see in this scene",
      "characters_in_scene": ["child", "mother"],
      "key_objects": ["red toy car", "cushion"],
      "background_setting": "English background description",
      "continuity_notes": "English notes for continuity with previous/next scene",
      "image_prompt": {
        "prompt_text": "Full English image generation prompt — MUST start with: 'Use the same child from the reference image.' Then describe the scene, environment, lighting, emotion, composition. Include style_guide art_direction keywords.",
        "style_reference": "Short English style tag matching production_plan.style_guide.art_direction",
        "character_reference_note": "Use the reference image of the child Yusuf exactly as provided. Preserve face, hair, and clothing consistency."
      },
      "animation_prompt": {
        "start_frame_description": "English description of the first frame",
        "end_frame_description": "English description of the last frame",
        "motion_hint": "English motion (e.g. slow zoom-in on child's face, gentle pan left across the room)",
        "camera_style": "English camera style (e.g. static handheld, smooth dolly-in, subtle parallax)"
      }
    }
  ],
  "book_pages": [
    {
      "page_number": 1,
      "scene_index": 1,
      "text": "نص الصفحة بالعربية المبسّطة — نفس روح book_text لكن يمكن أن يُعاد صياغته لجعله أكثر ملاءمة لصفحة الكتاب",
      "illustration_prompt": "English simplified version of the scene's image_prompt_text, suitable for a picture-book illustration"
    }
  ]
}

## قواعد صارمة
- عدد scenes = target_scene_count بالضبط.
- عدد book_pages = عدد scenes (1 لكل مشهد).
- characters: الطفل إلزامي (type=child). أضف أي شخصية بارزة ذُكرت في بيانات الطلب.
- characters_in_scene: استخدم type (child/mother/...) وليس name — سيتم ربطها داخلياً.
- visual_description، style_guide، prompts كلها بالإنجليزية.
- narration_text و book_text و scene_goal و title بالعربية.
- **كل مشهد يجب أن يحمل narration_text و book_text فريدين ومختلفين جذرياً عن المشاهد الأخرى** — لا تكرار! كل مشهد يمثّل بيت قصصي مختلف (مقدمة / مشكلة / تصعيد / لحظة تعلّم / حل / نهاية).
- اقرأ الـ arc_template واكتب محتوى يعكس كل arc_beat بدقة. التكرار يفسد القصة.
- safety_check: "ok" في الحالة الطبيعية. استخدم "review" فقط لو هناك موضوع حسّاس.
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _dedupe_scene_texts(scenes: list[dict]) -> None:
    """In-place: guarantee narration_text and book_text are unique per scene.

    If the LLM or fallback accidentally returns identical narration/book text
    across scenes, we prepend a scene marker so each scene stays distinct. We
    also log a warning so we can track how often it happens.
    """
    n_seen: dict[str, int] = {}
    b_seen: dict[str, int] = {}
    for s in scenes:
        idx = s.get("scene_index") or 0
        n = str(s.get("narration_text") or "").strip()
        if n and n in n_seen:
            logger.warning(f"Duplicate narration_text detected at scene {idx}; de-duplicating.")
            s["narration_text"] = f"(المشهد {idx}) {n}"
        else:
            n_seen[n] = idx
        b = str(s.get("book_text") or "").strip()
        if b and b in b_seen:
            logger.warning(f"Duplicate book_text detected at scene {idx}; de-duplicating.")
            s["book_text"] = f"{b} (صفحة {idx})"
        else:
            b_seen[b] = idx


def _build_user_prompt(order: dict, scenario: dict, target_scenes: int) -> str:
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    duration = order.get("duration", {}) or {}
    child = data.get("child", {}) or {}
    goal = data.get("goal", {}) or {}
    pers = data.get("personalization", {}) or {}
    chars = data.get("characters", []) or []
    audio_bg = (data.get("audio_background") or {}).get("mode") or "music"
    audio_bg_label = {
        "music": "موسيقى هادئة (gentle instrumental music)",
        "human_rhythm": "إيقاع صوتي بشري بدون موسيقى (vocal rhythm / nasheed style, no instruments)",
        "none": "بدون خلفية صوتية (narration only, no background track)",
    }.get(audio_bg, audio_bg)

    arc = ARC_TEMPLATES.get(target_scenes) or ARC_TEMPLATES[6]

    chars_brief = "\n".join(
        f"- {c.get('type')}{' (' + (c.get('name') or '') + ')' if c.get('name') else ''} — {c.get('role','mentioned')}"
        for c in chars
    ) or "لا يوجد"

    fav_brief = "، ".join(
        f"{k}: {(v or {}).get('name','')}"
        for k, v in (pers.get("favorites") or {}).items()
        if (v or {}).get("selected") and (v or {}).get("name")
    ) or "لا يوجد"

    return f"""## بيانات الطلب

**الطفل**: {child.get('name')} (اسم إنجليزي مقترح: {child.get('name','Child')})
- العمر: {child.get('age')} سنوات
- الجنس: {"ولد" if child.get('gender') == 'male' else "بنت"}{" — تظهر بالحجاب" if child.get('hijab') else ""}
- ملاحظات المظهر: {child.get('appearance_notes') or 'لم تُحدد'}
- reference_image_url: {child.get('image_url') or '—'}

**السيناريو المختار**:
- عنوان: {scenario.get('title')}
- ملخص: {scenario.get('short_summary')}
- زاوية: {scenario.get('emotional_angle')}
- هدف تعليمي: {scenario.get('learning_goal')}
- توجيه بصري: {scenario.get('visual_style_hint')}
- why_this_fits: {scenario.get('why_this_fits','')}

**الهدف التربوي**: {enriched.get('category_name')} / {enriched.get('subcategory_name') or goal.get('custom_subcategory') or '—'}
**الموقف الحقيقي**: {goal.get('context')}

**الأسلوب المطلوب**:
- نوع: {enriched.get('type_name') or 'غير محدد'}
- نبرة: {enriched.get('tone_name') or 'غير محدد'}
- بيئة: {enriched.get('setting_name') or 'غير محدد'}
- لغة: {enriched.get('language_name') or 'عربية فصحى مبسطة'}

**مدة الفيديو**: {duration.get('label')} ({duration.get('seconds')} ثانية)
**target_scene_count**: {target_scenes}
**arc_template (بالترتيب)**: {arc}
**الخلفية الصوتية المفضّلة**: {audio_bg_label}

**الشخصيات الإضافية**:
{chars_brief}

**مفضّلات الطفل**: {fav_brief}
**ملاحظات خاصة**: {pers.get('custom_notes') or 'لا يوجد'}

---

أنتج الخطة الكاملة كـ JSON واحد حسب الصيغة المطلوبة. **{target_scenes} scenes بالضبط**، ولكل مشهد arc_beat من القائمة أعلاه بالترتيب."""


from services.config_service import resolve_model, resolve_prompt


def _build_production_context(order: dict, scenario: dict, target_scenes: int) -> dict:
    """Flat variable context for admin-configurable production_planning prompt."""
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    duration = order.get("duration", {}) or {}
    child = data.get("child", {}) or {}
    goal = data.get("goal", {}) or {}
    pers = data.get("personalization", {}) or {}
    chars = data.get("characters", []) or []
    audio_bg = (data.get("audio_background") or {}).get("mode") or "music"
    audio_bg_label = {
        "music": "موسيقى هادئة",
        "human_rhythm": "إيقاع صوتي بشري بدون موسيقى",
        "none": "بدون خلفية صوتية",
    }.get(audio_bg, audio_bg)

    arc = ARC_TEMPLATES.get(target_scenes) or ARC_TEMPLATES[6]

    chars_brief = "، ".join(
        f"{c.get('type','')}: {c.get('name','')}" for c in chars if c.get("name")
    ) or "لا يوجد"

    fav_brief = "، ".join(
        f"{k}: {(v or {}).get('name','')}"
        for k, v in (pers.get("favorites") or {}).items()
        if (v or {}).get("selected") and (v or {}).get("name")
    ) or "لا يوجد"

    return {
        # Child
        "child_name":         child.get("name", ""),
        "child_age":          child.get("age", ""),
        "child_gender":       "ولد" if child.get("gender") == "male" else "بنت",
        # Selected scenario
        "selected_scenario_title":           scenario.get("title", ""),
        "selected_scenario_summary":         scenario.get("short_summary", ""),
        "selected_scenario_learning_goal":   scenario.get("learning_goal", ""),
        "selected_scenario_emotional_angle": scenario.get("emotional_angle", ""),
        "selected_scenario_visual_style":    scenario.get("visual_style_hint", ""),
        # Goal
        "goal_category":      enriched.get("category_name", ""),
        "goal_subcategory":   enriched.get("subcategory_name") or goal.get("custom_subcategory", ""),
        "context":            goal.get("context", ""),
        # Style
        "story_type":         enriched.get("type_name", "") or "غير محدد",
        "tone":               enriched.get("tone_name", "") or "غير محدد",
        "setting":            enriched.get("setting_name", "") or "غير محدد",
        "language":           enriched.get("language_name", "") or "عربية فصحى مبسطة",
        "voice":              enriched.get("voice_name", "") or "غير محدد",
        # Duration
        "duration_label":     duration.get("label", ""),
        "duration_seconds":   duration.get("seconds", ""),
        "scene_target":       target_scenes,
        "arc_beats_csv":      ", ".join(arc),
        # Extras
        "favorites_summary":  fav_brief,
        "characters_summary": chars_brief,
        "extra_notes":        pers.get("custom_notes", "") or "لا يوجد",
        "audio_background_mode": audio_bg_label,
    }


async def _generate_via_claude(order: dict, scenario: dict, target_scenes: int) -> dict:
    if not EMERGENT_LLM_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY missing")
    session_id = f"production-{order.get('id', uuid.uuid4())}-{uuid.uuid4().hex[:6]}"
    provider, model_name, model_src = await resolve_model(
        "production_planning", MODEL_PROVIDER, MODEL_NAME
    )
    logger.info(f"[config] stage=production_planning source={model_src} model={provider}/{model_name}")

    # Prompt: admin template if it renders cleanly, else hardcoded fallback.
    ctx = _build_production_context(order, scenario, target_scenes)
    admin_prompt, prompt_src, reason = await resolve_prompt("production_planning", ctx)
    if prompt_src == "admin":
        logger.info(f"[config] stage=production_planning prompt_source=admin {reason}")
        prompt = admin_prompt
    else:
        logger.info(f"[config] stage=production_planning prompt_source=default reason={reason}")
        prompt = _build_user_prompt(order, scenario, target_scenes)

    chat = (
        LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=SYSTEM_MSG)
        .with_model(provider, model_name)
    )
    response = await chat.send_message(UserMessage(text=prompt))
    text = (response or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in Claude response")
    payload = json.loads(text[start : end + 1])
    # Minimal validation
    if "production_plan" not in payload or "scenes" not in payload:
        raise ValueError("Missing required top-level keys")
    if len(payload.get("scenes", [])) != target_scenes:
        raise ValueError(f"Expected {target_scenes} scenes, got {len(payload.get('scenes', []))}")
    return payload


def _fallback_payload(order: dict, scenario: dict, target_scenes: int) -> dict:
    """Deterministic minimal plan. Used if Claude fails — preserves UX continuity."""
    data = order.get("data", {}) or {}
    duration = order.get("duration", {}) or {}
    child = data.get("child", {}) or {}
    chars = data.get("characters", []) or []
    name_ar = child.get("name") or "بطلنا"
    name_en = name_ar  # transliteration not attempted here
    arc = ARC_TEMPLATES.get(target_scenes) or ARC_TEMPLATES[6]
    learning = scenario.get("learning_goal") or "قيمة جميلة"
    summary = scenario.get("short_summary") or ""

    style_guide = {
        "palette": "warm earth tones with soft golden highlights",
        "lighting": "gentle natural lighting, soft shadows",
        "art_direction": "whimsical watercolor illustration, soft edges, Pixar-like warmth",
    }

    characters_out = [{
        "type": "child",
        "name": name_ar,
        "name_en": name_en,
        "visual_description": (
            f"A {child.get('age','5')}-year-old {'boy' if child.get('gender')=='male' else 'girl'} "
            f"with kind eyes, warm skin tone, styled hair. "
            + (child.get('appearance_notes') or "")
        ).strip(),
        "clothing_style": "comfortable everyday clothes, simple colors",
        "key_features": "expressive eyes, gentle smile, natural posture",
        "reference_image_url": child.get("image_url"),
    }]
    for c in chars:
        characters_out.append({
            "type": c.get("type"),
            "name": c.get("name"),
            "name_en": c.get("name"),
            "visual_description": f"A {c.get('type')} of {name_en}, warm and caring appearance",
            "clothing_style": "traditional modest clothing",
            "key_features": f"kind face, supportive presence for {name_en}",
            "reference_image_url": c.get("image_url"),
        })

    scenes_out = []
    book_pages_out = []
    beat_to_ar = {
        "setup": "المشهد التمهيدي",
        "introduction": "البداية",
        "problem": "تظهر المشكلة",
        "turning_point": "لحظة التحوّل",
        "escalation": "تتصاعد الأمور",
        "escalation_1": "تتصاعد الأمور",
        "escalation_2": "ذروة التصعيد",
        "climax": "اللحظة الحاسمة",
        "resolution": "الحل",
        "reflection": "لحظة التأمّل",
        "positive_ending": "النهاية الجميلة",
    }

    # Per-beat unique narration + book text snippets (Arabic) so fallback
    # never returns duplicate content across scenes.
    beat_narration = {
        "setup":            f"في بدايتنا نلتقي بـ{name_ar} في عالمه المألوف، والأجواء هادئة.",
        "introduction":     f"يخطو {name_ar} أول خطواته في رحلة جديدة تفتح قلبه للتعلّم.",
        "problem":          f"فجأة يُواجه {name_ar} موقفاً صعباً يحتاج إلى التفكير بهدوء.",
        "turning_point":    f"يتوقف {name_ar} للحظة ويبدأ في رؤية الأمر من زاوية جديدة.",
        "escalation":       f"تتعقد الأمور حول {name_ar} ويحاول إيجاد طريقة أفضل للتعامل.",
        "escalation_1":     f"يجرّب {name_ar} حلاً ويكتشف أن الأمر يحتاج إلى صبر أكبر.",
        "escalation_2":     f"تزداد التحديات وتختبر {name_ar} في لحظات مهمة.",
        "climax":           f"تأتي اللحظة الفاصلة حيث يتخذ {name_ar} قراره الشجاع.",
        "resolution":       f"يجد {name_ar} أخيراً الطريق الصحيح ويشعر بالارتياح.",
        "reflection":       f"يتأمّل {name_ar} ما تعلّمه اليوم ويبتسم للقيمة الجميلة.",
        "positive_ending":  f"تنتهي الرحلة بابتسامة دافئة لـ{name_ar} وقلب مليء بالفخر.",
    }
    beat_book = {
        "setup":            f"هذا {name_ar}، يعيش يوماً جميلاً.",
        "introduction":     f"بدأ {name_ar} يوماً مليئاً بالمفاجآت.",
        "problem":          f"واجه {name_ar} مشكلة صغيرة.",
        "turning_point":    f"فكّر {name_ar} قليلاً وابتسم.",
        "escalation":       f"حاول {name_ar} أن يجد حلاً.",
        "escalation_1":     f"جرّب {name_ar} طريقة جديدة.",
        "escalation_2":     f"لم يستسلم {name_ar} أبداً.",
        "climax":           f"اختار {name_ar} أن يكون شجاعاً.",
        "resolution":       f"وجد {name_ar} الحلّ الصحيح.",
        "reflection":       f"تعلّم {name_ar} عن {learning}.",
        "positive_ending":  f"فرح {name_ar} وابتسم بفخر.",
    }
    # Per-beat visual descriptor (English) for image prompts.
    beat_visual = {
        "setup":            "in a calm home setting, soft morning light, relaxed pose",
        "introduction":     "stepping outside into a warm, inviting environment, curious expression",
        "problem":          "noticing a small challenge ahead, thoughtful expression",
        "turning_point":    "pausing mid-action, eyes widening with realization",
        "escalation":       "actively trying to solve a growing problem, focused expression",
        "escalation_1":     "attempting a new approach with determination",
        "escalation_2":     "facing a harder challenge, breathing in deeply",
        "climax":           "standing tall, making a brave decision, golden backlight",
        "resolution":       "smiling gently, relieved shoulders, warm soft lighting",
        "reflection":       "sitting peacefully, looking up with a proud smile",
        "positive_ending":  "hugging a loved one, surrounded by warm sunset hues",
    }

    scenes_out = []
    book_pages_out = []
    for i, beat in enumerate(arc, start=1):
        title_ar = f"{beat_to_ar.get(beat, 'مشهد')} — {name_ar}"
        narration_ar = beat_narration.get(beat, f"مشهد {i} من قصة {name_ar}.")
        # Add beat+index suffix so even if beats repeat, texts differ.
        if arc.count(beat) > 1:
            narration_ar = f"[{i}] {narration_ar}"
        book_ar = beat_book.get(beat, f"{name_ar} يعيش لحظة جميلة.")
        if arc.count(beat) > 1:
            book_ar = f"{book_ar} (لحظة {i})"
        visual_ar = beat_visual.get(beat, f"{name_en} in a meaningful moment")
        scene = {
            "scene_index": i,
            "arc_beat": beat,
            "title": title_ar,
            "scene_goal": f"مشهد رقم {i}: إظهار {beat_to_ar.get(beat, beat)} بشكل يناسب عمر الطفل",
            "narration_text": narration_ar,
            "book_text": book_ar,
            "emotional_tone": "gentle and warm",
            "visual_description": f"{name_en} {visual_ar}",
            "characters_in_scene": ["child"] + [c.get("type") for c in chars[:1]],
            "key_objects": [],
            "background_setting": "warm, familiar home environment with soft natural light",
            "continuity_notes": f"Maintain {name_en}'s appearance and outfit consistent with previous scenes",
            "image_prompt": {
                "prompt_text": (
                    f"Use the same child from the reference image. Scene {i} of {len(arc)}: "
                    f"{name_en}, a {child.get('age','5')}-year-old "
                    f"{'boy' if child.get('gender')=='male' else 'girl'}, {visual_ar}. "
                    f"Warm earth tones, soft golden lighting, whimsical watercolor illustration. "
                    f"Storybook composition, aspect 16:9."
                ),
                "style_reference": style_guide["art_direction"],
                "character_reference_note": f"Use the reference image of {name_en} exactly as provided. Preserve face, hair, and clothing across all {len(arc)} scenes.",
            },
            "animation_prompt": {
                "start_frame_description": f"Scene {i} start: {name_en} — {visual_ar}",
                "end_frame_description":   f"Scene {i} end: {name_en} reacts to the moment in an age-appropriate way.",
                "motion_hint": "gentle slow zoom-in, subtle parallax",
                "camera_style": "smooth static with soft dolly-in",
            },
        }
        scenes_out.append(scene)
        book_pages_out.append({
            "page_number": i,
            "scene_index": i,
            "text": book_ar,
            "illustration_prompt": (
                f"Use the reference image of {name_en}. Page {i}: simple picture-book illustration of {name_en} {visual_ar}, "
                f"warm earth tones, whimsical watercolor style."
            ),
        })

    return {
        "production_plan": {
            "title": scenario.get("title") or f"قصة {name_ar}",
            "story_summary": summary or f"رحلة {name_ar} لاكتشاف معنى {learning}.",
            "main_message": scenario.get("learning_goal") or learning,
            "emotional_arc": f"From quiet curiosity to heartfelt understanding over {duration.get('label','the story')}.",
            "style_guide": style_guide,
            "cover_prompt": (
                f"Use the reference image of {name_en}. Book cover illustration showing {name_en} "
                f"smiling warmly, golden hour lighting, whimsical watercolor style, title space at the top."
            ),
            "safety_check": "ok",
        },
        "characters": characters_out,
        "scenes": scenes_out,
        "book_pages": book_pages_out,
    }


async def generate_production_plan(order: dict, scenario: dict, target_scenes: int) -> tuple[dict, str, str | None]:
    try:
        return (await _generate_via_claude(order, scenario, target_scenes), "ai", None)
    except Exception as e:
        logger.warning(f"Claude production plan failed, using fallback: {e}")
        return (_fallback_payload(order, scenario, target_scenes), "fallback", str(e))


def build_docs(order: dict, payload: dict, run_id: str, source: str) -> dict:
    """Convert LLM JSON into DB-ready documents. Returns {plan, scenes, book_pages, character_profiles}."""
    order_id = order["id"]
    now = _now()
    plan_payload = payload.get("production_plan", {}) or {}
    plan_id = str(uuid.uuid4())

    # characters
    character_profiles = []
    type_to_id: dict[str, str] = {}
    for c in payload.get("characters", []) or []:
        cid = str(uuid.uuid4())
        t = c.get("type") or "other"
        type_to_id.setdefault(t, cid)  # first match wins for type → id lookup
        character_profiles.append({
            "id": cid,
            "order_id": order_id,
            "production_plan_id": plan_id,
            "run_id": run_id,
            "type": t,
            "name": c.get("name"),
            "name_en": c.get("name_en"),
            "visual_description": c.get("visual_description", ""),
            "clothing_style": c.get("clothing_style", ""),
            "key_features": c.get("key_features", ""),
            "reference_image_url": c.get("reference_image_url"),
            "is_archived": False,
            "created_at": now,
        })

    # Ensure child exists (even if LLM missed)
    if "child" not in type_to_id:
        cid = str(uuid.uuid4())
        type_to_id["child"] = cid
        character_profiles.insert(0, {
            "id": cid,
            "order_id": order_id,
            "production_plan_id": plan_id,
            "run_id": run_id,
            "type": "child",
            "name": None,
            "name_en": None,
            "visual_description": "",
            "clothing_style": "",
            "key_features": "",
            "reference_image_url": None,
            "is_archived": False,
            "created_at": now,
        })

    # scenes + book pages
    scenes: list[dict] = []
    words_total = 0
    for s in payload.get("scenes", []) or []:
        sid = str(uuid.uuid4())
        img = s.get("image_prompt") or {}
        anim = s.get("animation_prompt") or {}
        chars_in = []
        for t in s.get("characters_in_scene", []) or []:
            cpid = type_to_id.get(t)
            chars_in.append({"character_profile_id": cpid, "role_in_scene": t})
        narration = str(s.get("narration_text") or "").strip()
        wc = len([w for w in narration.split() if w])
        words_total += wc
        scenes.append({
            "id": sid,
            "order_id": order_id,
            "production_plan_id": plan_id,
            "run_id": run_id,
            "scene_index": int(s.get("scene_index") or (len(scenes) + 1)),
            "arc_beat": s.get("arc_beat"),
            "title": s.get("title"),
            "scene_goal": s.get("scene_goal"),
            "narration_text": narration,
            "book_text": s.get("book_text"),
            "emotional_tone": s.get("emotional_tone"),
            "visual_description": s.get("visual_description"),
            "characters_in_scene": chars_in,
            "key_objects": s.get("key_objects", []) or [],
            "background_setting": s.get("background_setting"),
            "continuity_notes": s.get("continuity_notes"),
            "image_prompt": {
                "prompt_text": img.get("prompt_text", ""),
                "style_reference": img.get("style_reference", ""),
                "character_reference_note": img.get("character_reference_note", ""),
            },
            "animation_prompt": {
                "start_frame_description": anim.get("start_frame_description", ""),
                "end_frame_description": anim.get("end_frame_description", ""),
                "motion_hint": anim.get("motion_hint", ""),
                "camera_style": anim.get("camera_style", ""),
            },
            "word_count": wc,
            "is_archived": False,
            "created_at": now,
        })

    # Sanity: ensure no duplicate narration/book texts between scenes.
    # If the LLM (or fallback) emitted duplicates for any reason, we append a
    # uniqueness marker so every scene tells its own micro-beat.
    _dedupe_scene_texts(scenes)

    book_pages: list[dict] = []
    # Map scene_index → scene.id for scene_reference
    idx_to_scene_id = {s["scene_index"]: s["id"] for s in scenes}
    for p in payload.get("book_pages", []) or []:
        idx = int(p.get("scene_index") or p.get("page_number") or (len(book_pages) + 1))
        book_pages.append({
            "id": str(uuid.uuid4()),
            "order_id": order_id,
            "production_plan_id": plan_id,
            "run_id": run_id,
            "page_number": int(p.get("page_number") or (len(book_pages) + 1)),
            "scene_index": idx,
            "scene_reference": idx_to_scene_id.get(idx),
            "text": p.get("text"),
            "illustration_prompt": p.get("illustration_prompt"),
            "is_archived": False,
            "created_at": now,
        })

    # plan
    data = order.get("data") or {}
    audio_bg_mode = (data.get("audio_background") or {}).get("mode") or "music"
    plan = {
        "id": plan_id,
        "order_id": order_id,
        "run_id": run_id,
        "source": source,
        "is_archived": False,
        "title": plan_payload.get("title"),
        "story_summary": plan_payload.get("story_summary"),
        "main_message": plan_payload.get("main_message"),
        "emotional_arc": plan_payload.get("emotional_arc"),
        "style_guide": plan_payload.get("style_guide") or {},
        "cover_prompt": plan_payload.get("cover_prompt"),
        "safety_check": plan_payload.get("safety_check") or "ok",
        "target_scene_count": len(scenes),
        "estimated_image_count": len(scenes) + 1,  # +1 for the cover
        "total_word_count": words_total,
        "duration_seconds": (order.get("duration") or {}).get("seconds"),
        "duration_label": (order.get("duration") or {}).get("label"),
        "tone": (order.get("enriched") or {}).get("tone_name"),
        "setting": (order.get("enriched") or {}).get("setting_name"),
        "language": (order.get("enriched") or {}).get("language_name"),
        "audio_background": {"mode": audio_bg_mode},
        "ai_plan_snapshot_json": json.dumps(payload, ensure_ascii=False),
        "created_at": now,
    }

    return {
        "plan": plan,
        "scenes": scenes,
        "book_pages": book_pages,
        "character_profiles": character_profiles,
    }
