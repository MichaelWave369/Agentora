# Agentora v0.5 — Cosmos & Eternal

![Agentora Soul & Arena Hero](docs/hero-soul-arena.svg)

[🚀 Try It Now: MicTek Rebellion](http://localhost:5173/band-mode)  
[🏠 Try Gathering](http://localhost:5173/gathering-mode)  
[🌳 Create Your First Legacy Agent](http://localhost:5173/legacy-mode)  
[🌌 Plant Your First Cosmos](http://localhost:5173/cosmos-mode)

Agentora is a local-first multi-agent orchestration studio for Ollama with six modes:
- **Studio**: voice/song generation with personas, stems, waveform, and Sing flow
- **Band**: iterative music crews (beat/melody/bass/vocals/mix) with track exports
- **Arena**: truth-seeking debate matches/tournaments with scoring and reports
- **Gathering**: family/friends LAN sessions with room codes, shared crews, and memory vault
- **Legacy**: persistent agent souls, family trees, evolution points, heirloom exports
- **Cosmos**: personal universes, branching timelines, cosmic reflection, eternal seed export

## Privacy & safety defaults
- Local SQLite + local artifact storage only
- No telemetry
- Default network mode is localhost-only
- Mock modes (`AGENTORA_USE_MOCK_OLLAMA`, `AGENTORA_USE_MOCK_VOICE`) for offline tests
- No cloud accounts required

## Cosmos highlights
- Create persistent worlds from real memories, dreams, sci-fi ideas, or family stories
- Galaxy map where stars represent chapters/events linked to family legacy roots
- Multi-timeline branching (`What if I moved to Chico in 2025?`) with side-by-side evolution
- Cosmic Reflection / Oracle mode with warmth-controlled hopeful vs realistic tone
- Eternal Archive search across songs, debates, and soul companions
- Heirloom 2.0 export: `Eternal Seed` zip for full lineage + cosmos continuation

## Legacy highlights
- Persistent Soul Files for every agent (`server/data/legacy/souls/*.soul.json`)
- Evolution points and trait growth (humor/truth/creativity/empathy)
- Agent family trees with child/fork creation and trait inheritance
- Daily reflection + nurture mechanics
- Heirloom export (`/api/legacy/heirloom/{agent_id}.zip`) for pass-it-on archives

## Streamlit Cloud
- Root `requirements.txt` includes server dependencies for embedded mode.
- `streamlit_app.py` supports:
  - `AGENTORA_STREAMLIT_MODE=auto|http|embedded`
  - optional `AGENTORA_API_URL`
  - automatic embedded fallback when HTTP API is unavailable

## Run locally
### Server
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
```

### Web
```bash
cd web
npm ci
npm run build
npm run dev
```

### Streamlit
```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Optional voice/music deps
- Piper and Whisper.cpp are optional hooks via env vars; mock mode works without binaries.
- Heavy musicgen models are intentionally not bundled in default install; a plugin hook approach is used.
- ffmpeg is optional (WAV-first workflow still works without it).

## Screenshot placeholders
- `docs/hero-soul-arena.svg` (current hero)
- `docs/legacy-tree-placeholder.svg` (optional)
- `docs/cosmos-map-placeholder.svg` (optional)

## Dev scripts
- `scripts/dev.sh`
- `scripts/dev.ps1`
- `scripts/make_release_zip.py`
