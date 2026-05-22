@echo off
cd /d D:\Claude\Projects\Gheras\Gheras_V3

:: Start MongoDB
start "" /min "C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe" --config "C:\data\mongod.cfg"

:: Wait for MongoDB to be ready
timeout /t 3 /nobreak >nul

:: Start Backend
start "" /min cmd /c "cd /d D:\Claude\Projects\Gheras\Gheras_V3\backend && .venv\Scripts\uvicorn.exe server:app --host 0.0.0.0 --port 8001"

:: Wait for backend to be ready
timeout /t 4 /nobreak >nul

:: Start Frontend
start "" /min cmd /c "cd /d D:\Claude\Projects\Gheras\Gheras_V3\frontend && yarn start"
