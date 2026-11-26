# Phi Independence R04-A — PhiBuddy advisory bridge

Experimental transport, no live workstation acceptance. This consumes PhiBuddy's
actual RecordedEvent schema v1 and events --jsonl CLI, reviewed at
5832141379174938bdd4d5487c698e228ccb9537 (crates/phibuddy-core/src/store.rs
and apps/phibuddy-cli/src/main.rs). No PhiBuddy changes or new repo.

## Private Windows pilot

From PhiBuddy, export one known session into an existing ACL-restricted encrypted
directory outside Git. PowerShell 7 example (UTF-8); Windows PowerShell 5 redirection
defaults to UTF-16 and is unsupported.

```powershell
cargo run -p phibuddy -- events YOUR_SESSION_ID --jsonl > D:/PhiVault/buddy-events.jsonl
```

The export contains private prompts and model outputs. Do not commit or upload it.
Inspect locally and choose the sequence of a solo_answer, synthesis or workshop_build
in a completed turn. From Agentora, set PYTHONPATH and preview:

```powershell
$env:PYTHONPATH = "server"
python -m app.services.phibuddy_bridge_cli D:/PhiVault/buddy-events.jsonl --sequence 2
```

Sequence 2 is illustrative. The preview prints private selected text and source IDs.
Read it before sending; avoid shared logs. Configure a unique 64-character lowercase
hex operator key in both private process environments, without putting it in Git or
shell history. Enable AGENTORA_PHIBUDDY_BRIDGE_ENABLED=1 in the server process.
Start the existing Agentora API with no proxy header trust:

```powershell
uvicorn app.main:app --app-dir server --host 127.0.0.1 --port 8088 --no-proxy-headers
```

In the separate client shell (same private key environment and PYTHONPATH):

```powershell
python -m app.services.phibuddy_bridge_cli D:/PhiVault/buddy-events.jsonl --sequence 2 --send --confirm-shared-text
```

Use an isolated disposable Agentora environment for first tests. The ordinary
Agentora server startup initializes its database and background services; the new
route itself does not access them. Do not expose Agentora to LAN/WAN.

## Boundaries

- Disabled by default; fixed IPv4 loopback port, exact Host, reject Origin,
  private key, no redirects or proxies in client. Key in process environment,
  not CLI arguments. No protection against compromised same-user processes.
- Input cap 8 MiB JSONL; UTF-8 (optional BOM). One session, increasing sequences,
  selected answer in a cleanly completed turn. No other message bodies sent.
- 32 KiB canonical packet cap, source and packet SHA-256; receiver verifies
  packet consistency only, not actual PhiBuddy origin or source completion.
  Copied/forged packets remain untrusted. No signatures, replay protection or
  persistence; repeated previews are harmless but do not establish fresh identity.
- Preview then send are separate invocations; file changes between them may
  alter selected text. Use a stable private export; no authenticated consent
  binding in this rung.
- Receipt RECEIVED_REVIEW_ONLY means schema/digest accepted. No model call,
  tool invocation, memory write, task dispatch, code change or authorization.
- Future R04-B: bind explicit consent to exact digest, optionally run isolated
  local review with independently verified local model configuration; no execution
  rights. R05 handles approved development separately.
- Tests exercise actual FastAPI route using synthetic schema-shaped records and
  mocked client transport. No live PhiBuddy binary, Windows sockets, or field
  isolation proof. No claim of EXIT-VERIFIED.

Run PYTHONPATH=server pytest -q server/tests/test_phibuddy_bridge.py.
