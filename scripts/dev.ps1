python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server/requirements.txt
Start-Job -ScriptBlock { $env:PYTHONPATH='server'; uvicorn app.main:app --host 0.0.0.0 --port 8000 }
Set-Location web
npm ci
npm run dev -- --host 0.0.0.0 --port 5173
