# PROGRESS — غراس

> **للمطورين:** اقرأ الملف ده الأول قبل ما تبدأ أي شغل.
> لما تخلص سيشن وتعمل push، حدّث الملف ده.

---

## ✅ اتعمل

### الإعداد المحلي (جهاز موامن)
- تحميل الملفات من Emergent وكلون الريبو من GitHub
- تنصيب Python venv + كل المتطلبات
- حل مشكلة `emergentintegrations` (عمل stub محلي)
- استيراد الداتا في MongoDB المحلية (`gheras_local`)
- تشغيل Backend على port 8001 + Frontend على port 3000
- إعداد auto-start مع كل login على Windows

### السيرفر (VPS - Hostinger)
- تنصيب Node.js 20 + MongoDB 8 + yarn
- كلون الريبو على `/var/www/gheras/`
- إعداد Python venv + تنصيب المتطلبات
- استيراد الداتا في MongoDB (`gheras_prod`)
- إنشاء systemd service اسمه `gheras` (backend port 8001)
- إعداد Nginx على port 3000 (static files + proxy للـ API)
- الموقع شغال على: http://76.13.0.195:3000

### GitHub & Deploy
- ربط الريبو بالـ VPS عن طريق GitHub Actions
- أي `git push` على `main` → الموقع يتحدث أوتوماتيك
- إضافة ONBOARDING.md للمشروع
- إضافة Amr كـ collaborator على GitHub

---

## 🔄 شغال عليه دلوقتي

- لا يوجد — المشروع في مرحلة التعديلات

---

## 📋 الخطوة الجاية

- ربط دومين بالموقع (لما يكون جاهز)
- إضافة API keys للـ AI features (OpenAI, FAL, إلخ)

---

## 🔑 معلومات مهمة

| حاجة | التفاصيل |
|------|---------|
| **Admin login** | admin@gheras.com — كلمة المرور مع مسؤول المشروع (مش في الريبو) |
| **VPS IP** | 76.13.0.195 |
| **الموقع** | http://76.13.0.195:3000 |
| **GitHub** | github.com/hertzstudioksa-wq/Gheras_V3 |
| **Backend port** | 8001 |
| **DB (prod)** | gheras_prod |
| **DB (local)** | gheras_local |

---

*آخر تحديث: 2026-05-22 — موامن*
