$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  Write-Host '[Agentora] Python not found. Install Python 3.10+.' -ForegroundColor Red
  exit 1
}

if (-not (Test-Path .venv)) {
  Write-Host '[Agentora] Creating .venv'
  python -m venv .venv
}

$py = Join-Path $root '.venv/Scripts/python.exe'
& $py -m pip install -r requirements.txt

if (Get-Command npm -ErrorAction SilentlyContinue) {
  if (Test-Path web/package.json) {
    Push-Location web
    npm ci
    Pop-Location
  }
} else {
  Write-Warning 'npm not found. Skipping web setup.'
}

Start-Process "http://127.0.0.1:8501"
Write-Host '[Agentora] Starting FastAPI and Streamlit...'
Start-Process $py -ArgumentList '-m uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088' -NoNewWindow
& $py -m streamlit run app.py
