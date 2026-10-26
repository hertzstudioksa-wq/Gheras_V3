"""Production planning service — one AI call per order (no template fallback).

One mega-JSON call that produces: production_plan + scene_plans + book_pages + character_profiles.
"""
import os
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from models import ARC_TEMPLATES, duration_scene_range

logger = logging.getLogger("production_service")

MODEL_PROVIDER = "anthropic"
MODEL_NAME = "claude-opus-5-5"


SYSTEM_MSG = """أنت مدير إنتاج قصص أطفال عربية محترف. مهمتك إنتاج **خطة إنتاج كاملة** لقصة مختارة، تتضمّن:

1. خطة عامة (production_plan)
2. مشاهد مُفصّلة (scenes) — عددها يساوي exactly target_scene_count
3. صفحات كتاب (book_pages) — صفحة لكل مشهد
4. ملفات شخصيات (character_profiles) — للطفل وكل الشخصيات البارزة

## القواعد الأساسية
- النصوص الموجّهة للقراءة/الصوت: **بالعربية** (narration_text, book_text, story_summary...).
- برومبتات الصور/الأنيميشن: **بالإنجليزية** (image_prompt_text, animation start/end, style_reference, visual_description). انقل أسماء الأطفال صوتياً (مثل Yusuf, Sara).
- لا عنف، لا أذى، لا خوف مفرط. النهاية دائماً إيجابية.
- consistency: نفس أوصاف الشخصيات وملابسها في كل مشهد ولقطة.
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
    "cover_prompt": "English prompt for the book cover illustration — include child's name transliterated, mood, and visual anchor (no art-style words: the studio applies a fixed house style)",
    "story_keywords": ["English keywords, 8-15 short tags capturing themes, emotions, recurring objects, environment — child-safe"],
    "story_music_prompt": "English one-paragraph music direction for the whole story (mood, tempo feel, instrumentation family, child-friendly)",
    "story_music_keywords": ["warm", "gentle", "playful"],
    "story_voice_prompt": "English narration-direction for the whole story (pace, warmth, delivery style, child-safe tone)",
    "safety_check": "ok"
  },
  "characters": [
    {
      "type": "child, or the character's key exactly as in the list of characters (mother, father, friend, friend_2...)",
      "name": "Arabic name if any",
      "name_en": "Transliterated name",
      "visual_description": "English detailed appearance (face, hair, body type, eyes, skin tone)",
      "clothing_style": "English clothing",
      "key_features": "English 2-3 permanent look features (hair, glasses, freckles, an accessory) — never an expression or a mood",
      "reference_image_url": null
    }
  ],
  "story_objects": [
    {
      "key": "short_english_key (e.g. kite)",
      "name_en": "English name as the shots say it (e.g. the red kite)",
      "look": "English: what never changes — material, shape of its parts, exact colors, any special mark (e.g. a red diamond-shaped paper kite on thin wooden sticks with a long yellow tail of ribbon bows). No size, no arrangement, no state.",
      "sheet_view": "English: how its reference picture shows it alone (e.g. the kite lying flat on the floor, its tail curled beside it); an object that changes in the story shows its parts loose and apart, not assembled",
      "toy": "true for a toy with a face or a body (plush, doll, action figure, toy animal) — a famous character's toy keeps its famous design — else false"
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
        "prompt_text": "Full English image generation prompt — MUST start with: 'Use the same child from the reference image.' Then describe the scene, environment, lighting, emotion, composition. No art-style words.",
        "style_reference": "",
        "character_reference_note": "Use the reference image of the child Yusuf exactly as provided. Preserve face, hair, and clothing consistency."
      },
      "animation_prompt": {
        "start_frame_description": "English description of the first frame",
        "end_frame_description": "English description of the last frame",
        "motion_hint": "English motion (e.g. slow zoom-in on child's face, gentle pan left across the room)",
        "camera_style": "English camera style (e.g. static handheld, smooth dolly-in, subtle parallax)"
      },
      "video_prompt": "English, 2-3 sentence prompt suitable for a text-to-video generator. Cover subject, motion, camera, mood, pacing. Include the recurring object if present in this scene.",
      "voice_prompt": "English voice-direction for this scene — pacing, emotional delivery, volume/intensity, any pauses. Child-safe tone.",
      "music_prompt": "English music-direction for this scene only — mood, tempo feel, texture. 1-2 sentences.",
      "music_keywords": ["English", "3-6 tags", "for this scene only"],
      "camera_motion_hint": "English short camera/motion cue (e.g. slow push-in, static hold, gentle whip-pan)",
      "estimated_duration_seconds": 15,
      "shots": [
        {
          "shot_index": 1,
          "narration_line": "جملة سرد واحدة قصيرة (باللهجة المطلوبة) تُقال أثناء هذه اللقطة بالضبط",
          "shot_type": "wide | medium | close-up | insert | over-the-shoulder | back view",
          "characters": ["child", "mother"],
          "objects": ["keys of the story_objects seen in this shot"],
          "keyframe_prompt": "English: the FIRST frame of this shot, at the very moment of narration_line — who is where, pose, where each character looks (at whom or what — never at the camera), the feeling on each face (tears, surprise, joy...), the size of each story object measured against a character's body, composition, background, lighting. Name characters (e.g. Sara, her mother) and keep their outfits from characters[]. No art-style words.",
          "motion_prompt": "English: ONE small continuous movement of a named character that starts from the first frame (a face changing, a head turning, hands rising to the mouth, a hug, clapping). Nothing else: no camera move, no environment motion, no object moving by itself; a hand touching an object stays on it."
        }
      ]
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

## قواعد اللقطات (shots) — الأهم في الخطة
الفيديو يُبنى من لقطات متحركة قصيرة (كل لقطة ~5 ثوانٍ) مثل أفلام الأطفال المصوّرة، وكل لقطة يُقال عليها سطر سرد واحد.
- عدد shots في كل مشهد = العدد المحدد لهذا المشهد في رسالة المستخدم بالضبط.
- narration_line: جملة واحدة كاملة قصيرة تصف ما يحدث في نفس اللقطة (لا تحكي حدثاً لا نراه). الحد الأقصى للكلمات في رسالة المستخدم.
- narration_text للمشهد = سطور اللقطات متتالية (يمكن تركه فارغاً، سيُجمَع تلقائياً).
- نوّع shot_type مثل السينما: لقطة واسعة تؤسس المكان، ثم متوسطة وقريبة على المشاعر، وinsert لغرض مهم. لا تكرر نفس النوع في لقطتين متتاليتين.
- motion_prompt: حركة حقيقية واضحة للشخصيات (تمشي، تحضن، تلتفت، تبتسم، تمد يدها...) — ليس مجرد زووم على صورة ثابتة. لكن اللقطة ~5 ثوانٍ فقط، وموديل الفيديو يخطئ عندما تزدحم: يكرر شخصية أو يجعل جسماً يخترق شيئاً. لذلك:
  - فعل رئيسي واحد لكل لقطة (أو فعلان بسيطان جداً لنفس الشخصية). ممنوع سلسلة أحداث مثل "يأخذ نفساً ثم يمسك يده ثم يعبر ثم يقفز والأم تصفق".
  - كل من سيظهر في اللقطة موجود في أول إطار. لا أحد يدخل الكادر، والكاميرا لا "تكشف" أشخاصاً أو مكاناً جديداً.
  - الكاميرا ثابتة دائماً: لا push-in ولا pan ولا zoom (حركة الكاميرا بتمطّ الأشياء الثابتة وبتكبّرها). ممنوع arc / orbit / follow / reveal.
  - اللقطة تتحرك من صورة واحدة ثابتة، وموديل الفيديو لا يستطيع إظهار الأحداث الفيزيائية: الأشياء التي تقع أو تنهار أو تنكسر أو تنسكب أو تُرمى أو تصطدم بتذوب أو تتمدد. لذلك أي حدث فيزيائي في السطر (وقوع، انهيار، كسر، انسكاب، رمي، اصطدام، قفز، طيران شيء): keyframe_prompt يصوّر اللحظة بعده مباشرة — النتيجة موجودة بالفعل في أول إطار (الأشياء على الأرض، البقعة موجودة) والشخصيات تتفاعل معها — وmotion_prompt حركة رد الفعل (وش بيتغيّر، إيدين على البق). السرد هو اللي يحكي السبب. لا تطلب أبداً في motion_prompt أن يقع أو ينكسر أو يتحرك شيء.
  - لا حركة للبيئة في motion_prompt (رياح، ستائر، غبار، أوراق، ضوء يتراقص، شعر يتطاير)، ولا شيء يكبر أو يصغر أو يغيّر شكله.
  - تجنّب الحركات الصعبة فيزيائياً: القفز، التسلق، المشي على جسر حبال أو حافة ضيقة، المرور خلال شيء، تسليم شيء من يد ليد، الركض ممسكين بالأيدي. لو القصة فيها جسر أو مرتفع: الشخصيات واقفة عليه وتنظر للمنظر، أو لقطة قريبة على الوجه والمشاعر.
  - في over-the-shoulder و back view: الكاميرا ثابتة تماماً، والشخصية التي في المقدمة لا تتحرك من مكانها.
  - اللقطات المتوسطة والقريبة: شخصية أو اثنتان فقط. ثلاث شخصيات أو أكثر في لقطة واسعة فقط، وأربع شخصيات بحد أقصى في أي لقطة (الطفل وأهله أولاً).
  - motion_prompt يُظهر ما يقوله narration_line لنفس اللقطة — والحدث الفيزيائي يُظهر رد الفعل عليه (القاعدة السابقة).
- لا تطلب أي كلام مكتوب في keyframe_prompt أو motion_prompt (أسماء أماكن، كلمات على خريطة، لافتات، عناوين، أرقام): الموديلات بتكتبها غلط. الخريطة أو اللافتة تبان برسومات بس (جزيرة، بركان، شجر، علامة X).
- keyframe_prompt: يصف أول إطار فقط، في لحظة narration_line نفسها، والمشاعر ظاهرة على الوجوه (دموع، دهشة، فرح): أول إطار هو اللي بيحدد شكل الشخصية طول اللقطة. كل شخصية تظهر فيه يجب أن تكون في characters للقطة. لا تصف ملابس الشخصيات التي clothing_style لها "same as in the photo" (ملابسها تأتي من صورتها المرجعية).
- story_objects: الأغراض التي لها دور في القصة وتظهر في لقطتين أو أكثر (برج مكعبات، طائرة ورقية، كرة، كعكة، صندوق...) — 3 بحد أقصى. لعبة الطفل التي رفع الأهل صورتها ليست منها (لها صورتها)؛ أما اللعبة أو الشخصية المفضّلة بدون صورة فتدخل لو ظهرت في لقطتين أو أكثر. كل لقطة تُرسم وحدها، فالغرض الذي ليس له شكل ثابت مكتوب يتغيّر شكله من لقطة لأخرى. look: ما لا يتغيّر أبداً بتفاصيل محددة (الخامة، شكل الأجزاء، الألوان بالضبط، أي علامة مميزة)، بدون حجم ولا ترتيب ولا حالة. sheet_view: كيف يُرسم في صورته المرجعية وحده؛ لو الغرض يتغيّر في القصة (برج يُبنى ثم يقع، كعكة تُقطع) ارسم أجزاءه سائبة ومتفرقة فقط (بضع قطع على الأرض غير مركّبة)، لا أي شكل مركّب: الصورة تنسخ الترتيب الذي تراه في المرجع.
- الشخصية المشهورة أو اللعبة التي لها وجه (سوبر هيرو، شخصية كرتون، دبدوب، عروسة، فيجر): لو الأهل وصفوها لعبة أو دمية، أو القصة واقعية والأهل لم يطلبوها بطلاً حياً: هي من story_objects و toy = true — look يصفها بشكلها المشهور بالضبط (نفس الوجه وشكل العيون وألوانها، الشعر، الملابس والألوان) مصنوعة كدميتها الرسمية من محلات اللعب (قماش فرو بخياطة، أو بلاستيك)؛ في keyframe_prompt تجلس مثل الدمية أو في يد أو حضن أحد، ولا تقف ولا تمشي وحدها. لو القصة خيالية وجعلتها بطلاً حياً مع الطفل (أو الأهل طلبوا ذلك): هي شخصية في characters (type = other) بوصفها المشهور، تتحرك وتتكلم عادي، وليست من story_objects.
- objects في كل لقطة: keys الأغراض من story_objects التي تظهر فيها.
- الأحجام بالجسم: كلما ذكر keyframe_prompt غرضاً من story_objects اكتب حجمه بالنسبة لجسم شخصية في نفس اللقطة (حتى ركبة / وسط / كتف / ذقن / فوق رأس فلان وهو واقف أو جالس أو راكع)، لا "كبير" ولا "أطول منهم". لو القصة تقارن (أكبر، أطول، أكثر من الأول): الحجم الجديد أكبر بوضوح بنفس المقياس الذي كُتب به الأول، ورتّب اللقطة ليظهر الفرق (الشخصيات واقفة بجانبه لا جالسة).
- النظرة: keyframe_prompt يحدد لكل شخصية إلى من أو إلى ماذا تنظر (إلى بعضهم، إلى الغرض، إلى الطفل). لا أحد ينظر إلى الكاميرا: الصور المرجعية مرسومة تنظر للأمام، ومن لم تُكتب نظرته ينظر للمشاهد.
- الألعاب التي لها وجه (دمية، دبدوب، شخصية كرتون): موديل الفيديو يحرّكها مع حركة الناس كأنها حيّة. في لقطة فيها حركة كبيرة (تصفيق، هتاف، رفع الذراعين، قفز) تكون اللعبة في حضن أو ذراعي شخصية، أو على طرف الكادر بعيداً عنهم — لا في المنتصف بينهم.
- الأيدي: لو يد شخصية تلمس شيئاً في أول إطار تبقى ثابتة عليه طوال اللقطة، إلا لو كان السطر عن تحريك هذا الشيء نفسه — موديل الفيديو حين تبتعد اليد عن شيء يأخذه معها. سطر فيه وضع / تركيب / إغلاق / ترك شيء: أول إطار يكون الشيء في مكانه بالفعل والأيدي بعيدة عنه، وmotion_prompt رد فعل (ابتسامة، تصفيق، إشارة).
- key_features لكل شخصية: صفات شكل دائمة فقط (الشعر، نظارة، نمش، إكسسوار) — ممنوع تعبيرات أو مشاعر (ابتسامة، تكشيرة، ضحكة): الصورة بتنسخها في كل لقطة حتى لو الشخصية بتعيّط.
- اللقطات داخل المشهد الواحد في نفس المكان والإضاءة والملابس (استمرارية).
- آخر لقطتين في القصة تختمان القصة بوضوح ودفء (لحظة الفرح/الطمأنينة بعد الحل).

## قواعد قوة القصة
حتى في 30–45 ثانية القصة تحتاج قوساً كاملاً، وإلا خرجت باهتة:
- أول سطر صورة محددة تشدّ الطفل (فعل، صوت، تفصيلة)، لا تلخيص عام مثل "كانوا بيشتغلوا بجد كل يوم".
- للطفل هدف واضح، ثم محاولة فيها صعوبة صغيرة حقيقية تناسب عمره (تعب، خوف بسيط، فشل أول) ثم يكمل، ثم نتيجة تأتي **بسبب** مجهوده هو، ثم خاتمة دافئة.
- القيمة تُرى ولا تُقال: الطفل يفعلها بنفسه بفعل ملموس (يرتّب، يوفّر، يتدرّب، يساعد، يكمل رغم التعب). ممنوع سطر وعظ في النهاية مثل "الكنز الحقيقي هو…" أو "وتعلّم أن…".
- "الموقف الحقيقي" الذي كتبه الأهل هو أساس القصة: استخدم أماكنه وأشخاصه وأحداثه كما هي. ممنوع الأدوات السحرية (خريطة تنوّر أو تتكلم، باب سحري…) إلا لو الأهل طلبوا خيالاً صراحة أو كان السيناريو المختار خيالياً.
- لا حلول من السماء: ممنوع "وفجأة ظهر…" ليحل المشكلة أو يبدأ الرحلة. النتيجة يصنعها الطفل والعائلة.
- تفاصيل حسّية محددة من المكان (حيوان باسمه، صوت، لون، ملمس) بدل الوصف العام.
- سطر أو سطران من حوار قصير لشخصية (يقولها الطفل أو أحد الأهل) يقرّبان القصة من الطفل.
- كل سطر يدفع القصة خطوة جديدة: لا سطرين بنفس المعنى، ولا سطر يصف شيئاً لا نراه.

## قواعد صارمة
- عدد scenes = target_scene_count بالضبط.
- عدد book_pages = عدد scenes (1 لكل مشهد).
- characters: الطفل إلزامي (type=child). أضف أي شخصية بارزة ذُكرت في بيانات الطلب.
- characters_in_scene و characters في كل لقطة: استخدم مفتاح الشخصية كما في قائمة الشخصيات (child, mother, friend, friend_2...) وليس name — سيتم ربطها داخلياً. شخصيتان من نفس النوع (صديقان، أخوان) لكل منهما مفتاحه، وكل من يظهر في اللقطة يُذكر بمفتاحه.
- الشخصيات ذات role = mentioned تُذكر بالاسم في السرد فقط ولا تظهر بصرياً: لا تضعها في characters_in_scene ولا في characters أي لقطة، ولا تصفها في keyframe_prompt.
- الطفل وأي شخصية لها reference_image_url (صورة حقيقية): اكتب clothing_style = "same as in the photo" — ملابس الصورة هي ما يجعل الأهل يتعرّفون على الشخصية. غيّرها فقط إذا احتاجت القصة ملابس معيّنة (بيجامة وقت النوم، ملابس سباحة، زي تنكري...) واكتب حينها الملابس الجديدة صراحةً.
- أي زي أو إكسسوار تلبسه الشخصية في معظم القصة (كاب شرطة، عباءة بطل، بالطو دكتور، تاج، نظارة غطس...) يُكتب في clothing_style نفسه، مش في key_features بس: مثلاً "same as in the photo, plus a blue police cap with a gold badge and a silver whistle on a cord". الشيت المرجعي يُرسم منه، وموديل الفيديو يرجّع الشخصية لشكل الشيت — فالإكسسوار اللي مش في الشيت يختفي في نص اللقطة.
- visual_description و prompts كلها بالإنجليزية. لا تكتب أي وصف لستايل الرسم (ألوان مائية، 3D، Pixar...) — الستايل ثابت يطبّقه الاستوديو.
- narration_text و book_text و scene_goal و title بالعربية.
- **كل مشهد يجب أن يحمل narration_text و book_text فريدين ومختلفين جذرياً عن المشاهد الأخرى** — لا تكرار! كل مشهد يمثّل بيت قصصي مختلف (مقدمة / مشكلة / تصعيد / لحظة تعلّم / حل / نهاية).
- اقرأ الـ arc_template واكتب محتوى يعكس كل arc_beat بدقة. التكرار يفسد القصة.
- safety_check: "ok" في الحالة الطبيعية. استخدم "review" فقط لو هناك موضوع حسّاس.

## قواعد جودة المشهد الأخير (Final scene — CRITICAL)
- المشهد الأخير يجب أن يُغلق القصة عاطفياً: خاتمة واضحة، إظهار الدرس/القيمة بوضوح، لحظة تأمّل أو فرح، تغيّر ملموس في الطفل.
- سطور لقطات المشهد الأخير دافئة وتختم القصة، لا تُترك مبتورة.
- book_text للمشهد الأخير: جملتان كاملتان على الأقل، تختم القصة برسالة مُقنعة.
- video_prompt و music_prompt للمشهد الأخير: يعكسان **الهدوء بعد الحل** أو **الفرح بعد التجاوز**، ليس بداية جديدة.
- ممنوع: "وانتهت القصة" أو أي نهاية قصيرة ضعيفة من سطر واحد.

## قواعد جودة الكثافة (يخص المدد الطويلة)
- لو target_scene_count ≥ 7: كل مشهد يجب أن يحمل **لحظة فعل حقيقية أو تحوّل داخلي** — لا تكرر نفس الفكرة بألفاظ مختلفة.
- استخدم key_objects و اللعبة المفضّلة (إن وُجدت) كخيط مرئي متكرر عبر المشاهد لخلق ترابط.
- estimated_duration_seconds لكل مشهد ≈ duration_seconds / target_scene_count (± قليلاً).

## توجيهات JSON الإضافية (Phase D.4)
- story_keywords: 8-15 وسوم إنجليزية قصيرة، child-safe، تغطي الثيمات، المشاعر، الأغراض المتكرّرة، البيئة.
- story_music_prompt: paragraph إنجليزي موحّد لموسيقى القصة كاملة.
- video_prompt و voice_prompt و music_prompt و music_keywords في كل مشهد **إلزامية** — لا تتركها فارغة.
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


# Phase D.5 — final-scene quality guard thresholds.
# Arabic averages ~5-6 words per short sentence; we require the closing
# scene to feel complete rather than a one-liner.
_FINAL_MIN_NARRATION_WORDS = 12  # ≈ 3 short sentences
_FINAL_MIN_BOOK_WORDS      = 8   # ≈ 2 short sentences


def _enforce_final_scene_quality(scenes: list[dict], child_name: str = "") -> None:
    """In-place: ensure the LAST scene closes the story strongly.

    Guarantees:
      * narration_text has at least _FINAL_MIN_NARRATION_WORDS words.
      * book_text has at least _FINAL_MIN_BOOK_WORDS words.
      * Never throws — if the text is too short we append a warm closing line
        in Arabic that reinforces the main message. This is the backend-side
        mirror of the LLM-side "Final scene CRITICAL" rules in SYSTEM_MSG.
    """
    if not scenes:
        return
    last = scenes[-1]
    name = (child_name or "بطلنا").strip()

    narr = str(last.get("narration_text") or "").strip()
    narr_wc = len([w for w in narr.split() if w])
    if narr_wc < _FINAL_MIN_NARRATION_WORDS:
        logger.warning(
            f"Final scene narration too short ({narr_wc} words < {_FINAL_MIN_NARRATION_WORDS}); enriching."
        )
        addition = (
            f" وفي النهاية، ابتسم {name} بهدوء وهو يشعر بأن قلبه أصبح أكبر، "
            f"وتأمّل اللحظة بكل جمالها قبل أن يعود إلى عالمه مليئاً بالفخر."
        )
        last["narration_text"] = (narr + addition).strip()
        last["word_count"] = len([w for w in last["narration_text"].split() if w])

    book = str(last.get("book_text") or "").strip()
    book_wc = len([w for w in book.split() if w])
    if book_wc < _FINAL_MIN_BOOK_WORDS:
        logger.warning(
            f"Final scene book_text too short ({book_wc} words < {_FINAL_MIN_BOOK_WORDS}); enriching."
        )
        addition = f" وابتسم {name} بفخر، وعرف أن الدرس سيبقى في قلبه للأبد."
        last["book_text"] = (book + addition).strip()


def _build_user_prompt(order: dict, scenario: dict, target_scenes: int) -> str:
    data = order.get("data", {}) or {}
    enriched = order.get("enriched", {}) or {}
    duration = order.get("duration", {}) or {}
    brange = duration_scene_range(duration)
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

    keys = house_style.cast_keys(chars)
    chars_brief = "\n".join(
        f"- {key}{' (' + (c.get('name') or '') + ')' if c.get('name') else ''} — {c.get('role','mentioned')}"
        + (f"\n  reference_image_url: {c.get('image_url')}" if c.get("role") == "visible" and c.get("image_url") else "")
        + (f"\n  auto_visual_description: {c.get('visual_description_auto')}" if c.get("visual_description_auto") else "")
        for key, c in zip(keys, chars)
    ) or "لا يوجد"

    fav_brief = "، ".join(
        f"{k}: {(v or {}).get('name','')}"
        for k, v in (pers.get("favorites") or {}).items()
        if (v or {}).get("selected") and (v or {}).get("name")
    ) or "لا يوجد"

    # Uploaded toy/object — automatic visual description (Phase D.3).
    toy_desc = pers.get("toy_description_auto") or ""
    toy_url = pers.get("toy_image_url") or ""
    toy_name = ((pers.get("favorites") or {}).get("toy") or {}).get("name") or ""
    toy_block = ""
    if toy_desc or toy_url or toy_name:
        # Only a toy with a photo has its own reference; one named without a photo
        # is a story object like any other (the plan once left a favourite plush seen in
        # every shot out of story_objects because this header said "uploaded").
        lines = ["**لعبة/غرض مهم للطفل (مرفوع كصورة)**:" if toy_url else "**لعبة الطفل المفضّلة (بدون صورة)**:"]
        if toy_name:
            lines.append(f"- الاسم: {toy_name}")
        if toy_url:
            lines.append(f"- image_url: {toy_url}")
        if toy_desc:
            lines.append(f"- الوصف البصري المستخرج: {toy_desc}")
        lines.append("- يجب أن يظهر هذا الغرض في key_objects و visual_description للمشاهد المناسبة."
                     + ("" if toy_url else " ولو ظهر في لقطتين أو أكثر فهو من story_objects بشكل ثابت."))
        toy_block = "\n".join(lines) + "\n"

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
**target_scene_count**: {target_scenes}{" (ضمن النطاق " + f"{brange[0]}–{brange[1]}" + " — يُسمح بأي عدد داخل هذا النطاق)" if brange else ""}
**arc_template (بالترتيب)**: {arc}
**الخلفية الصوتية المفضّلة**: {audio_bg_label}

**الشخصيات الإضافية**:
{chars_brief}

{toy_block}**مفضّلات الطفل**: {fav_brief}
**ملاحظات خاصة**: {pers.get('custom_notes') or 'لا يوجد'}

---

أنتج الخطة الكاملة كـ JSON واحد حسب الصيغة المطلوبة. **{target_scenes} scenes بالضبط**{" (أو أي عدد داخل النطاق " + f"{brange[0]}–{brange[1]}" + " إن كان أنسب للسرد)" if brange else ""}، ولكل مشهد arc_beat من القائمة أعلاه بالترتيب."""


