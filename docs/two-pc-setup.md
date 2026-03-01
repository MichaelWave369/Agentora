# Two-PC Setup

Use this mode when you want one machine as control plane and another as worker.

## Docker profile
```bash
docker compose --profile two-pc up --build
```

## Notes
- Main node runs API + UI.
- Worker node handles eligible jobs.
- Configure `AGENTORA_WORKER_URLS` and verify `/api/system/doctor` worker checks.
- If workers are unavailable, Agentora falls back to local execution when policy allows.
