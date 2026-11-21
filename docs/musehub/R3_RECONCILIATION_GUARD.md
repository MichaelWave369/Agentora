# R3: Reconciliation hold for uncertain PhiOS writebacks

**Scope:** Agentora only, no PhiOS schema/API changes, no live external writes.

## Failure mode (before R3)

R2 stopped the same HTTP request from being sent automatically to a
second endpoint after ambiguous failures. However, the orchestrator still
recorded every writeback exception as `failed` and allowed later manual or
watcher retries. A timeout or remote 5xx could happen after PhiOS accepted
the write: resending it could duplicate the recorded memory.

## New conservative client classification

`IntegrationDeliveryUncertain` extends the existing
`IntegrationClientError` contract. The PhiOS client marks HTTP 408, 425,
5xx, request/transport exceptions, invalid response JSON, and successful
non-object JSON responses as potentially already delivered. The normal
`IntegrationClientError` remains for definite rejections (e.g. 401, 404,
405, 422) and disabled integration. Any unexpected client exception is
also treated as uncertain at the orchestrator boundary.

## Durable writeback states, no migration

Agentora already stores `IntegrationRun.writeback_status` as text. R3
adds two internal values without altering the database schema:

- `dispatching`: committed immediately **before** contacting PhiOS.
  If the process exits unexpectedly, subsequent calls hold for review.
- `needs_reconciliation`: request outcome unknown, including timeout
  and server-side ambiguity. Watcher, manual and MCP routes refuse to
  resend until external evidence establishes the outcome.

A conclusively rejected write remains `failed`, and normal success is
`written`. If a successful manual write is repeated with the exact same
`outcome_fingerprint`, the second call is a no-op, not a second POST.
A changed outcome remains eligible for a new write *when no hold exists*.

## Operator reconciliation (no unsafe reset endpoint in R3)

1. Read the Agentora integration run and timeline; locate its PhiOS
   `session_id`, `task_id` (job ID or run-ID fallback), last attempt,
   and outcome contents.
2. Query the authoritative PhiOS history using an existing approved,
   authenticated read mechanism if one is available. Confirm whether
   the exact operation was applied or not. Do not infer absence from
   a transient network failure.
3. Preserve the evidence and ask for an explicitly reviewed reconciliation
   procedure. **R3 deliberately provides no public status-reset endpoint.**
4. Do not force a resend, alter the SQLite row, or merge this work
   merely to silence a health score.

## Limitations and future cross-repo contract

These checks prevent sequential retries inside Agentora. They do NOT
provide cross-process transactional exclusion, remote deduplication, or
exactly-once semantics. Concurrent requests from different workers can
still race. End-to-end delivery needs an authenticated PhiOS endpoint
supporting stable idempotency keys, operation-status reads, and an
operator-approved reconciliation action with audit evidence.

The legacy `remember` and `recall` helpers are deliberately untouched:
the modern capsule memory router does not import them, but public callers
have not been exhaustively ruled out. Keep the SQLite `MemoryItem` model
and previous R1 tests intact.

## Validation

R3 includes mocked HTTP client classification tests, a stubbed persistent
writeback lifecycle, blocked manual and watcher resends, duplicate-no-op,
known rejection retry, and interruption-state checks. The exact-head PR
CI must pass in Python 3.12/3.13 before review. MuseHub scoring is
separate and no improvement is claimed here.
