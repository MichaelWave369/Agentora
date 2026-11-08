# Agent Exchange R3: signed PHircQ frame to durable Agentora inbox

**Local opt-in pilot.** This connects the previously merged PHircQ signed peer message and Agentora's durable review inbox without opening an HTTP port or trusting a browser-supplied sender field.

## Security boundary

- A PHircQ recipient must first accept an `agent.exchange` frame through a trusted `PeerSession`, which verifies its ECDSA P-256 signature and pinned peer identity.
- The `onAgentExchange` callback now preserves the **original signed frame**. `serializeSignedExchangeBundle(...)` exports it without its private key. This serialization does NOT assert that the object was verified; always export from the verified callback.
- Agentora independently validates the signed frame's WebCrypto 64-byte `r||s` P-256 signature, a *separately configured* peer fingerprint, the sender/recipient agent mapping, message bounds, timestamps and advisory-only rights.
- Only after verification does the original Commonline v1 message enter Agentora's existing SQLite inbox with durable replay/collision handling. The result is **REVIEW_PENDING**, never a job launch, merge, accepted artifact or execution grant.

## Local trust policy

Create an operator-owned JSON file OUTSIDE source control, such as `~/.agentora/peer-trust.json`, matching this shape (replace the example fingerprint using the peer's verified, out-of-band key fingerprint):

```json
{
  "schema": "agentora.phircq.trust.v1",
  "peers": [{
    "peerId": "peer-btm",
    "fingerprint": "64_lowercase_hex_characters_from_verified_peer",
    "senderAgent": "agent:btm",
    "recipientAgent": "agent:overstrings"
  }]
}
```

On POSIX, trust policy must be owned by the current account and mode 0600 (for example, `chmod 600 ~/.agentora/peer-trust.json`). This is a manually pinned trust file, **not** automatic trust-on-first-use. Never use an incoming bundle to populate or modify this file.

## Commands (local operator console)

```bash
PYTHONPATH=server python -m app.services.agent_exchange_bridge_cli import \
  --trust ~/.agentora/peer-trust.json \
  --db ~/.agentora/agent-exchange.sqlite3 \
  --bundle /path/to/verified-phircq-bundle.json

PYTHONPATH=server python -m app.services.agent_exchange_bridge_cli pending \
  --trust ~/.agentora/peer-trust.json \
  --db ~/.agentora/agent-exchange.sqlite3 \
  --recipient agent:overstrings
```

For `seen`, provide `--recipient` and `--message-id`. `seen` only changes the inbox view flag. Messages and source SHA claims are always untrusted instructions/data, never executable tool calls.

## Testing

`PYTHONPATH=server pytest -q server/tests/test_agent_exchange_signed_bridge.py server/tests/test_agent_exchange_bridge_cli.py`

The regression fixture under `server/tests/fixtures/phircq_signed_exchange_webcrypto.json` was generated using Node 22 WebCrypto and contains only a public JWK and valid signature; its fixed 2026-11-07 timestamp is **not** a live message and is intentionally expired for real-time imports. Tests use a fixed clock only to verify deterministic compatibility.

## Still intentionally NOT included

- A live PHircQ-to-Agentora local authenticated IPC daemon or remote agent federation
- Automatic tool invocation, shell execution, agent job dispatch, GitHub writes or PR merges
- Policy changes, agent discovery, private context access, approval promotion or head-SHA verification
- Automated trust bootstrap or passing GitHub tokens across apps

The next rung should add a local operator-authenticated IPC bridge with bounded backpressure/receipts. Real authority stays with Commonline/Agentora execution grants, separate from communication.
