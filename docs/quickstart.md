# Quickstart (v1.0.0-rc1)

## Recommended first run
1. Copy `.env.example` to `.env`.
2. Keep `AGENTORA_USE_MOCK_OLLAMA=true` for first launch.
3. Start Agentora (launcher on Windows, manual commands elsewhere).
4. Validate `System Version` and `System Doctor` in Streamlit.

## Manual commands
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

## First checks
- `GET /api/system/version` should return `1.0.0-rc1`.
- `GET /api/system/doctor` should include actionable `next_steps` when something is missing.
- `GET /api/actions/pending` and `GET /api/workflows` should be reachable.
