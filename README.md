# Agentora v0.3 — Together (Family & Community Edition)

![Agentora Soul & Arena Hero](docs/hero-soul-arena.svg)

[🚀 Try It Now: MicTek Rebellion](http://localhost:5173/band-mode)  
[🏠 Try Gathering](http://localhost:5173/gathering-mode)

Agentora is a local-first multi-agent orchestration studio for Ollama with four modes:
- **Studio**: voice/song generation with personas, stems, waveform, and Sing flow
- **Band**: iterative music crews (beat/melody/bass/vocals/mix) with track exports
- **Arena**: truth-seeking debate matches/tournaments with scoring and reports
- **Gathering**: family/friends LAN sessions with room codes, shared crews, and memory vault

## Privacy & safety defaults
- Local SQLite + local artifact storage only
- No telemetry
- Default network mode is localhost-only
- Mock modes (`AGENTORA_USE_MOCK_OLLAMA`, `AGENTORA_USE_MOCK_VOICE`) for offline tests
- No cloud accounts required

## Streamlit Cloud
- Root `requirements.txt` includes server dependencies for embedded mode.
- `streamlit_app.py` supports:
  - `AGENTORA_STREAMLIT_MODE=auto|http|embedded`
  - optional `AGENTORA_API_URL`
  - automatic embedded fallback when HTTP API is unavailable

## Gathering highlights
- LAN discovery + 4-digit room code join fallback
- Warm neon living-room table visualization for participants
- Shared jam/debate flow with live events and local-only memory import (consent-gated)
- Mutual-aid templates included by default

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

## Dev scripts
- `scripts/dev.sh`
- `scripts/dev.ps1`
- `scripts/make_release_zip.py`
