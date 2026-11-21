# R2: PhiOS writeback fallback, fail closed

## Evidence

At the R1 baseline, `PhiOSClient._post_first_success()` retried every
configured endpoint when an HTTP request raised **any exception**.
The same helper handles context-pack discovery and mission writebacks.

For writebacks, a timeout or HTTP 500 does not establish that a request
was never processed. Automatically sending it again to `/memory/write`
could duplicate a side effect. These are delivery-ambiguity states, not
proof that an endpoint is unavailable.

## R2 behavior

- Keep the existing order of endpoint candidates and unchanged successful
  JSON-object responses.
- Only try the next candidate after HTTP **404 or 405** from a previous route.
- Fail immediately on HTTP 400/401/403/409/422/429/500/503, transport
  errors/timeouts, malformed JSON, or a non-object JSON success response.
- Keep the existing `IntegrationClientError` API on ordinary HTTP/network
  failures. No authentication configuration or writeback policy changes.
- Do not make any outgoing request during tests: `httpx.post` is mocked.
- Test both Python CI versions through the existing workflow.

**Important limitation:** This stops *automatic* cross-endpoint resends
after ambiguous outcomes. It does not guarantee exactly-once delivery if
an operator retries manually or a remote server does not implement
idempotency. Future work: explicit reconciliation and shared idempotency
keys with PhiOS, agreed by both services before deployment.

## Related R1 cleanup

The legacy `server/app/services/memory.py` helpers `remember` and
`recall` are retained. The modern memory router uses capsule/maintenance
services, but this is insufficient to prove there are no external callers.
Neither `MemoryItem` nor any SQLite table or stored row is removed.

MuseHub's old score of 81/100 remains an **unverified baseline**.
Do not claim a score delta until MuseHub has imported and reanalyzed the
resulting revision.

## Validation

Local isolated `httpx` test harness: 17 parameterized cases passed.
Full integration and backend test verification must come from exact-head
GitHub CI on the draft PR. No protected ref or release is changed.