from services import engine_config, house_style
from services.config_service import resolve_model, resolve_prompt
from services.ai.text_client import generate_text


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
        f"{key}: {c.get('name','')}" for key, c in zip(house_style.cast_keys(chars), chars) if c.get("name")
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
        "scene_target_min":   duration.get("scene_target_min", target_scenes),
        "scene_target_max":   duration.get("scene_target_max", target_scenes),
        "scene_target_bucket": duration.get("scene_target_bucket", ""),
        "arc_beats_csv":      ", ".join(arc),
        # Extras
        "favorites_summary":  fav_brief,
        "characters_summary": chars_brief,
        "extra_notes":        pers.get("custom_notes", "") or "لا يوجد",
        "audio_background_mode": audio_bg_label,
    }


def target_scene_count(order: dict, scenario: dict | None) -> int:
    """Scenes to plan: the scenario's own estimate when it lies inside the
    duration bucket, else the bucket's target (Phase D.5)."""
    duration = order.get("duration") or {}
    target = int(duration.get("scene_target") or 6)
    est = (scenario or {}).get("estimated_scene_count")
    mn, mx = duration.get("scene_target_min"), duration.get("scene_target_max")
    if isinstance(est, int) and isinstance(mn, int) and isinstance(mx, int) and mn <= est <= mx:
        return est
    return target


