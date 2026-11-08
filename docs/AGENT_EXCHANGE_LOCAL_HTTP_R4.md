# R4: Live local PHircQ -> Agentora advisory bridge

This is an **optional, operator-started localhost service**, not an Agentora default API route or a cloud deployment. It uses the merged PHircQ signed bundle v1 / Agentora durable review inbox from R3.

## Boundaries

- Binds only to IPv4 `127.0.0.1`. Host header must match the active port. No externally configurable bind address.
- Every request requires a fixed-length operator-provided bearer token (64 lowercase hex characters, generated with `python -c "import secrets; print(secrets.token_hex(32))"`). Token is read from a separate file, never logged or passed in the URL. On POSIX its file must be owner-only (0600). On Windows use an ACL-restricted local file.
- Browser CORS is denied by default; optional exact local origins must be named with `--allow-origin`. Never list a hosted Pages site or arbitrary public origin.
- POST `/v1/ingest` accepts at most 16 KiB and independently verifies the PHircQ P-256 signed frame, operator-pinned key, exact peer-to-agent mapping and expiry before storing the advisory request.
- GET `/v1/pending?recipient=agent:overstrings` is a token-protected, private, **read-only** list. GET `/v1/status` is also token-protected. No browser-accessible `mark_seen` or execution action.
- The SQLite inbox keeps restart-safe replay protection. No auto-dispatch, no tool calls, no GitHub token, no merge grants, no automatic task acceptance.
- **This is a local pilot, not a multi-host authenticated IPC deployment.** A live PHircQ peer still needs explicit trust on both sides and an operator-configured matching agent ID mapping.

## Local setup

Make a private directory and create the token and trust files outside Git. You can generate a new token using Python:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Write its 64-character output to `~/.agentora/bridge-token` with restrictive permissions. Write `~/.agentora/peer-trust.json` with the R3 `agentora.phircq.trust.v1` policy containing the **out-of-band verified** PHircQ peer fingerprint and exact agent IDs, e.g. `peer-btm`, `agent:btm`, `agent:overstrings`. Do not copy any private key from PHircQ.

Run the explicit local receiver from Agentora's working directory:

```bash
PYTHONPATH=server python -m app.services.agent_exchange_local_http \
  --trust ~/.agentora/peer-trust.json \
  --token-file ~/.agentora/bridge-token \
  --db ~/.agentora/agent-exchange.sqlite3 \
  --port 38771 --allow-origin http://localhost:3690
```

On Windows PowerShell, set `$env:PYTHONPATH = "server"`, then run `python -m app.services.agent_exchange_local_http` with Windows file paths and the arguments above. Limit file access to your Windows user. For a packaged Tauri PHircQ client, explicitly allow its actual runtime origin, for example `http://tauri.localhost`. Never allow all origins.

In PHircQ's **Net > Agentora Local Bridge**, enable the bridge *before* connecting a trusted Paper Link. Enter the loopback URL, same token (session-only), and exact local and remote agent IDs. Peer trust must be explicitly established and Agentora's policy must pin the **sender peer** fingerprint separately. After receiving a signed agent offer, PHircQ sends the original signed frame to Agentora. Agentora independently checks it and stores it as `REVIEW_PENDING`. The **Read Agentora review inbox** button fetches a private view with the same token. To test delivery from a linked node, use the **Send signed work offer** control. Delivery over the peer link is not yet proof of inbox acceptance; confirm through the receiver acknowledgment.

## Security and limitations

This runtime has a single HTTP worker and bounded request sizes. It is for small trusted local use, not general internet exposure or high-volume fleet messaging. Browser mixed-content and Private Network Access controls may prevent some hosted pages from reaching localhost, which is intentional. A browser or extension with access to the in-memory token could read inbox content: do not use this bridge from untrusted origins or machines. The listener makes no promises about protecting the device against another malicious local process running as the same OS user.

There is no cross-platform file ACL manager, no automatic secret rotation, no unattended startup, no PhiMadaPrime public dashboard and no task approval/promotions in this rung. Agentora's durable `mark_seen` is still a local view flag, not a Commonline acceptance receipt.

## Verification

`PYTHONPATH=server pytest -q server/tests/test_agent_exchange_local_http.py`, then full Agentora CI including Python 3.12 and 3.13.
