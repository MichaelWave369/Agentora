# Troubleshooting

## Startup issues
- Run `GET /api/system/doctor` and review `next_steps`.
- Confirm DB and artifact directories are writable.

## Version mismatch
- Check `AGENTORA_VERSION` in `.env` and `GET /api/system/version` output.

## Memory/team inspector looks empty
- Use a known run ID and inspect `/api/runs/{id}` first.
- Validate retrieval at `/api/memory/runs/{id}/retrieval`.

## Approval/action failures
- Verify allowlists for path/domain/app.
- Inspect `/api/actions/history` for policy decisions and execution errors.

## Worker failures
- Verify `AGENTORA_WORKER_URLS` and DNS reachability.
- Confirm fallback behavior through `/api/workers/dispatch` and `/api/workers/jobs/{id}`.
