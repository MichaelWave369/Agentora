# Agentora v1.0.0 — Local Agent Operating Studio

Agentora is a **local-first, private-by-default, memory-aware agent operating studio** for chat, team orchestration, safe actions, and workflows.

## What Agentora does now

- **Local runtime:** Streamlit + FastAPI with SQLite persistence.
- **Memory-aware execution:** retrieval, contexts, lineage, duplicates/conflicts, maintenance visibility.
- **Team-capable orchestration:** plans, subgoals, handoffs, collaboration traces.
- **Safe action system:** approval-gated desktop/browser actions with policy/allowlist guardrails.
- **Workflow + Operator Mode:** run, replay, pause/resume/advance/retry/skip.
- **Optional worker assist:** offload path with graceful fallback when worker is unavailable.

## Quickstart (recommended one-PC path)

1. Copy `.env.example` to `.env`.
2. Keep mock defaults for first launch (`AGENTORA_USE_MOCK_OLLAMA=true`).
3. Start Agentora:
   - Windows: `launch_agentora.bat` or `launch_agentora.ps1`
   - macOS/Linux: manual commands below
4. Open Streamlit and verify `System Version` + `System Doctor` panels.

### Manual launch
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```
Second terminal:
```bash
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

## One PC vs Two PC

- **One PC (recommended):** local API + local Streamlit.
- **Two PC (optional):** add worker-assist node for distributed execution.
  See [docs/two-pc-setup.md](docs/two-pc-setup.md).

## Stable vs experimental

### Stable in v1.0.0
- Core run lifecycle
- Memory inspector + retrieval endpoints
- Team planning/handoffs/collaboration traces
- Action approvals/history
- Workflow run/replay
- Operator run control APIs

### Optional / experimental surfaces
- Cosmos / Open Cosmos / Garden / World Garden remain optional and labeled accordingly.

## Core API groups

- `system`: health/version/doctor/bootstrap
- `runs`: run lifecycle, traces, team/collaboration views
- `actions`: pending queue, approve/deny, history
- `workflows`: create/run/replay history
- `operator`: run controls and operator history
- `memory`: retrieval, contexts, lineage, maintenance
- `workers`: register/heartbeat/dispatch/job status

## Architecture summary

- **Streamlit:** primary operator UI
- **FastAPI:** orchestration and runtime APIs
- **SQLModel/SQLite:** local data storage by default
- **Ollama:** optional local model runtime (mock-friendly startup)
- **Worker queue:** optional offload/fallback execution

## Screenshots

- Placeholder hero asset: `docs/hero-soul-arena.svg`
- Capture environment-specific local screenshots for release/demo artifacts.

## Known limitations

- Some advanced actions depend on local desktop/browser capability availability.
- Worker mode requires configured/reachable worker URLs.
- Optional modules (Cosmos/Garden family) are not required for core GA operation.

## Documentation

- [docs/quickstart.md](docs/quickstart.md)
- [docs/operator-mode.md](docs/operator-mode.md)
- [docs/two-pc-setup.md](docs/two-pc-setup.md)
- [docs/troubleshooting.md](docs/troubleshooting.md)
- [docs/release-history.md](docs/release-history.md)
- [CHANGELOG.md](CHANGELOG.md)
- [RELEASE_NOTES.md](RELEASE_NOTES.md)
- [DEPLOYMENT.md](DEPLOYMENT.md)
