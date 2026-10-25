# تشغيل غِراس على السيرفر (76.13.0.195)

السيرفر ده عليه **لزام (Lizamcenter.com) شغّال إنتاج**. كل خطوة هنا بتلمس غِراس بس:
- مفيش `systemctl stop/restart` لأي خدمة غير `gheras`.
- الحاجة الوحيدة المشتركة هي `nginx reload` هادي (من غير ما الموقع يقع) عشان نضيف بورت 3000، وبيحصل بس بعد `nginx -t`، ولو لزام اتأثر بيترجع لوحده.
- قبل وبعد: `systemctl is-active lizam` لازم `active`، و`https://lizamcenter.com/api/public/site-settings` لازم `200`.

## مرة واحدة: التجهيز
1. انسخ الريبو للسيرفر (مثلاً `scp -r backend deploy frontend/build root@76.13.0.195:/root/gheras-src/` بعد `npm run build` بـ `REACT_APP_BACKEND_URL=''`).
2. على السيرفر: `bash /root/gheras-src/deploy/provision.sh`
   - أول مرة بيعمل `/etc/gheras/gheras.env` ويقف: املأ `JWT_SECRET` و`ADMIN_PASSWORD` و`SECRETS_ENCRYPTION_KEY` (`openssl rand -hex 32`)، وشغّله تاني.
   - بيسطّب: ffmpeg، Python venv، Chromium بتاع Playwright (للكتاب)، مستخدم `gheras`، خدمة `gheras.service` بحدود ذاكرة ومعالج.
3. لما الخدمة تشتغل: `bash /root/gheras-src/deploy/provision.sh --enable-site` عشان الموقع يفتح على `:3000`.
4. ادخل `/admin` بالأدمن وغيّر كلمة السر، وحط المفاتيح من «المفاتيح والمزوّدين» (fal، ميسر، SMTP).
5. فعّل الـ deploy التلقائي: repo variable `GHERAS_DEPLOY_ENABLED=true` (الـ workflow بيكشف على لزام قبل وبعد).

## بعدين
- كل `git push` على main بيعمل deploy لغِراس بس (`.github/workflows/deploy.yml`).
- اللوجز: `journalctl -u gheras -f`
- الملفات: `/var/lib/gheras/media` — النسخ الاحتياطي يشمله هو وقاعدة `gheras_prod`.
- **نسخة احتياطية يومية** (`deploy/backup.sh`): `mongodump` لقاعدة `gheras_prod` بس (قراءة فقط، من غير ما يوقف أو يعيد تشغيل MongoDB اللي لزام بيستخدمه) + snapshot تزايدي للميديا بـ `rsync --link-dest` (كل يوم بياخد مساحة اللي اتغيّر بس)، في `/var/backups/gheras`، وبيحتفظ بآخر 14 يوم. محتاج `rsync`. التسطيب والاسترجاع مكتوبين أول وآخر السكريبت، والأفضل نسخة برّه السيرفر بـ `rclone`.
- **السعة والضغط:** الخطة الكاملة (القياسات، حدود التوازي، مواصفات السيرفر، المساحة) في `.claude/production-plan.md` على جهاز التطوير. الإعدادات المهمة من لوحة الإدارة ← إعدادات النظام: `generation.max_parallel_orders` و`render.max_parallel` و`retention.intermediate_days`.
- **تنبيه امتلاء القرص** (`deploy/disk-check.sh`): كل نص ساعة، لو القرص عدّى 85% بيكتب تحذير في سجل النظام، وبيبعت إيميل لو `GHERAS_ALERT_EMAIL` و`mail` موجودين. لوحة الإدارة كمان بتبيّن مساحة القرص في كارت «حالة المحرك».
- لما يبقى فيه دومين: سيرفر nginx منفصل لدومين غِراس + certbot لدومينه هو بس، وبعدها `PUBLIC_APP_URL` و`PUBLIC_API_URL` بـ https.
