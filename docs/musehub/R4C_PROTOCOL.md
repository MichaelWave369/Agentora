# Agentora R4c: durable PhiOS writeback client and GET-only reconciliation

R4c is an opt-in feature behind AGENTORA_PHIOS_WRITEBACK_V1_ENABLED=false by default.
It depends on PhiOS R4b draft PR #426, which exposes the authenticated
loopback-only /api/v1/agentora/writeback endpoint. This PR does not
merge, activate, deploy or start that PhiOS service. AGENTORA_PHIOS_ENABLED
and explicit API-key provisioning remain independently required.

## Dispatch contract

1. Agentora derives R4a's stable operation ID from session ID, task ID,
   and the complete raw outcome. The canonical, UTC-normalized envelope
   has the same frozen protocol version and 32 KiB inner-size limit.
2. Before any POST, the IntegrationRun transaction commits:
   writeback_status=dispatching, writeback_request_json holding the exact
   envelope including its timestamp and operation ID, and its associated
   original outcome fingerprint. All three new fields are added to
   existing SQLite databases by the established additive migration.
3. R4c sends exactly one request to the versioned endpoint. There is no
   fallback to the legacy routes, implicit retry or redirection to
   another host. Only http://127.0.0.1 with an explicit port is accepted.
   Authentication uses the configured X-API-Key.
4. Only HTTP 200 with matching operation ID, ok=true, state=published,
   and nonempty receipt_id and record_id counts as success.
   HTTP 202, timeout, 408/425/5xx, malformed/mismatched acknowledgement
   or network error become needs_reconciliation. Definite 4xx rejection
   remains a failed writeback.
5. Existing R3 manual/watcher holds for dispatching and needs_reconciliation
   remain active. A crash after the persisted commit still leaves the
   exact envelope and operation identity available for review.

## Operator-only reconciliation service method

IntegrationOrchestrator.reconcile_writeback_v1(run_id) loads the persisted
immutable envelope and checks it against the stored operation ID.
It calls PhiOS GET /api/v1/agentora/writeback/{operation_id} only.
GET 200 with published receipt marks the run written and records the
original outcome fingerprint. GET 202 pending or GET 404 not_found
**keeps the run held** and NEVER authorizes a new POST.

This is an internal method for an explicitly reviewed operator workflow;
no automatic polling loop, scheduler, public API route, or auto-retry
endpoint is introduced. Reconciliation requires a separate reviewed
operator entrypoint before use from the UI. For now, a held run remains
held, even if a remote receipt cannot be queried.

## Known limits for review

R3's dispatching-status guard is still a row-level check, not a
multi-process compare-and-swap; concurrent writers are not yet atomic.
This branch deliberately does not alter service startup, watcher
configuration, mission queues, or the preexisting legacy writeback mode.
Review cross-process atomic claims before enabling for multiple workers.
The PhiOS R4b side must itself be merged, explicitly configured,
launched locally and granted memory.read/write by an operator.

Acceptance: mocked single-POST and GET-only tests, durable metadata
migration, previous R3 no-retry tests, backend Python/CI, and no
unapproved changes to PhiOS or default configuration.
