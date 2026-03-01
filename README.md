# Agentora v1.0.0-rc1 — Scope Freeze, Final Polish & Launch Readiness

Agentora is a **local-first, private-by-default, memory-aware operating studio** for agent teams, safe actions, and repeatable workflows.

This release candidate is a stabilization pass before `v1.0.0`: consistency, reliability, setup clarity, and launch readiness.

## What Agentora can do today

- **Local chat + memory inspection** (retrieval, contexts, lineage, duplicates/conflicts).
- **Team collaboration** (plan/subgoals/handoffs/collaboration trace).
- **Safe action approvals** for desktop/browser actions with allowlists and policy controls.
- **Workflow execution and replay** with history surfaces.
- **Operator Mode** with pause/resume/advance/retry/skip controls.
- **Optional worker assist** with fallback to local execution.

## Quickstart (recommended)

### Easiest one-PC path
1. Copy `.env.example` to `.env`.
2. Keep mock defaults for first run (`AGENTORA_USE_MOCK_OLLAMA=true`).
3. Start with:
   - Windows: `launch_agentora.bat` or `launch_agentora.ps1`
   - macOS/Linux: manual commands below
4. In UI, open `System Version` and `System Doctor` to verify readiness.

### Manual launch (cross-platform)
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```
Second terminal:
```bash
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

## One PC vs Two PC guidance

- **One PC (recommended default):** local API + local Streamlit.
- **Two PC (optional):** control plane + worker node for heavy/remote assist.
  See [docs/two-pc-setup.md](docs/two-pc-setup.md).

## First-run endpoints

- `GET /api/system/health`
- `GET /api/system/version`
- `GET /api/system/doctor`
- `POST /api/system/bootstrap`

## Core demo flows (v1.0 RC)

1. **Flow A — Local chat + memory:** run request, inspect `/api/memory/runs/{id}/retrieval` and contexts.
2. **Flow B — Team collaboration:** inspect `/api/runs/{id}/plan`, `/handoffs`, `/collaboration-trace`.
3. **Flow C — Safe approvals:** create action, approve/deny via `/api/actions/{id}/approve|deny`, inspect `/api/actions/history`.
4. **Flow D — Workflow replay:** create workflow, run it, inspect `/api/workflows/{id}/runs`, run again for replay history.
5. **Flow E — Worker assist/fallback:** dispatch worker-eligible job and verify fallback behavior if worker unavailable.

## API overview

- `system`: health/version/doctor/bootstrap
- `runs`: run lifecycle + trace + team/collaboration surfaces
- `actions`: pending queue, approvals, execution history
- `workflows`: create/run/clone/history
- `operator`: run controls + workflow history
- `memory`: retrieval, trace, lineage, maintenance
- `workers`: register/heartbeat/dispatch/job status

## Architecture

- **Streamlit**: primary local UX and inspectors
- **FastAPI**: API + orchestration runtime
- **SQLModel/SQLite**: local persistence defaults
- **Ollama**: optional local model runtime (mock-friendly startup)
- **Worker queue**: optional assist/offload routing

## Optional and experimental surfaces

- Cosmos / Open Cosmos / Garden / World Garden remain optional and labeled experimental where applicable.

## Known limitations (RC)

- FastAPI startup currently uses legacy startup event hooks (deprecation warning only).
- Some advanced flows depend on optional local capabilities (Ollama, workers, desktop/browser tooling).
- Web UI build is supported; Streamlit is still the primary operator surface.

## Screenshots

- Placeholder hero: `docs/hero-soul-arena.svg`
- Current Streamlit dashboard screenshot can be captured locally for your environment.

## Release progression

- `v0.9.1` → `v0.9.7`: runtime, memory, team, action, workflow, operator, and polish groundwork.
- `v1.0.0-rc1`: scope freeze, consistency pass, core flow hardening, launch-candidate readiness.

## Docs

- [docs/quickstart.md](docs/quickstart.md)
- [docs/operator-mode.md](docs/operator-mode.md)
- [docs/two-pc-setup.md](docs/two-pc-setup.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [docs/release-history.md](docs/release-history.md)
- [CHANGELOG.md](CHANGELOG.md)
- [RELEASE_NOTES.md](RELEASE_NOTES.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
