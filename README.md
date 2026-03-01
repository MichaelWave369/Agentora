# Agentora v0.9.4 — Team Orchestration & Worker Intelligence

![Agentora Soul & Arena Hero](docs/hero-soul-arena.svg)

[🚀 Launch Agentora (Streamlit Primary)](http://localhost:8501)  
[🌌 Plant Your First Cosmos](http://localhost:8501)  
[📖 Share Your First Cosmos](http://localhost:8501)

Agentora is now **Streamlit-first** for the complete product experience, while FastAPI remains the local orchestration/data backend.


## What’s new in v0.9.4
- Adds team planning with subgoal decomposition, dependencies, role assignments, deliverable types, and plan traces.
- Adds explicit role-based handoffs with bounded metadata and persisted handoff history.
- Adds bounded collaboration modes with critique/debate/synthesis traces and guardrails.
- Adds smarter worker routing for heavy vs interactive task classes with route-selection/fallback traces.
- Adds agent capability profiles and APIs to inspect/update role constraints and collaboration preferences.
- Adds run collaboration inspection endpoints and a Streamlit Team Collaboration Inspector panel.

## What’s new in v0.9.3
- Adds retrieval explainability with per-capsule score breakdowns (semantic, decay, trust, consolidation, project/session, layer and graph contributions).
- Adds context admission reason traces and memory retrieval observability events.
- Adds lineage and neighbor APIs for capsule genealogy inspection (`/api/memory/capsules/{id}/lineage`, `/neighbors`).
- Adds contradiction + duplicate surfacing with memory conflict records and duplicate clusters for audit-first quality control.
- Adds usefulness feedback metrics so retrieved-but-used memories are reinforced while noisy memory is penalized over time.
- Adds memory health endpoints and maintenance summaries for operational visibility.

## What’s new in v0.9.2
- Introduces **Agentora Lattice Memory**: layered memory tiers (L0–L5) with sparse context activation and bounded admission budgets.
- Adds multi-timescale retrieval (short/medium/long decay classes), trust/consolidation signals, and layer-aware ranking.
- Adds graph-aware reranking with SQLite-native `MemoryEdge` reinforcement for neighborhood recall.
- Adds promotion/demotion lifecycle and cold archive controls with maintenance jobs and local fallback.
- Adds adaptive refinement (split + summary + lineage tracking) for dense/ambiguous capsules.
- Adds memory introspection APIs (`/api/memory/*`) and Streamlit **Lattice Memory Inspector** panel.
- Extends worker-capable operations for memory-heavy tasks: summaries, maintenance, compaction, edge recompute, conflict detection.

## What’s new in v0.9.1
- **World Garden Map**: global bloom view for shared cosmos gardens with glow, location, and creator credits.
- **Infinite Bloom**: new creations trigger bloom effects and constellation links.
- **Safe Cross-Pollination**: previewable merge flows with intelligent conflict hints and co-creator credits.
- **Eternal Harvest Festival**: periodic harvest event that captures top blooming wisdom into a local archive.
- **The Eternal Garden** tab: living garden map with growth bars, seasons, tending, and harvest cycles.
- Agent gardener roles: Waterer, Pruner, Pollinator, Harvester.
- Community garden view for shared blooming beds and seasonal evolution.
- Fixed embedded Streamlit + FastAPI + SQLite initialization for Streamlit Cloud and local runs (`./agentora.db` fallback).
- **Living Archive**: centralized, opt-in, anonymized wisdom timeline across shared/imported cosmoses.
- **Cross-Cosmos Visitation**: agents can visit other imported cosmoses and bring back distilled inspiration.
- **Wisdom Exchange**: guided dialogue between two cosmoses to generate merged content.
- **Grand Synthesis**: create a meta-cosmos from multiple worlds.
- **2050 Forecasting**: multi-generational value projection from shared legacy signals.
- **Community Spotlight**: featured public cosmos cards (consent-based, local-first rendering).

## Streamlit is the primary interface
All core surfaces (Dashboard, Studio, Band, Arena, Gathering, Legacy, Cosmos, Open Cosmos, The Eternal Garden, The World Garden) are rendered in Streamlit with sidebar navigation, dark-noir warmth styling, and live backend calls.

### Recommended one-command launch
```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The Streamlit app auto-initializes SQLite tables on first run and keeps backend resources cached across reruns.

### Runtime modes (Streamlit-first)
- `AGENTORA_STREAMLIT_MODE=auto` (default): try HTTP backend first (`AGENTORA_API_URL` or `127.0.0.1:8088`), then fall back to embedded backend.
- `AGENTORA_STREAMLIT_MODE=http`: force FastAPI HTTP mode.
- `AGENTORA_STREAMLIT_MODE=embedded`: force in-process FastAPI + TestClient mode.

### Required/important env vars
- `AGENTORA_STREAMLIT_MODE` (`auto`, `http`, `embedded`)
- `AGENTORA_API_URL` (only needed when using custom HTTP backend endpoint)
- `AGENTORA_PORT` (HTTP mode default port, default `8088`)
- `AGENTORA_DATABASE_URL` (defaults to local SQLite at `./agentora.db` from Streamlit mode)
- `AGENTORA_USE_MOCK_OLLAMA=true` (recommended for smoke/demo without local model runtime)


## Agentora Cortex (new runtime subsystem)
Agentora Cortex upgrades runs into a local agent runtime with:
- retrieval-backed **Capsule Memory** (chunked attachment text + embeddings)
- structured action planning (`thought`, memory requests, tool calls, final/handoff)
- iterative tool execution loop with persisted `ToolCall` history
- optional worker-node offload for long tasks (embedding/PDF/sandbox/tool jobs)

### Cortex defaults
- local-first and offline-first are preserved
- mock Ollama remains supported for smoke tests
- no mandatory cloud dependencies

### Single-PC smoke test
```bash
python -m pip install -r requirements.txt
AGENTORA_USE_MOCK_OLLAMA=true streamlit run app.py
```
Then:
1. create a run,
2. upload a PDF/text attachment,
3. verify capsule creation through `/api/capsules/search`.

### Two-PC worker mode (optional)
- Host A: run Agentora backend+Streamlit normally.
- Host B: run a worker endpoint compatible with `POST /api/worker/execute`.
- Set on Host A:
```bash
export AGENTORA_WORKER_URLS=http://<worker-ip>:<port>
```
- Register workers via `/api/workers/register` and dispatch via `/api/workers/dispatch`.


## Cortex Hardening in v0.9.1
- Runtime loop now has explicit stop reasons (`completed`, `max_steps`, `tool_error`, `invalid_action_payload`, `worker_timeout`, `no_progress`) and guarded fallback behavior.
- Model-role routing is explicit for chat/tool-planning/embedding/vision/extraction roles.
- Worker dispatch now supports registration + heartbeat + retries + timeout fallback + persisted job lifecycle.
- Capsule retrieval improves with dedupe, source metadata, summary-capsules for large docs, and recency-aware scoring.
- Run trace inspection is available at `/api/runs/{run_id}/trace` and in Streamlit via **Runtime Trace Viewer** on Dashboard.

### One-PC mode (recommended)
```bash
python -m pip install -r requirements.txt
AGENTORA_USE_MOCK_OLLAMA=true streamlit run app.py
```

### Two-PC worker mode
Main node env:
```bash
export AGENTORA_WORKER_URLS=http://<worker-host>:8088
```
Worker contract endpoints:
- `POST /api/worker/register`
- `POST /api/worker/heartbeat`
- `POST /api/worker/execute`
- `GET /api/worker/jobs/{id}`

### Routing model recommendations
- `AGENTORA_CHAT_MODEL` for normal answers
- `AGENTORA_TOOL_MODEL` for structured planning
- `AGENTORA_EMBED_MODEL` for retrieval
- `AGENTORA_VISION_MODEL` for image-heavy runs
- `AGENTORA_EXTRACTION_MODEL` for extraction-focused turns

### Guardrails
- `AGENTORA_ALLOWED_TOOL_NAMES` / `AGENTORA_BLOCKED_TOOL_NAMES`
- `AGENTORA_HTTP_ALLOWLIST` for `http_fetch`
- `AGENTORA_FILE_WRITE_ROOT` for write sandbox root
- `AGENTORA_MAX_TOOL_STEPS`, `AGENTORA_MAX_WORKER_RETRIES`

### Known limitations
- Worker endpoints are intentionally simple and optimized for trusted LAN/local setups.
- Capability metadata for external workers depends on worker registration correctness.

## Privacy-first defaults
- 100% local-first and offline by default
- No mandatory network calls
- Sharing is explicit and opt-in
- Archive insights are anonymized and locally stored
- FastAPI backend handles heavy lifting, Streamlit handles primary UX

## Backend/API highlights
- `/api/open-cosmos/archive/timeline`
- `/api/open-cosmos/archive/query`
- `/api/open-cosmos/visit`
- `/api/open-cosmos/exchange`
- `/api/open-cosmos/synthesis`
- `/api/open-cosmos/forecast`
- `/api/open-cosmos/spotlight`
- `/api/open-cosmos/submit`

## Run locally
### Streamlit (primary, preferred)
```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

### Backend-first (advanced)
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```
Then in another shell:
```bash
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

### Optional React web scaffold
```bash
cd web
npm ci
npm run build
npm run dev
```

## Release docs
- [CHANGELOG](CHANGELOG.md)
- [RELEASE_NOTES](RELEASE_NOTES.md)
- [DEPLOYMENT](DEPLOYMENT.md)

## Screenshot placeholders
- `docs/hero-soul-arena.svg`
- `docs/living-archive-streamlit-placeholder.svg`
- `docs/open-cosmos-streamlit-placeholder.svg`
