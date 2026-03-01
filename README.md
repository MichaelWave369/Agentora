# Agentora v0.9.6 — Operator Mode & One-Click Deployment

Agentora is a **local-first, safety-first desktop/browser operator runtime** with team orchestration, Lattice Memory, approvals, workflows, and worker-assisted execution.

## Quickstart (recommended)

### One-click launch (Windows)
- `launch_agentora.bat`
- `launch_agentora.ps1`

Both scripts:
1. create `.venv` if needed,
2. install Python dependencies,
3. optionally install web dependencies,
4. start FastAPI + Streamlit,
5. print/open local URLs.

### Manual launch
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```
In another shell:
```bash
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

## First-run setup and doctor
- API doctor: `GET /api/system/doctor`
- bootstrap helper: `POST /api/system/bootstrap`
- version endpoint: `GET /api/system/version`
- health endpoint: `GET /api/system/health`

Checks include Python dependencies, Node/npm availability, writable paths, DB directory writability, Ollama reachability, and worker URL DNS checks.

## Operator Mode (v0.9.6)
- Stepwise and auto operator runs from workflow templates.
- Pause/resume/advance/retry/skip controls.
- Approval queue with reason + scope previews.
- Operator traces for start/request/approve/execute/fail/pause/resume/complete.
- Artifacts and action outputs tied to each run.

Primary APIs:
- `GET /api/operator/runs`
- `POST /api/operator/runs`
- `GET /api/operator/runs/{id}`
- `POST /api/operator/runs/{id}/pause`
- `POST /api/operator/runs/{id}/resume`
- `POST /api/operator/runs/{id}/advance`
- `POST /api/operator/runs/{id}/retry-step`
- `POST /api/operator/runs/{id}/skip-step`
- `GET /api/operator/workflows`
- `GET /api/operator/workflows/{id}/history`

## Deployment choices

### Native local (default)
Use the launcher scripts or manual commands above.

### Docker single-PC
```bash
docker compose --profile single-pc up --build
```

### Docker two-node profile
```bash
docker compose --profile two-pc up --build
```
This starts `agentora-main` + `agentora-worker` with separate persistent volumes.

## Approvals and guardrails
- policy-aware desktop/browser actions
- allowlisted paths/domains/apps
- retry limits and workflow duration caps
- worker fallback to local execution when unavailable
- explicit trace/audit logs for operator actions

## Release progression (v0.9.1 → v0.9.6)
- **v0.9.1**: Cortex hardening + worker routing + trace visibility.
- **v0.9.2**: Lattice Memory layers + retrieval introspection.
- **v0.9.3**: Memory explainability, conflicts, dedupe, maintenance quality.
- **v0.9.4**: Team planning + role handoffs + collaboration metrics.
- **v0.9.5**: Desktop/browser actions, approvals, workflows, action artifacts.
- **v0.9.6**: One-click launch, system doctor/bootstrap, Operator Mode control plane, operator center UX, Docker profile polish.

## Architecture summary
- **Streamlit**: primary local operator UI
- **FastAPI**: orchestration and operator APIs
- **SQLModel/SQLite**: local persistence by default
- **Ollama**: local model runtime (or mock mode)
- **Worker queue**: optional LAN/offload for heavy tasks

## Screenshots
- Placeholder hero: `docs/hero-soul-arena.svg`
- Add fresh Operator Center screenshots in a local run when available.

## Docs
- [CHANGELOG](CHANGELOG.md)
- [RELEASE_NOTES](RELEASE_NOTES.md)
- [DEPLOYMENT](DEPLOYMENT.md)
