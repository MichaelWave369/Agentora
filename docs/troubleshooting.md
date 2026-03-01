# Troubleshooting

## Startup issues
- Run `GET /api/system/doctor`.
- Ensure database/artifact directories are writable.

## Version mismatch
- Check `.env` (`AGENTORA_VERSION`) and `GET /api/system/version`.

## Memory/team inspector empty
- Confirm run exists via `/api/runs/{id}`.
- Check memory retrieval at `/api/memory/runs/{id}/retrieval`.

## Approval/action failures
- Review path/domain/app guardrails.
- Inspect `/api/actions/history` for policy and execution errors.

## Worker issues
- Verify worker URLs and DNS reachability.
- Confirm fallback behavior through `/api/workers/dispatch`.