async def build_planning_request(order: dict, scenario: dict, target_scenes: int) -> dict:
    """Everything the planning call sends — model, system prompt, user prompt — plus
    the admin layers behind it. Shared by generation and the admin prompt preview,
    so the preview is exactly what the model receives."""
    provider, model_name, model_src = await resolve_model(
        "production_planning", MODEL_PROVIDER, MODEL_NAME
    )
    # Prompt: admin template if it renders cleanly, else hardcoded fallback.
    ctx = _build_production_context(order, scenario, target_scenes)
    admin_prompt, prompt_src, reason = await resolve_prompt("production_planning", ctx)
    prompt = admin_prompt if prompt_src == "admin" else _build_user_prompt(order, scenario, target_scenes)

    # Admin direction for the parent's picks (category, topic, story type, tone, setting).
    fragments = await engine_config.story_fragments(order)
    prompt += fragments
    # Shots and dialect drive the video: one ~5 s animated shot per narration
    # line, so the story lasts what the parent chose and nothing is held still.
    pacing = await engine_config.get_pacing()
    seconds = int((order.get("duration") or {}).get("seconds") or 0) or 60
    counts = house_style.shot_counts(seconds, target_scenes, pacing["shot_seconds"])
    dialect = await engine_config.get_dialect(await house_style.dialect_for_order(order))
    per_scene = "\n".join(f"- المشهد {i + 1}: {n} لقطات" for i, n in enumerate(counts))
    max_words = house_style.max_line_words(pacing["shot_seconds"], pacing["words_per_second"])
    prompt += (
        f"\n\n## اللقطات واللهجة (لها الأولوية على أي قاعدة أخرى)\n"
        f"- مدة القصة {seconds} ثانية = {sum(counts)} لقطة تقريباً (لقطة كل ~{pacing['shot_seconds']} ثوانٍ):\n"
        f"{per_scene}\n"
        f"- كل narration_line لا تزيد عن {max_words} كلمات (يُفضّل 6–9).\n"
        f"- لهجة السرد ({dialect['name_ar']}): {dialect['writing']}\n"
        f"- book_text و title وباقي النصوص العربية بالفصحى المبسّطة."
    )
    system, system_src = await engine_config.system_prompt("production_planning", SYSTEM_MSG)
    style = await engine_config.style_for_order(order)
    return {
        "provider": provider, "model": model_name, "system": system, "user": prompt,
        "seconds": seconds, "counts": counts,
        "style_guide": engine_config.style_guide(style),
        "words_per_second": pacing["words_per_second"],
        # Which admin layers (and versions) shaped this plan — kept on the plan so a
        # story can be traced and reproduced after the settings change.
        "trace": {
            "model": f"{provider}/{model_name}",
            "model_source": model_src,
            "user_prompt_source": prompt_src,
            "user_prompt_reason": reason,
            "system_prompt": system_src,
            "style": {"key": style.get("key"), "version": style.get("version")},
            "dialect": {"key": dialect["key"], "version": dialect.get("version")},
            "pacing_version": pacing.get("version"),
            "story_fragments": fragments.strip(),
            "shot_counts": counts,
        },
    }


