# Agentora v0.1

Agentora is a **local-first multi-agent orchestration studio for Ollama**. It helps you build teams of agents that debate, critique, synthesize, and execute with a visual workflow and YAML templates.

## Privacy Promise
- No telemetry
- Default network mode is `localhost_only`
- Intended outbound target is local Ollama (`http://localhost:11434`)
- SQLite-only local persistence

## Quickstart (macOS/Linux)
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn app.main:app --reload
```
In another terminal:
```bash
cd web
npm ci
npm run dev
```

## Quickstart (Windows PowerShell)
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r server/requirements.txt
$env:PYTHONPATH='server'
uvicorn app.main:app --reload
```
Then:
```powershell
cd web
npm ci
npm run dev
```

## Mock Mode
Set `AGENTORA_USE_MOCK_OLLAMA=true` to run deterministic orchestration and tests without Ollama.

## Built-in Templates
- TruthQuest (debate)
- CreativityForge (sequential)
- LifeOptimizer (supervisor)
- CodeCrew (sequential)
- SupportDesk (parallel)

## Troubleshooting
- Ollama not running: start `ollama serve`
- No models: run `ollama pull llama3.1`
- CI/tests: enable mock mode (`AGENTORA_USE_MOCK_OLLAMA=true`)

## Commands
```bash
AGENTORA_USE_MOCK_OLLAMA=true PYTHONPATH=server pytest server/tests
python -m compileall server/app
cd web && npm ci && npm run build
python scripts/make_release_zip.py
```

## Add a Tool
1. Implement function in `server/app/services/tools/builtins.py`
2. Register in `server/app/services/tools/registry.py`
3. Add to agent tools allowlist.

## Add a Template
1. Add a YAML file under `/teams`
2. Ensure `name`, `description`, `mode`, `agents`, `edges` are set
3. It appears via `/api/teams/templates`
