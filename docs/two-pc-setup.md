# Two-PC Setup (optional)

Use two-PC mode when one machine hosts UI/API and another provides worker assist.

## Docker profile
```bash
docker compose --profile two-pc up --build
```

## Recommended checks
- Set `AGENTORA_WORKER_URLS` on control-plane node.
- Verify worker diagnostics via `GET /api/system/doctor`.
- Validate worker path/fallback using `/api/workers/dispatch` and `/api/workers/jobs/{id}`.