async def _generate_via_claude(order: dict, scenario: dict, target_scenes: int) -> dict:
    """Ask the configured text model for the full production plan. Raises on any failure."""
    req = await build_planning_request(order, scenario, target_scenes)
    provider, model_name, prompt, system = req["provider"], req["model"], req["user"], req["system"]
    seconds, counts = req["seconds"], req["counts"]
    logger.info(f"[config] stage=production_planning model={provider}/{model_name} "
                f"prompt={req['trace']['user_prompt_source']} system={req['trace']['system_prompt']['source']}")

    # The plan is a large nested JSON (scenes, pages, characters); its shape is
    # enforced by SYSTEM_MSG and validated below rather than by a strict schema.
    response = await generate_text(
        stage="production_planning",
        provider=provider,
        model=model_name,
        system=system,
        user=prompt,
        effort="high",
        max_tokens=48000,
        timeout=600.0,
    )
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
    scenes_len = len(payload.get("scenes", []))
    brange = duration_scene_range(order.get("duration"))
    if brange is not None:
        lo, hi = brange
        if not (lo <= scenes_len <= hi):
            raise ValueError(
                f"Scenes out of bucket range: got {scenes_len}, expected {lo}-{hi} (target {target_scenes})"
            )
    else:
        # Legacy: old orders without bucket info — keep exact-match.
        if scenes_len != target_scenes:
            raise ValueError(f"Expected {target_scenes} scenes, got {scenes_len}")
    # Every scene must come as animated shots with a narration line each; a
    # plan without them would fall back to one long held image per scene.
    shot_total = 0
    for s in payload.get("scenes") or []:
        lines = [sh for sh in (s.get("shots") or []) if str(sh.get("narration_line") or "").strip()]
        if len(lines) < 2:
            raise ValueError(f"scene {s.get('scene_index')} has {len(lines)} shots with narration (need ≥2)")
        shot_total += len(lines)
    if abs(shot_total - sum(counts)) > max(2, sum(counts) // 5):
        raise ValueError(f"plan has {shot_total} shots, expected about {sum(counts)} for {seconds}s")
    payload["_engine"] = {k: req[k] for k in ("style_guide", "words_per_second", "trace")}
    return payload


async def generate_production_plan(order: dict, scenario: dict, target_scenes: int) -> tuple[dict, str, str | None]:
    # No template fallback (it produced generic, gender-blind plans that looked
    # personalised). A failure propagates and the order is marked failed.
    return (await _generate_via_claude(order, scenario, target_scenes), "ai", None)


def _normalise_shots(raw) -> list[dict]:
    """Clean the LLM's shots list: keep shots that have a narration line, renumber 1..n."""
    shots = []
    for sh in raw or []:
        if not isinstance(sh, dict):
            continue
        line = str(sh.get("narration_line") or "").strip()
        if not line:
            continue
        chars = sh.get("characters") or []
        objects = sh.get("objects") or []
        shots.append({
            "shot_index": len(shots) + 1,
            "narration_line": line,
            "shot_type": str(sh.get("shot_type") or "medium").strip(),
            "characters": [str(c).strip() for c in chars if str(c).strip()] if isinstance(chars, list) else [],
            "keyframe_prompt": str(sh.get("keyframe_prompt") or "").strip(),
            "motion_prompt": str(sh.get("motion_prompt") or "").strip(),
            "objects": [_object_key(o) for o in objects if _object_key(o)] if isinstance(objects, list) else [],
        })
    return shots


MAX_STORY_OBJECTS = 3

# Things worn. The sheet is drawn from clothing_style, so a helmet the plan put in
# key_features only (scooter story) was on no sheet while the shots asked for it —
# the way a cap missing from the sheet came off mid-shot.
WEARABLES = ("helmet", "cap", "hat", "glasses", "sunglasses", "goggles", "backpack", "bag", "cape", "crown",
             "tiara", "mask", "scarf", "headband", "apron", "badge", "vest", "jacket", "gloves", "costume",
             "uniform", "bow tie", "whistle")
_WORN = re.compile(r"\b(" + "|".join(re.escape(w) for w in WEARABLES) + r")s?\b", re.I)


def worn_in_outfit(clothing: str, features) -> str:
    """clothing_style plus every worn thing key_features names that it doesn't."""
    clothing = str(clothing or "").strip()
    text = ", ".join(map(str, features)) if isinstance(features, list) else str(features or "")
    worn = [p.strip() for p in re.split(r"[;,]", text) if p.strip() and _WORN.search(p)]
    missing = [w for w in worn if w.lower() not in clothing.lower()]
    if not clothing or not missing:
        return clothing
    return f"{clothing.rstrip(' .')}, plus {' and '.join(missing)}"


def _object_key(raw) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(raw or "").strip().lower()).strip("_")[:40]


