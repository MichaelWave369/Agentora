# Agentora v0.7 — Wisdom Eternal & The Living Archive

![Agentora Soul & Arena Hero](docs/hero-soul-arena.svg)

[🚀 Launch Agentora (Streamlit Primary)](http://localhost:8501)  
[🌌 Plant Your First Cosmos](http://localhost:8501)  
[📖 Share Your First Cosmos](http://localhost:8501)

Agentora is now **Streamlit-first** for the complete product experience, while FastAPI remains the local orchestration/data backend.

## What’s new in v0.7
- **Living Archive**: centralized, opt-in, anonymized wisdom timeline across shared/imported cosmoses.
- **Cross-Cosmos Visitation**: agents can visit other imported cosmoses and bring back distilled inspiration.
- **Wisdom Exchange**: guided dialogue between two cosmoses to generate merged content.
- **Grand Synthesis**: create a meta-cosmos from multiple worlds.
- **2050 Forecasting**: multi-generational value projection from shared legacy signals.
- **Community Spotlight**: featured public cosmos cards (consent-based, local-first rendering).

## Streamlit is the primary interface
All core surfaces (Dashboard, Studio, Band, Arena, Gathering, Legacy, Cosmos, Open Cosmos) are rendered in Streamlit with sidebar navigation, dark-noir warmth styling, and live backend calls.

### Recommended one-command launch
```bash
streamlit run app.py
```

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
### Backend
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```

### Streamlit (primary)
```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

### Optional React web scaffold
```bash
cd web
npm ci
npm run build
npm run dev
```

## Screenshot placeholders
- `docs/hero-soul-arena.svg`
- `docs/living-archive-streamlit-placeholder.svg`
- `docs/open-cosmos-streamlit-placeholder.svg`
