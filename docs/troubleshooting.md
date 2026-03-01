# Troubleshooting

## App starts but data is missing
- Check `/api/system/health` and `/api/system/doctor`.
- Confirm database path is writable.

## Models unavailable
- Enable mock mode (`AGENTORA_USE_MOCK_OLLAMA=true`) for local/offline startup.
- Verify `OLLAMA_URL` and local model pull status.

## Action failures
- Inspect path/domain/app allowlists.
- Review action approval status and denial reasons in `/api/actions/history`.

## Worker issues
- Verify worker URLs and connectivity.
- Review doctor output and retry local fallback path.
