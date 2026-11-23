@echo off
cd /d "%~dp0"
start "Clinthinker backend" cmd /k "cd backend && .venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
start "Clinthinker frontend" cmd /k "cd frontend && npm run dev"
timeout /t 8 >nul
start http://localhost:5173