def _normalise_objects(raw) -> list[dict]:
    """The plan's recurring story objects: a key, a name and a look that never changes."""
    objects: list[dict] = []
    for o in raw or []:
        if not isinstance(o, dict):
            continue
        key, name, look = _object_key(o.get("key") or o.get("name_en")), str(o.get("name_en") or "").strip(),             str(o.get("look") or "").strip()
        if key and name and look and key not in {x["key"] for x in objects}:
            objects.append({"key": key, "name_en": name[:80], "look": look[:400],
                            "sheet_view": str(o.get("sheet_view") or "").strip()[:300],
                            "toy": o.get("toy") is True or str(o.get("toy")).strip().lower() == "true"})
    return objects[:MAX_STORY_OBJECTS]


def build_docs(order: dict, payload: dict, run_id: str, source: str) -> dict:
    """Convert LLM JSON into DB-ready documents. Returns {plan, scenes, book_pages, character_profiles}."""
    order_id = order["id"]
    now = _now()
    plan_payload = payload.get("production_plan", {}) or {}
    plan_id = str(uuid.uuid4())
    engine = payload.get("_engine") or {}
    wps = engine.get("words_per_second") or house_style.WORDS_PER_SECOND

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
            "clothing_style": worn_in_outfit(c.get("clothing_style", ""), c.get("key_features", "")),
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

    story_objects = _normalise_objects(payload.get("story_objects"))
    known_objects = {o["key"] for o in story_objects}

    # scenes + book pages
    scenes: list[dict] = []
    words_total = 0
    for s in payload.get("scenes", []) or []:
        sid = str(uuid.uuid4())
        img = s.get("image_prompt") if isinstance(s.get("image_prompt"), dict) else {}
        anim = s.get("animation_prompt") if isinstance(s.get("animation_prompt"), dict) else {}
        chars_in = []
        for t in s.get("characters_in_scene", []) or []:
            cpid = type_to_id.get(t)
            chars_in.append({"character_profile_id": cpid, "role_in_scene": t})
        shots = _normalise_shots(s.get("shots"))
        for sh in shots:
            sh["objects"] = [k for k in dict.fromkeys(sh["objects"]) if k in known_objects]
        narration = (" ".join(sh["narration_line"] for sh in shots) if shots
                     else str(s.get("narration_text") or "").strip())
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
            # Phase D.4 — downstream generator fields
            "video_prompt":        s.get("video_prompt") or "",
            "voice_prompt":        s.get("voice_prompt") or "",
            "music_prompt":        s.get("music_prompt") or "",
            "music_keywords":      s.get("music_keywords") or [],
            "camera_motion_hint":  s.get("camera_motion_hint") or "",
            "estimated_duration_seconds": (round(wc / wps, 1) if shots
                                           else s.get("estimated_duration_seconds")),
            "shots": shots,
            "word_count": wc,
            "is_archived": False,
            "created_at": now,
        })

    # Sanity: ensure no duplicate narration/book texts between scenes.
    # If the LLM (or fallback) emitted duplicates for any reason, we append a
    # uniqueness marker so every scene tells its own micro-beat.
    _dedupe_scene_texts(scenes)

    # Phase D.5 — final-scene quality guard. The LLM prompt enforces this on
    # its side, but we defensively guarantee the last scene never ships as a
    # weak one-liner even if the upstream model/fallback slips.
    # Shot plans carry their narration line by line (appending text would leave
    # a sentence without a shot), so only legacy plans get the narration top-up.
    _child_name = ((order.get("data") or {}).get("child") or {}).get("name") or ""
    if not any(s["shots"] for s in scenes):
        _enforce_final_scene_quality(scenes, child_name=_child_name)

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
        # The admin style preset the parent picked (the LLM no longer picks one per story).
        "style_guide": engine.get("style_guide") or dict(house_style.STYLE_GUIDE),
        "engine_trace": engine.get("trace"),
        "cover_prompt": plan_payload.get("cover_prompt"),
        # Recurring objects with a fixed look; the shots list theirs under "objects".
        "story_objects": story_objects,
        # Phase D.4 — story-level downstream generator fields
        "story_keywords":        plan_payload.get("story_keywords") or [],
        "story_music_prompt":    plan_payload.get("story_music_prompt") or "",
        "story_music_keywords":  plan_payload.get("story_music_keywords") or [],
        "story_voice_prompt":    plan_payload.get("story_voice_prompt") or "",
        "safety_check": plan_payload.get("safety_check") or "ok",
        "target_scene_count": len(scenes),
        # one keyframe per shot (or per scene on legacy plans) + the cover
        "estimated_image_count": (sum(len(s["shots"]) for s in scenes) or len(scenes)) + 1,
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
