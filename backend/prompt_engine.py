"""Pre-compute an Arabic AI prompt from structured order data."""
from typing import Any, Dict


def _fav_line(favorites: Dict[str, Any]) -> str:
    parts = []
    for k, v in (favorites or {}).items():
        if not v:
            continue
        if isinstance(v, dict) and v.get("selected"):
            name = v.get("name") or ""
            labels = {
                "toy": "لعبة مفضلة",
                "place": "مكان مفضل",
                "character": "شخصية مفضلة",
                "hobby": "هواية",
                "other": "أخرى",
            }
            parts.append(f"{labels.get(k, k)}: {name}" if name else labels.get(k, k))
    return "، ".join(parts) if parts else "—"


def build_prompt(data: Dict[str, Any], enriched: Dict[str, str]) -> str:
    """data = order.data (structured); enriched = resolved names for ids."""
    child = data.get("child", {}) or {}
    goal = data.get("goal", {}) or {}
    characters = data.get("characters", []) or []
    personalization = data.get("personalization", {}) or {}

    gender_ar = "ولد" if child.get("gender") == "male" else "بنت"
    hijab_line = ""
    if child.get("gender") == "female" and child.get("hijab"):
        hijab_line = " (ترتدي حجاب)"

    chars_lines = []
    for c in characters[:5]:
        type_map = {
            "mother": "الأم",
            "father": "الأب",
            "sibling": "أخ/أخت",
            "friend": "صديق",
            "teacher": "معلّم",
            "grandparent": "جد/جدة",
            "other": "شخصية أخرى",
        }
        t = type_map.get(c.get("type"), c.get("type", ""))
        nm = c.get("name")
        role = "ظاهر في القصة" if c.get("role") == "visible" else "مذكور فقط"
        line = f"- {t}"
        if nm:
            line += f" ({nm})"
        line += f" — {role}"
        # Append auto-generated visual description if available (from uploaded photo).
        if c.get("visual_description_auto"):
            line += f"\n    ملامح بصرية مستخرجة من الصورة: {c['visual_description_auto']}"
        chars_lines.append(line)
    chars_block = "\n".join(chars_lines) if chars_lines else "لا توجد"

    goal_text = (
        enriched.get("subcategory_name")
        or goal.get("custom_subcategory")
        or enriched.get("category_name")
        or ""
    )

    style_parts = []
    for k, label in [
        ("type_name", "نوع القصة"),
        ("tone_name", "النبرة"),
        ("setting_name", "البيئة"),
        ("language_name", "اللغة"),
        ("voice_name", "صوت الراوي"),
    ]:
        v = enriched.get(k)
        if v:
            style_parts.append(f"{label}: {v}")
    style_block = "، ".join(style_parts) if style_parts else "—"

    fav_block = _fav_line(personalization.get("favorites", {}))
    custom_notes = personalization.get("custom_notes") or "—"
    appearance = child.get("appearance_notes") or "—"
    context = goal.get("context") or "—"

    # Uploaded toy/object — automatic visual description (Phase D.3).
    toy_desc = personalization.get("toy_description_auto") or ""
    toy_name = ((personalization.get("favorites") or {}).get("toy") or {}).get("name") or ""
    toy_line = ""
    if toy_desc or toy_name:
        toy_line = "\nلعبة/غرض مهم (من الصورة المرفوعة): "
        if toy_name:
            toy_line += f"{toy_name}. "
        if toy_desc:
            toy_line += toy_desc
        toy_line += "\nيجب أن تظهر هذه اللعبة/الغرض في المشاهد المناسبة للقصة."

    template = f"""اكتب قصة عربية مصوّرة للأطفال بطلها طفل اسمه "{child.get('name', '')}"، عمره {child.get('age', '')} سنوات، {gender_ar}{hijab_line}.

الهدف التربوي من القصة:
- التصنيف: {enriched.get('category_name', '—')}
- الموضوع: {goal_text}
- موقف حقيقي عاشه الطفل: {context}

وصف الطفل:
- ملاحظات مظهر: {appearance}
- صورة مرجعية للطفل: {child.get('image_url', '—')}

الشخصيات الإضافية:
{chars_block}

تخصيصات:
- مفضّلات: {fav_block}
- تفاصيل خاصة يرغب الأهل بإضافتها: {custom_notes}{toy_line}

أسلوب القصة: {style_block}

تعليمات السرد:
- اجعل القصة دافئة ومناسبة لعمر الطفل.
- اغرس القيم ضمن الحدث دون وعظ مباشر.
- استخدم لغة بسيطة سلسة حسب تفضيل اللغة أعلاه.
- اختم بدرس واضح وخفيف بصوت لطيف.
""".strip()
    return template
