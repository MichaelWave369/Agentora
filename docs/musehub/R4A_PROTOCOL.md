# Agentora / PhiOS R4a: Operation identity contract (inactive)

The same `phios.agentora.writeback.v1` SHA-256 operation identity is now
specified and tested independently in both Agentora and PhiOS.

- Agentora: `server/app/integrations/writeback_idempotency.py`
- PhiOS: `phios/memory/agentora_writeback.py` (PhiOS draft PR #425)
- Fixed test vector:
  `056f70f4e94787b3aa2f96e82fd93bd173f1b92582deaec4c2f12e698431ba06`

Logical identity is the canonical JSON object with:
`session_id`, `task_id`, and the complete `raw_payload.outcome`.
The hash uses SHA-256 over UTF-8 bytes of the protocol version plus one
newline, followed by canonical compact sorted-key JSON.

Notes and tags are part of the complete immutable writeback record but not
the identity: changing them under the same operation ID is a **conflict**
on the PhiOS store, not a new submission. A new outcome earns a new ID.

Stable `created_at_utc` must be an explicit timezone-aware timestamp and
be reused across retries. The canonical envelope is capped at 32 KiB.

**R4a is deliberately not activated.** No HTTP requests are sent, no new
port is exposed, no PhiOS permissions are granted, and Agentora's current
writeback flow is unchanged. The next reviewed stage must add an
authenticated, loopback-only transport, a read-only operation-status
endpoint, and explicit opt-in on both sides. It must also preserve R3
reconciliation holds until a remote published receipt is verified.

Do not claim that cross-service exactly-once delivery exists before
those end-to-end tests pass. The existing 81/100 MuseHub score has not
been freshly reanalyzed against these changes.
