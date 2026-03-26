@echo off
echo ========================================
echo   Meta Enrichment — Starting servers
echo ========================================
echo.

:: Start FastAPI backend using the existing venv
echo [1/2] Starting FastAPI backend on http://localhost:8000 ...
start "FastAPI Backend" cmd /k "call "C:\Users\M Rohith\Documents\venvs_list\venv_3.10\Scripts\activate.bat" && cd /d r:\meta_enr\app\backend && uvicorn main:app --reload --port 8000"

:: Wait a moment for the backend to start up
timeout /t 3 /nobreak >nul

:: Start React frontend
echo [2/2] Starting React frontend on http://localhost:5173 ...
start "React Frontend" cmd /k "cd /d r:\meta_enr\app\frontend && npm run dev"

echo.
echo Both servers starting. Open your browser at:
echo   http://localhost:5173
echo.
pause
