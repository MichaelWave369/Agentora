# Two-PC Setup (optional)

Use two-PC mode when you want one node for UI/API and another node as worker assist.

## Docker profile
```bash
docker compose --profile two-pc up --build
```

## Recommended checks
- Configure `AGENTORA_WORKER_URLS` on control-plane node.
- Validate worker reachability in `GET /api/system/doctor`.
- Verify fallback by dispatching a worker job and confirming local fallback behavior if worker is unavailable.
