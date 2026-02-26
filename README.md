# Agentora v0.2 — Grok Mega Pack

> Local-first multi-agent orchestration studio for Ollama. Private by default, offline-friendly, localhost network guardrails.

![Agentora demo GIF placeholder](docs/demo-placeholder.gif)

## Highlights
- Offline/localhost-first orchestration studio (FastAPI + SQLite + React + Streamlit dashboard)
- Marketplace with local install/update/export of team YAML templates
- Multi-modal runs with image/PDF attachments + PDF text extraction + vision fallback routing
- Voice mode scaffold (Whisper.cpp + Piper hooks, mock mode available)
- Analytics, run metrics, cost guardrails, consensus threshold, pause/resume, cloning, LAN join-code scaffolding

## Quickstart (macOS/Linux)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn app.main:app --reload
```
```bash
cd web
npm install
npm ci
npm run build
npm run dev
```
```bash
pip install -r requirements-streamlit.txt
streamlit run streamlit_app.py
```

## Quickstart (Windows)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server/requirements.txt
$env:PYTHONPATH='server'
uvicorn app.main:app --reload
```

## Offline Promise
- No telemetry.
- Default `AGENTORA_NETWORK_MODE=localhost_only`.
- Non-localhost outbound HTTP blocked unless explicit allowlist.

## Troubleshooting
- Ollama unavailable? Set `AGENTORA_USE_MOCK_OLLAMA=true`.
- Voice unavailable? Configure `VOICE_ENABLED=true`, `WHISPER_CPP_PATH`, `PIPER_PATH`, `PIPER_VOICE_MODEL_PATH`.
- Marketplace installs are stored in `server/data/user_templates/`.

## Release
```bash
python scripts/make_release_zip.py
```
Outputs: `dist/agentora-v0.2-github-ready.zip`.
