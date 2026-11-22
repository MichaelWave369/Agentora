# Agentora R4d: atomic writeback admission and operator-only reconciliation

This change builds on merged R4c; the PhiOS R4b endpoint in draft PR #426 remains a separate, unmerged dependency. Neither integration is enabled or activated by this draft.

## Atomic dispatch claim

For the opt-in R4c path, a single conditional SQL UPDATE checks the current database status before allowing any remote POST. A winning worker atomically commits dispatching status, the complete canonical request envelope, operation ID, outcome hash and attempt timestamp. A losing worker never sends a POST. Existing held statuses dispatching and needs_reconciliation cannot be claimed. A previously written identical outcome cannot be re-claimed. R4c defaults remain off.

Crash after the claim preserves its exact envelope and hold, even across process restarts. Real SQLite tests cover two stale readers and simultaneous workers. Legacy non-R4c writeback is deliberately unchanged.

## Receipt reconciliation

After a verified PhiOS published receipt, a second conditional SQL UPDATE checks the same held state, operation ID, persisted request body and original outcome hash. If anything changed while the GET was in flight, the update fails closed rather than overwriting another worker's state. Pending and absent receipts stay held and cannot authorize a POST.

## Local operator-only command

Run the CLI explicitly with an existing absolute regular SQLite database path, run ID, and expected complete operation ID:

    PYTHONPATH=server python -m app.services.phios_writeback_reconcile_cli --database /absolute/path/agentora.sqlite --run-id 221 --expected-operation-id <64-lowercase-hex>

Without --apply this only prints held status and identity, with no network or database mutations. With --apply, and only if R4c is enabled, it invokes the existing GET-only reconciler exactly once. No web API endpoint, scheduled polling, remote server, automatic retry or secret echo is added.

Required checks: stale-session and concurrent SQLite claims; durable crash holds; exact identity on receipt update; operator CLI refusal/dry-run; R3/R4c legacy regression tests; backend Python 3.12 and 3.13; UI CI. Do not merge, deploy or activate automatically.
