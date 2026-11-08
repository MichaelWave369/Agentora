# Agent exchange R2: durable review-only inbox

A local opt-in library, not an enabled HTTP endpoint or network listener. The implementation lives at server/app/services/agent_exchange_durable.py.

The SQLite inbox persists incoming validated Commonline v1 message envelopes. It deduplicates exact same message IDs across restarts. A duplicate ID with different content is held as MESSAGE_ID_COLLISION. Sending contacts are operator-supplied, not included as grants in the envelope. Ingestion requires a previously authenticated sender from a trusted transport.

Pending messages remain available after restart. mark_seen is only a view receipt, never outcome acceptance, job dispatch, or permission to merge. Once full, capacity fails closed rather than evicting dedupe history. SQLite may contain private project summaries; do not expose it to public Pages, include it in repo commits, or use this as a cloud service.

Production prerequisites: cryptographically bound PHircQ peer to agent identities, authenticated operator review endpoint, lifecycle handling, secure delivery receipts, backpressure, delegation policy, and separate Commonline execution grants.

Test with PYTHONPATH=server pytest -q server/tests/test_agent_exchange_durable.py.
