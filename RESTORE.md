# Gheras — Local Restore Guide

## Bundle contents
```
source/             — full backend + frontend source code (.git, .venv, node_modules excluded)
mongo-bundle.zip    — Mongo JSONL per collection + META.json
uploads.zip         — every binary asset registered in db.files
env-template.zip    — backend/.env + frontend/.env scaffolds (every secret REDACTED)
RESTORE.md          — this file
```

## 1. Prerequisites
- Python 3.11+
- Node 18+ / Yarn
- MongoDB 6+ (`docker run -d -p 27017:27017 mongo:6`)
- ffmpeg (`sudo apt install ffmpeg` or `brew install ffmpeg`)

## 2. Extract the source
```bash
unzip gheras-everything-*.zip -d gheras-local
cd gheras-local/source
```

## 3. Restore MongoDB
```bash
unzip ../mongo-bundle.zip -d ../mongo-restore
cd backend
python scripts/import_mongo_json.py \
    --src ../../mongo-restore \
    --mongo-url "mongodb://localhost:27017" \
    --db gheras_local
```

## 4. Restore uploads (optional — only if going fully offline)
```bash
mkdir -p backend/uploads
cd backend/uploads
unzip ../../../uploads.zip
```

## 5. Write the .env files
```bash
unzip ../../env-template.zip
cp backend/.env  backend/.env.real
cp frontend/.env frontend/.env.real
# Edit each .env.real:
#   openssl rand -hex 32                  →  JWT_SECRET
#   python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())' → ENCRYPTION_KEY
#   then paste real OPENAI_API_KEY / FAL_KEY_* / etc.
mv backend/.env.real  backend/.env
mv frontend/.env.real frontend/.env
```

## 6. Boot
```bash
cd backend && pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# In another terminal:
cd ../frontend && yarn install && yarn start
```

## 7. Verify
- http://localhost:3000 — login admin@gheras.com (password from ADMIN_PASSWORD in backend/.env)
- /admin/secrets shows your keys
- /admin/stage-control shows 11 stages
- `cd backend && pytest tests/test_phase_n_*.py -q` — all green

## 8. Caveats
- EMERGENT_LLM_KEY does NOT work outside Emergent. Replace each call-site
  with provider-native keys.
- If you keep secret_overrides collection, you also need the production
  ENCRYPTION_KEY. Email support@emergent.sh with your Job ID, or drop the
  collection and re-enter keys via /admin/secrets.
