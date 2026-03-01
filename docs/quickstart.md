# Quickstart (v1.0.0)

## Recommended first run
1. Copy `.env.example` to `.env`.
2. Keep `AGENTORA_USE_MOCK_OLLAMA=true` for first startup.
3. Start Agentora (Windows launchers or manual commands).
4. In Streamlit, verify `System Version` and `System Doctor`.

## Manual commands
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

## First checks
- `GET /api/system/version` returns `1.0.0`.
- `GET /api/system/doctor` provides readiness details.
- `GET /api/actions/pending` and `GET /api/workflows` are reachable.
