# Quickstart (v0.9.7)

## Recommended path
1. Copy `.env.example` to `.env`.
2. Run `launch_agentora.bat` or `launch_agentora.ps1` on Windows, or manual commands on macOS/Linux.
3. Open Streamlit UI and verify `System Version` + `System Doctor` panels.

## Manual commands
```bash
python -m pip install -r requirements.txt
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088
AGENTORA_STREAMLIT_MODE=http AGENTORA_API_URL=http://127.0.0.1:8088 streamlit run app.py
```

## First checks
- `GET /api/system/health`
- `GET /api/system/version`
- `GET /api/system/doctor`

## Optional after first successful launch
- Configure Ollama models.
- Add worker URLs for offload.
- Tune approvals and allowlists.
