# PROJECT_SCOPE — أبعاد مشروع غِراس

> **مهم:** اقرأ الملف ده في بداية كل سيشن عشان تفهم المشروع بسرعة بدون ما تراجع الملفات من الأول.

---

## المشروع إيه؟
منصة عربية بتخلي الأهل يعملوا كتاب قصة مخصص لأطفالهم بالذكاء الاصطناعي — فيديو + PDF بالعربي مع صوت وموسيقى.

---

## رحلة المستخدم (من أول لآخر)

```
1. يسجّل دخول
2. يبني القصة (6 خطوات: الهدف، الطفل، الشخصيات، التخصيص، الأسلوب، المراجعة)
3. يختار من 3 سيناريوهات (الذكاء الاصطناعي بيولدهم)
4. يوافق على خطة الإنتاج
5. الذكاء الاصطناعي يولد: صور + صوت + موسيقى + فيديو
6. يستلم: فيديو MP4 + كتاب PDF
```

---

## الـ Pipeline — 11 مرحلة إنتاج

| # | المرحلة | بتعمل إيه |
|---|---------|-----------|
| 1 | scenario_generation | توليد 3 سيناريوهات للاختيار |
| 2 | production_planning | تفصيل المشاهد والشخصيات والكتاب |
| 3 | child_character_i2i | تحويل صورة الطفل لرسمة كرتونية |
| 4 | extra_character_i2i | نفس الشيء لباقي الشخصيات |
| 5 | scene_image_generation | رسم صور المشاهد |
| 6 | book_page_image_generation | رسم صفحات الكتاب |
| 7 | narration_generation | توليد الصوت العربي (TTS) |
| 8 | video_generation | توليد مقاطع الفيديو (Kling AI) |
| 9 | music_generation | توليد الموسيقى الخلفية |
| 10 | video_assembly | تجميع الفيديو النهائي (ffmpeg) |
| 11 | pdf_assembly | تجميع الكتاب PDF |

---

## الـ APIs الخارجية المطلوبة

| المفتاح | بيعمل إيه | ضروري؟ |
|---------|-----------|--------|
| `OPENAI_API_KEY` | السيناريوهات + خطة الإنتاج + الصور | ✅ أهم حاجة |
| `ANTHROPIC_API_KEY` | بديل لـ OpenAI | اختياري |
| `FAL_KEY_SCENE` | صور المشاهد | ✅ |
| `FAL_KEY_NARRATION` | الصوت العربي | ✅ |
| `FAL_KEY_MUSIC` | الموسيقى | ✅ |
| `FAL_KEY_VIDEO` | الفيديو (Kling) | ✅ |
| `ELEVENLABS_API_KEY` | صوت + موسيقى مباشرة | اختياري |
| `STRIPE_SECRET_KEY` | نظام الدفع | اختياري لو مش بتستخدم الدفع |

---

## الصفحات الموجودة

### للمستخدم العادي:
- Landing (الرئيسية)، HowItWorks، Categories، Login، Signup
- StoryBuilder (بناء القصة)، Dashboard (طلباتي)
- OrderDetail، ScenarioSelection، ProductionReady، MyBundles

### للـ Admin:
- 18+ صفحة إدارة (طلبات، مستخدمين، محتوى، أسعار، مفاتيح API، إلخ)
- Admin Storyboard: تتبع كل مرحلة إنتاج بالتفصيل
- Stage Lab: اختبار أي مرحلة منفردة
- Model Registry: تغيير الـ AI provider من الـ dashboard

---

## المشاكل الموجودة دلوقتي

### 🔴 حرجة — الذكاء الاصطناعي مش شغال لوكالي
المشكلة: الكود مربوط بـ `emergentintegrations` اللي كانت تشتغل على منصة Emergent بس.
الحل: نحول الـ services دي لـ OpenAI SDK مباشرة:
- `backend/services/scenario_service.py`
- `backend/services/production_service.py`
- `backend/services/image_generation_service.py`

### 🟡 متوسطة — أسماء نماذج OpenAI غلط
الكود بيستخدم `gpt-5.4` و`gpt-image-1.5` — أسماء غير موجودة.
الصح: `gpt-4o` للنصوص، `dall-e-3` أو `gpt-image-1` للصور.

### 🟡 متوسطة — الدفع (Stripe) محتاج مفاتيح
الكود جاهز بس محتاج `STRIPE_SECRET_KEY` في الـ .env.

### 🟢 بسيطة — مفيش إشعارات للمستخدم
لما القصة تخلص مش بيوصله إيميل أو إشعار.

### 🟢 بسيطة — مفيش search في الـ Dashboard
المستخدم مش يقدر يبحث في طلباته.

---

## الأولويات المقترحة

1. **أول حاجة:** نحط مفاتيح API حقيقية (OpenAI + FAL) في الـ .env ونصلح أسماء النماذج
2. **تاني حاجة:** نتأكد إن الـ pipeline كامل بيشتغل من الأول للآخر
3. **تالت حاجة:** نربط دومين بالموقع
4. **بعدين:** إشعارات + search + تحسينات UX

---

## ملفات مهمة تعرفها

| الملف | بيعمل إيه |
|-------|-----------|
| `backend/server.py` | نقطة البداية للـ backend |
| `backend/models.py` | هيكل كل البيانات |
| `backend/services/scenario_service.py` | توليد السيناريوهات بـ AI |
| `backend/services/production_service.py` | خطة الإنتاج بـ AI |
| `backend/services/generation_orchestrator.py` | المدير العام للـ pipeline |
| `frontend/src/App.js` | routing كل الصفحات |
| `frontend/src/lib/api.js` | التواصل مع الـ backend |
| `PROGRESS.md` | آخر تحديث على الشغل |

---

*آخر تحديث: 2026-05-22*
