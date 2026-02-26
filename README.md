# Agentora

Agentora is a **local-first multi-agent orchestration studio for Ollama**. It runs privately on your machine, stores state in local SQLite, and defaults to localhost-only outbound networking.

## What it includes
- FastAPI backend with orchestration modes, template/marketplace APIs, multimodal attachments, analytics, snapshots, LAN scaffolding, and tool registry.
- React web app for run studio, marketplace, analytics, team/agent pages.
- Streamlit quick dashboard (`streamlit_app.py`) for lightweight operations.

## Safety defaults
- `AGENTORA_NETWORK_MODE=localhost_only` by default.
- No telemetry.
- Local persistence only.

## Quickstart (Server)
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r server/requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```

## Quickstart (Web)
```bash
cd web
npm ci
npm run build
npm run dev
```

## Mock mode (tests without Ollama)
```bash
AGENTORA_USE_MOCK_OLLAMA=true pytest server/tests
```

## Templates and marketplace
Built-in templates are available under `teams/` and `agents/marketplace/`. Install/update/export via marketplace/template API endpoints.

## Troubleshooting
- Ollama not running: start Ollama (`ollama serve`) and check `OLLAMA_URL`.
- No local model: `ollama pull llama3.1`.
- To bypass Ollama for tests/dev checks: set `AGENTORA_USE_MOCK_OLLAMA=true`.
