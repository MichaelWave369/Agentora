# Agentora Deployment Guide

## Runtime model
Agentora is **Streamlit-first** with FastAPI as backend orchestration.

### Mode A (recommended): Streamlit-first one-command launch
```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

This is the preferred local-first launch path.

### Mode B (advanced): backend-first HTTP launch
Terminal 1:
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```

Terminal 2:
```bash
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

## Streamlit backend modes
- `AGENTORA_STREAMLIT_MODE=auto` (default)
  - Try HTTP backend first.
  - Fall back to embedded backend automatically.
- `AGENTORA_STREAMLIT_MODE=http`
  - Force external FastAPI backend calls.
- `AGENTORA_STREAMLIT_MODE=embedded`
  - Force in-process backend via FastAPI TestClient.

## Environment variables
Copy and edit:
```bash
cp .env.example .env
```

Key variables:
- `AGENTORA_STREAMLIT_MODE`
- `AGENTORA_API_URL`
- `AGENTORA_PORT`
- `AGENTORA_DATABASE_URL`
- `AGENTORA_USE_MOCK_OLLAMA`
- `AGENTORA_USE_MOCK_VOICE`

## Ollama runtime (mock vs real)
- For smoke/demo/offline tests:
  - `AGENTORA_USE_MOCK_OLLAMA=true`
- For real inference:
  - Ensure Ollama is running at `OLLAMA_URL`
  - Ensure models configured by `OLLAMA_MODEL_DEFAULT` are installed

## Frontend scaffold build (optional)
```bash
cd web
npm ci
npm run build
```

## GitHub release archive packaging
Create a release zip (excludes caches, node_modules, venvs, local DBs, and artifacts):
```bash
scripts/create_release_archive.sh 0.9.0-rc1
```

Expected output:
- `dist/agentora-0.9.0-rc1-release.zip`

## Known limitations and caveats
- The Streamlit app is the canonical user experience; React web is optional.
- Embedded mode is convenient but not a replacement for production API hosting.
- LAN/integration features are opt-in and disabled by default in local-first setups.
