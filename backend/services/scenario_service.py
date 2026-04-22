"""Scenario generation service — Claude Sonnet 4.5 primary, deterministic fallback."""
import os
import json
import logging
import uuid
from datetime import datetime, timezone

from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger("scenario_service")

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
MODEL_PROVIDER = "anthropic"
MODEL_NAME = "claude-sonnet-4-5-20250929"

SYSTEM_MSG = """أنت كاتب قصص أطفال عربية محترف. مهمتك إنشاء 3 سيناريوهات قصيرة متنوعة ومميزة لكل طلب.

كل سيناريو يجب أن يكون مختلفاً جذرياً في الزاوية العاطفية والنبرة، لكن جميعها تحقق نفس الهدف التربوي وتناسب عمر الطفل.

النبرات الثلاث المستهدفة:
1. عاطفي - يلامس القلب ويبني الذكاء العاطفي
2. تعليمي/هادئ - يوضّح الدرس بهدوء وتأمّل
3. مغامرة/تشويق - يستخدم الإثارة لتوصيل القيمة

أرجع الإجابة كـ JSON فقط (بدون أي نص إضافي) بالصيغة التالية تماماً:
{
  "scenarios": [
    {
      "title": "عنوان قصير جذاب",
      "short_summary": "ملخص من 2-4 سطور يصف القصة باختصار واضح",
      "emotional_angle": "emotional|educational|adventure",
      "learning_goal": "الرسالة/القيمة التي ستُغرس",
      "visual_style_hint": "توجيه بصري للفنان (لون، جو، مشهد مفتاحي)",
      "estimated_scene_count": 5,
      "why_this_fits": "سطر أو سطران يشرحان بالضبط لماذا هذا السيناريو مناسب لهذا الطفل بالتحديد، مستنداً إلى الموقف الذي عاشه وعمره ومفضلاته"
    },
    ...
  ]
}

قواعد صارمة:
- 3 سيناريوهات بالضبط
- emotional_angle يجب أن يكون حرفياً واحداً من: emotional / educational / adventure
- العنوان ≤ 8 كلمات
- short_summary ≤ 4 سطور بالعربية
- why_this_fits حقل إلزامي — 1-2 سطر يربط القصة بتفاصيل الطفل الفعلية
- كل سيناريوهين مختلفان في الحبكة وليس فقط في الصياغة"""


