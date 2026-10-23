# غراس — دليل المشروع

## إيه المشروع ده؟
غراس هو موقع عربي لصناعة كتب أطفال مخصصة بالذكاء الاصطناعي.
المستخدم بيدخل بيانات طفله وبيطلع له كتاب قصة بالصور والأصوات.

## الفريق
- **موامن دايف** — raafatdaif@gmail.com
- **عمرو أبو المجد** — amr.aboelmagd.f5@gmail.com

## الموقع الأونلاين
- **الموقع:** http://76.13.0.195:3000
- **دخول Admin:** admin@gheras.com — كلمة المرور مع مسؤول المشروع (مش في الريبو)

## GitHub
- **الريبو:** https://github.com/hertzstudioksa-wq/Gheras_V3
- أي `git push` على `main` → الموقع بيتحدث أوتوماتيك على السيرفر

---

## إزاي تشتغل على المشروع (للمبتدئين)

### لو أول مرة على جهازك:
1. نزّل [Git](https://git-scm.com/download/win)
2. افتح Terminal وشغّل:
```bash
git clone https://github.com/hertzstudioksa-wq/Gheras_V3.git
cd Gheras_V3
```

### لما تعدل حاجة وتعايز ترفعها:
```bash
git add .
git commit -m "وصف التعديل"
git push
```

### لما حد تاني عمل تعديل وعايز تجيبه:
```bash
git pull
```

---

## هيكل المشروع
```
Gheras_V3/
├── frontend/        ← واجهة الموقع (React)
│   └── src/
│       ├── pages/   ← صفحات الموقع
│       └── components/
├── backend/         ← السيرفر (Python/FastAPI)
│   ├── routes/      ← الـ APIs
│   ├── services/    ← منطق الأعمال
│   └── models.py    ← هيكل البيانات
└── mongo-bundle/    ← بيانات قاعدة البيانات
```

---

## السيرفر (VPS)
- **IP:** 76.13.0.195 — Hostinger KVM 1 — Ubuntu 24.04
- **Backend:** شغال على port 8001 كـ systemd service اسمه `gheras`
- **Frontend:** ملفات static على Nginx port 3000
- **Database:** MongoDB local — DB name: `gheras_prod`
- **على نفس السيرفر:** موقع لزام (لا تلمسه — مستقل تماماً)

---

## التقنيات المستخدمة
- **Frontend:** React 19، TailwindCSS، shadcn/ui
- **Backend:** Python FastAPI، MongoDB
- **Deploy:** GitHub Actions → VPS أوتوماتيك عند كل push

---

## ملاحظات مهمة للـ Claude
- المشروع اتصدّر من منصة Emergent — باكدج `emergentintegrations` اتعمله stub محلي في `backend/emergentintegrations/`
- الـ frontend بيستخدم `REACT_APP_BACKEND_URL=` (فاضي) → الـ API calls بتروح على `/api/` عن طريق Nginx proxy
- الـ backend routes كلها تحت prefix `/api/`
- استخدم `requirements_local.txt` مش `requirements.txt` (لأن requirements.txt فيه packages مش متوافقة مع Python 3.14)
- الـ SSH للـ VPS بيكون بـ password (مش key) — الباسورد في GitHub Secrets
