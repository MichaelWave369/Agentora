@echo off
setlocal

set ROOT=%~dp0
cd /d "%ROOT%"

where py >nul 2>nul
if %errorlevel% neq 0 (
  echo [Agentora] Python launcher not found. Install Python 3.10+ and try again.
  exit /b 1
)

if not exist .venv (
  echo [Agentora] Creating virtual environment...
  py -m venv .venv || exit /b 1
)

call .venv\Scripts\activate.bat
python -m pip install -r requirements.txt || exit /b 1

where npm >nul 2>nul
if %errorlevel% equ 0 (
  if exist web\package.json (
    echo [Agentora] Installing web dependencies...
    cd web && npm ci && cd ..
  )
) else (
  echo [Agentora] npm not found. Skipping web dependency install.
)

echo [Agentora] Starting FastAPI on http://127.0.0.1:8088 ...
start "Agentora API" cmd /c "call .venv\Scripts\activate.bat && python -m uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088"

echo [Agentora] Starting Streamlit on http://127.0.0.1:8501 ...
python -m streamlit run app.py
