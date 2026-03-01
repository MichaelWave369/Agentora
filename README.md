# Agentora v0.9.7 — Stability, UX Polish & Public Readiness

Agentora is a **local-first operator runtime** for safe desktop/browser actions, memory-aware planning, and multi-agent execution.

This release focuses on polish: consistency, reliability, startup clarity, and public-repo readiness.

## What Agentora is today

Agentora combines:
- **Cortex runtime** for run execution and traces.
- **Lattice Memory** with retrieval introspection, layer health, lineage, and maintenance.
- **Team orchestration** with planning, handoffs, and collaboration traces.
- **Action + approval system** for guarded desktop/browser operations.
- **Workflows + Operator Mode** for stepwise and automatic automation.

## Quickstart (recommended)

### One-click launch (Windows)
Use either launcher from repo root:
- `launch_agentora.bat`
- `launch_agentora.ps1`

The launchers create `.venv`, install dependencies, and start FastAPI + Streamlit.

### Manual local launch (cross-platform)
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```
In another terminal:
```bash
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

### Easiest optional setup path
1. Start local with mock mode enabled in `.env` (default in `.env.example`).
2. Verify `/api/system/doctor` and `/api/system/version`.
3. Add Ollama and workers later (optional).

## First-run and troubleshooting endpoints
- `GET /api/system/health`
- `GET /api/system/version`
- `GET /api/system/doctor`
- `POST /api/system/bootstrap`

These report missing dependencies, model runtime availability, writable paths, and worker reachability.

## Product surface overview

### Operator Mode
- Create operator runs from workflows.
- Pause/resume/advance/retry/skip controls.
- Run history and trace visibility.
- Artifact/result output per step.

### Action & Workflow
- Approval-gated desktop/browser actions.
- Pending approval queue and history surfaces.
- Reusable workflow definitions and run history.

### Memory & Team
- Memory contexts, retrieval traces, duplicates/conflicts, lineage/neighbors.
- Team plans, role handoffs, and collaboration traces.

### Optional/experimental modules
- Cosmos / Open Cosmos / Garden / World Garden are available and treated as optional product surfaces.

## Install and deployment options

### Native local (recommended default)
Use launcher scripts or manual local run above.

### Docker single machine
```bash
docker compose --profile single-pc up --build
```

### Docker two-PC profile
```bash
docker compose --profile two-pc up --build
```
Runs `agentora-main` and `agentora-worker` with separate local volumes.

## Two-PC guidance
For LAN/offload usage and worker setup details, see:
- [docs/two-pc-setup.md](docs/two-pc-setup.md)

## API orientation
Key endpoint groups:
- `system`: health/version/doctor/bootstrap
- `operator`: run control + workflow replay history
- `actions`: pending/history/approve/deny
- `workflows`: create/run/list
- `memory`: retrieval/contexts/maintenance/introspection
- `runs/team`: run traces, plan/handoff/collaboration

## Architecture summary
- **Streamlit**: primary local operator UX
- **FastAPI**: API + orchestration runtime
- **SQLModel/SQLite**: local persistence defaults
- **Ollama**: local model runtime (optional/mock-friendly)
- **Workers**: optional remote/offload execution

## Screenshots
- Current placeholder hero: `docs/hero-soul-arena.svg`
- Add local screenshots for your environment as needed.

## Release progression
- **v0.9.1**: runtime hardening + worker routing
- **v0.9.2**: layered memory retrieval foundations
- **v0.9.3**: memory explainability and maintenance
- **v0.9.4**: team planning + collaboration metrics
- **v0.9.5**: desktop/browser actions + workflows + approvals
- **v0.9.6**: Operator Mode + one-click deployment groundwork
- **v0.9.7**: stability, UX polish, setup clarity, public readiness

## Documentation
- [docs/quickstart.md](docs/quickstart.md)
- [docs/operator-mode.md](docs/operator-mode.md)
- [docs/two-pc-setup.md](docs/two-pc-setup.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [docs/release-history.md](docs/release-history.md)
- [CHANGELOG.md](CHANGELOG.md)
- [RELEASE_NOTES.md](RELEASE_NOTES.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
