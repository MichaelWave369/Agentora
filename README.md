# Agentora v0.9.0-rc1 — The Infinite Bloom & The World Garden

![Agentora Soul & Arena Hero](docs/hero-soul-arena.svg)

[🚀 Launch Agentora (Streamlit Primary)](http://localhost:8501)  
[🌌 Plant Your First Cosmos](http://localhost:8501)  
[📖 Share Your First Cosmos](http://localhost:8501)

Agentora is now **Streamlit-first** for the complete product experience, while FastAPI remains the local orchestration/data backend.

## What’s new in v0.9.0-rc1
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
