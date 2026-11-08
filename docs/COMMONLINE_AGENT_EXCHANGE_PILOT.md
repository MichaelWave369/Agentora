# Commonline agent exchange pilot: review-only Agentora intake

The optional agent exchange service implements **commonline.agent-exchange.v1** validation and an operator-configured, in-process review-only inbox. It is not automatically mounted as an API endpoint; no background agent is launched. It intentionally cannot dispatch workers, grant tool permissions, or merge PRs.

The inbound contract has seven advisory kinds and exact sender/recipient IDs, message/thread IDs, UTC timestamps, a bounded summary, and optional opaque contextRef/sourceSha. Validation does not prove the sender's identity. **ReviewOnlyInbox.receive** therefore requires an independently authenticated_sender and an explicitly configured sender-to-recipient allowlist.

The pilot rejects wrong senders, unknown contact paths, stale or forged-authority envelopes, duplicates and overload. It queues a handoff proposal for manual review only. The in-memory replay record is not durable across process restart, so this is not production ready.

## Handoff plan

1. Commonline issues scoped offers and controls outcome acceptance and external-effect grants.
2. PHircQ authenticates and delivers signed frames using its existing governed peer-session path (future adapter).
3. Agentora validates and places offers in a persistent, scoped inbox (future implementation of this interface).
4. Human or authorized reviewer promotes one exact reviewed artifact using existing Agentora approvals and AgentCeption execution.
5. RepoNerve provides HEAD-pinned evidence; PhiMadaPrime displays privacy-filtered status.

No agent conversation, response, or proposal is an authority grant. A sourceSha field only declares a revision, which must be independently verified before acting.

Run the isolated tests from the server package context:

python -m unittest server/tests/test_agent_exchange.py

The full Agentora suite must still pass before merging.