TONES = ["emotional", "educational", "adventure"]
TONE_LABEL_AR = {
    "emotional": "عاطفي",
    "educational": "تعليمي هادئ",
    "adventure": "مغامرة مشوّقة",
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _user_prompt(order: dict) -> str:
    """Concise structured brief for the model."""
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    child = data.get("child", {}) or {}
    goal = data.get("goal", {}) or {}
    pers = data.get("personalization", {}) or {}
    dur = order.get("duration") or {}
    scene_target = dur.get("scene_target") or 5
    duration_label = dur.get("label") or "دقيقة ونصف"

    chars = data.get("characters", []) or []
    chars_brief = "، ".join(
        f"{c.get('type','')}"
        + (f" ({c.get('name')})" if c.get("name") else "")
        + (" — ظاهر" if c.get("role") == "visible" else "")
        for c in chars
    ) or "لا يوجد"

    fav_brief = "، ".join(
        f"{k}: {(v or {}).get('name','')}"
        for k, v in (pers.get("favorites") or {}).items()
        if (v or {}).get("selected") and (v or {}).get("name")
    ) or "لا يوجد"

    return f"""بيانات الطلب:

الطفل: {child.get('name','')} — عمر {child.get('age','')} — {"ولد" if child.get('gender')=='male' else "بنت"}{"(بحجاب)" if child.get('hijab') else ""}
التصنيف: {enriched.get('category_name','')}
الموضوع: {enriched.get('subcategory_name') or goal.get('custom_subcategory','')}
الموقف الحقيقي: {goal.get('context','')}
الشخصيات الإضافية: {chars_brief}
مفضّلات: {fav_brief}
تفاصيل إضافية: {pers.get('custom_notes','') or 'لا يوجد'}

الأسلوب المطلوب:
- نوع: {enriched.get('type_name','') or 'غير محدد'}
- نبرة عامة: {enriched.get('tone_name','') or 'غير محدد'}
- بيئة: {enriched.get('setting_name','') or 'غير محدد'}
- لغة: {enriched.get('language_name','') or 'عربية فصحى مبسطة'}

المدة المطلوبة للفيديو: {duration_label} — اجعل estimated_scene_count قريباً من {scene_target} (±1).

أنشئ الآن 3 سيناريوهات متنوعة حسب القواعد."""


def _clamp_scene_count(requested: int, target: int) -> int:
    """Keep estimated_scene_count within target ±1, bounded to [3, 10]."""
    lo = max(3, target - 1)
    hi = min(10, target + 1)
    try:
        r = int(requested)
    except (TypeError, ValueError):
        r = target
    return max(lo, min(hi, r))


from services.config_service import resolve_model, resolve_prompt, resolve_transport
from services.llm_direct import direct_openai_chat


def _build_scenario_context(order: dict) -> dict:
    """Build the flat variable context used to render admin prompt templates.

    Keys are stable identifiers (snake_case, ASCII) that admins can reference
    as ${var} inside a template. Defaults are empty strings instead of None so
    rendering never trips on a missing attribute.
    """
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    child = data.get("child", {}) or {}
    goal = data.get("goal", {}) or {}
    pers = data.get("personalization", {}) or {}
    duration = order.get("duration") or {}

    fav = pers.get("favorites") or {}
    fav_brief = "، ".join(
        f"{k}: {(v or {}).get('name','')}"
        for k, v in fav.items()
        if (v or {}).get("selected") and (v or {}).get("name")
    ) or "لا يوجد"

    chars = data.get("characters") or []
    # Build a rich character brief that includes visual descriptions when available.
    def _char_line(c):
        bits = [f"{c.get('type','')}: {c.get('name','')}"]
        if c.get("role"):
            bits.append(f"role={c['role']}")
        if c.get("visual_description_auto"):
            bits.append(f"visuals: {c['visual_description_auto']}")
        return " | ".join(bits)
    chars_brief = "\n- ".join(_char_line(c) for c in chars if c.get("name")) or "لا يوجد"
    if chars_brief != "لا يوجد":
        chars_brief = "- " + chars_brief

    # Toy/object description (from vision_describe, if available).
    toy_desc = pers.get("toy_description_auto") or ""
    toy_name = ((fav or {}).get("toy") or {}).get("name") or ""
    toy_brief = ""
    if toy_name or toy_desc:
        toy_brief = (f"اسم اللعبة: {toy_name}. " if toy_name else "") + \
                    (f"الوصف البصري: {toy_desc}" if toy_desc else "")
    toy_brief = toy_brief or "لا يوجد"

    return {
        "child_name":         child.get("name", ""),
        "child_age":          child.get("age", ""),
        "child_gender":       "ولد" if child.get("gender") == "male" else "بنت",
        "child_appearance_notes": child.get("appearance_notes", "") or "لا يوجد",
        "child_hijab":        "نعم" if child.get("hijab") else "لا",
        "goal_category":      enriched.get("category_name", ""),
        "goal_subcategory":   enriched.get("subcategory_name") or goal.get("custom_subcategory", ""),
        "context":            goal.get("context", ""),
        "story_type":         enriched.get("type_name", "") or "غير محدد",
        "tone":               enriched.get("tone_name", "") or "غير محدد",
        "setting":            enriched.get("setting_name", "") or "غير محدد",
        "language":           enriched.get("language_name", "") or "عربية فصحى مبسطة",
        "voice":              enriched.get("voice_name", "") or "غير محدد",
        "favorites_summary":  fav_brief,
        "characters_summary": chars_brief,
        "toy_summary":        toy_brief,
        "duration_label":     duration.get("label", ""),
        "duration_seconds":   duration.get("seconds", ""),
        "scene_target":       duration.get("scene_target", 5),
        "extra_notes":        pers.get("custom_notes", "") or "لا يوجد",
    }


async def _generate_via_claude(order: dict) -> list[dict]:
    """Try Claude Sonnet 4.5. Raises on any failure."""
    if not EMERGENT_LLM_KEY:
        raise RuntimeError("EMERGENT_LLM_KEY missing")
    session_id = f"scenarios-{order.get('id', uuid.uuid4())}"
    provider, model_name, model_src = await resolve_model(
        "scenario_generation", MODEL_PROVIDER, MODEL_NAME
    )
    logger.info(f"[config] stage=scenario_generation source={model_src} model={provider}/{model_name}")

    # Resolve prompt: prefer admin template if it renders cleanly, else default.
    ctx = _build_scenario_context(order)
    admin_prompt, prompt_src, reason = await resolve_prompt("scenario_generation", ctx)
    if prompt_src == "admin":
        logger.info(f"[config] stage=scenario_generation prompt_source=admin {reason}")
        user_prompt_text = admin_prompt
    else:
        logger.info(f"[config] stage=scenario_generation prompt_source=default reason={reason}")
        user_prompt_text = _user_prompt(order)

    chat = (
        LlmChat(api_key=EMERGENT_LLM_KEY, session_id=session_id, system_message=SYSTEM_MSG)
        .with_model(provider, model_name)
    )

    # Transport selection — Phase D.2: direct OpenAI (billed to user's own
    # OPENAI_API_KEY) OR Emergent proxy (billed to EMERGENT_LLM_KEY). The
    # decision is a pure DB read; both paths produce the same string result
    # so all downstream parsing/fallback logic is untouched.
    transport = await resolve_transport("scenario_generation")
    logger.info(f"[config] stage=scenario_generation transport={transport}")
    if transport == "direct-openai":
        response = await direct_openai_chat(
            system_message=SYSTEM_MSG,
            user_message=user_prompt_text,
            model=model_name,
            timeout=90.0,
        )
    else:
        response = await chat.send_message(UserMessage(text=user_prompt_text))
    text = (response or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("No JSON object in response")
    payload = json.loads(text[start : end + 1])
    items = payload.get("scenarios") or []
    if len(items) != 3:
        raise ValueError(f"Expected 3 scenarios, got {len(items)}")
    scene_target = (order.get("duration") or {}).get("scene_target") or 5
    out = []
    for i, s in enumerate(items):
        angle = str(s.get("emotional_angle", "")).strip().lower()
        if angle not in TONES:
            angle = TONES[i % 3]
        out.append({
            "title": str(s.get("title") or "").strip()[:120] or f"سيناريو {i+1}",
            "short_summary": str(s.get("short_summary") or "").strip(),
            "emotional_angle": angle,
            "learning_goal": str(s.get("learning_goal") or "").strip(),
            "visual_style_hint": str(s.get("visual_style_hint") or "").strip(),
            "estimated_scene_count": _clamp_scene_count(s.get("estimated_scene_count"), scene_target),
            "why_this_fits": str(s.get("why_this_fits") or "").strip(),
        })
    return out


def _fallback_scenarios(order: dict) -> list[dict]:
    """Deterministic fallback — 3 distinct tones derived from order data."""
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    child = data.get("child", {}) or {}
    goal = data.get("goal", {}) or {}
    name = child.get("name", "بطلنا")
    age = child.get("age", 5)
    theme = enriched.get("subcategory_name") or goal.get("custom_subcategory") or enriched.get("category_name") or "قيمة جميلة"
    context_snip = (goal.get("context") or "").strip()
    context_line = context_snip[:80] + ("..." if len(context_snip) > 80 else "")
    scene_target = (order.get("duration") or {}).get("scene_target") or 5

    return [
        {
            "title": f"قلب {name} الكبير",
            "short_summary": (
                f"قصة دافئة تلامس مشاعر {name}، تبدأ من الموقف الذي عاشه "
                f"وتأخذه في رحلة هادئة لاكتشاف معنى {theme} من الداخل. "
                f"تنتهي بلحظة مؤثرة تجعل الدرس يصل للقلب قبل العقل."
            ),
            "emotional_angle": "emotional",
            "learning_goal": f"أن يفهم {name} قيمة {theme} بصدق مشاعره",
            "visual_style_hint": "ألوان دافئة خفيفة، إضاءة ذهبية، لقطات قريبة من الوجه لإبراز المشاعر",
            "estimated_scene_count": _clamp_scene_count(scene_target, scene_target),
            "why_this_fits": f"النبرة العاطفية تناسب {name} في عمر {age} وتربط مباشرة بمشاعره في الموقف الذي عاشه.",
        },
        {
            "title": f"{name} يكتشف الحكمة",
            "short_summary": (
                f"قصة هادئة بأسلوب تعليمي لطيف، يتعلم فيها {name} معنى {theme} "
                f"من شخصية حكيمة ولحظات بسيطة في حياته اليومية. "
                f"مناسبة جداً لعمر {age} سنوات وتترك أثراً واضحاً."
            ),
            "emotional_angle": "educational",
            "learning_goal": f"توضيح {theme} بأمثلة عملية يفهمها طفل بعمر {age}",
            "visual_style_hint": "ألوان هادئة، زوايا ثابتة، تركيز على التعابير والتفاصيل الصغيرة",
            "estimated_scene_count": _clamp_scene_count(scene_target, scene_target),
            "why_this_fits": f"الأسلوب التعليمي الهادئ مثالي لشرح {theme} بلغة مبسطة تناسب استيعاب طفل في عمر {age}.",
        },
        {
            "title": f"مغامرة {name} الكبرى",
            "short_summary": (
                f"مغامرة مشوّقة يخوض فيها {name} تحدياً ممتعاً يعلّمه {theme}. "
                f"أحداث سريعة وشخصيات مرحة ونهاية بطولية — بدون عنف ومناسبة للأطفال. "
                + (f"القصة تبدأ من موقف شبيه بالذي عاشه: {context_line}" if context_line else "")
            ),
            "emotional_angle": "adventure",
            "learning_goal": f"تعزيز {theme} عبر تجربة بطولية ممتعة",
            "visual_style_hint": "ألوان زاهية، حركة ديناميكية، لقطات واسعة لإبراز المغامرة",
            "estimated_scene_count": _clamp_scene_count(scene_target + 1, scene_target),
            "why_this_fits": f"المغامرة تجذب انتباه {name} وتحوّل الموقف الذي عاشه إلى تجربة بطولية ممتعة تترك أثر {theme} بشكل لا يُنسى.",
        },
    ]


async def generate_scenarios(order: dict) -> tuple[list[dict], str, str | None]:
    """Main entry. Returns (scenarios, source, error_message_if_any)."""
    # Phase D.3 — populate auto visual descriptions for uploaded toy/character
    # images on the FIRST AI-call path. Idempotent + never raises. The refreshed
    # order (with new data.*.*_description_auto fields) propagates downstream
    # to production_planning and scene_image_generation through the DB.
    try:
        from services.vision_describe import ensure_vision_descriptions
        order = await ensure_vision_descriptions(order)
    except Exception as e:  # noqa: BLE001 — must never block scenarios
        logger.warning(f"[vision_describe] non-fatal: {type(e).__name__}: {e}")
    try:
        items = await _generate_via_claude(order)
        return items, "ai", None
    except Exception as e:
        logger.warning(f"Claude scenario generation failed, using fallback: {e}")
        return _fallback_scenarios(order), "fallback", str(e)


def build_scenario_docs(order_id: str, items: list[dict], batch_id: str, source: str) -> list[dict]:
    now = _now()
    out = []
    for idx, s in enumerate(items, start=1):
        out.append({
            "id": str(uuid.uuid4()),
            "order_id": order_id,
            "scenario_batch_id": batch_id,
            "scenario_index": idx,
            "title": s["title"],
            "short_summary": s["short_summary"],
            "emotional_angle": s["emotional_angle"],
            "learning_goal": s["learning_goal"],
            "visual_style_hint": s["visual_style_hint"],
            "estimated_scene_count": s["estimated_scene_count"],
            "why_this_fits": s.get("why_this_fits", ""),
            "is_selected": False,
            "is_archived": False,
            "source": source,
            "created_at": now,
        })
    return out
