# Φ Desktop Bridge · Rung 1: local authenticated broker

**Status:** experimental, explicitly opt-in. Built on the approved R0
[Desktop Bridge](DESKTOP_BRIDGE_R0.md). Designed for Linux, macOS and Windows
Python 3.12+, but it has **not** been field-tested against a real Windows
accessibility session.

## What it does

Agentora gets a separately launched localhost broker process for desktop
observation and carefully supervised *single-click* actions. It listens only
on \`127.0.0.1\`, uses an ephemeral port by default, and cannot accept requests
from a machine on the LAN. It is not an HTTP API.

Every connection uses a fresh 256-bit random challenge plus an HMAC-SHA256
signature derived from a 256-bit session token. The token is never transmitted
over the socket or saved to a file. Only a person launching the broker sees it
in the broker terminal. Both commands and responses are bounded, and requests
use a strict allowlisted schema. No secrets, accessibility trees or app labels
are written to the metadata audit ledger.

**Still not a hardened OS sandbox.** Local malware running as the same user
may read process memory, inspect terminals or control desktop applications
directly. The credential grants *local observation capability*; guard it as
sensitive. Do not paste the token into a chat, GitHub issue, shell argument,
browser, remote connection or CI log.

## Try it locally

On the Windows desktop where you want to test:

1. Install the upstream CLI with \`npm install -g agent-desktop\` and validate
   \`agent-desktop version\`.
2. From the Agentora repo root, open **PowerShell terminal A**:

   \`\`\`powershell
   $env:PYTHONPATH = "server"
   python -m app.services.desktop_broker start --app "Calculator"
   \`\`\`

3. Terminal A prints an ephemeral localhost port and a secret session token.
   Keep it private. Do **not** enable any port forwarding.
4. Open **PowerShell terminal B**, also at Agentora root:

   \`\`\`powershell
   $env:PYTHONPATH = "server"
   python -m app.services.desktop_broker request --port 54321 --op ping
   python -m app.services.desktop_broker request --port 54321 --op observe
   \`\`\`

   Replace \`54321\` with the displayed port, and paste the session token only
   into the private password prompt. Observe defaults to returning ref IDs and
   roles **without element labels**.

5. Stop terminal A with Ctrl+C. The session token expires when the broker
   stops. Nothing auto-starts on login.

To explicitly share clickable element names *locally*, start terminal A with
\`--expose-labels\`. Those labels may contain private information and should
never be forwarded to public model endpoints.

To test a harmless single click, start the broker with \`--enable-click\`,
first request \`observe\`, then in terminal B request:

\`\`\`powershell
python -m app.services.desktop_broker request --port 54321 --op click --ref '@sabc123:e7'
\`\`\`

Replace the example ref with a real recent ref. A new **one-time challenge
appears only in terminal A**, where a human operator must approve the click.
An authenticated client cannot approve it on its own. There is no automatic
retry, and a successful click delivery is reported as *unverified* until the
task's actual outcome is independently checked.

## Security model

- **Desktop broker process:** owns the upstream CLI, app allowlist, snapshot
  state, policy, and local approval terminal. It is launched manually.
- **Client:** holds an ephemeral session token and can request only
  \`ping\`, \`observe\`, or \`click\`. There is no arbitrary command execution,
  typing, shell access, browser or file API, screenshots, clipboard access,
  or app switching.
- **Independent approval:** click requests require R0's opt-in policy, current
  snapshot-bound ref, label filter, and fresh approval typed into broker TTY.
- **Confidentiality:** ref IDs/roles are returned by default; labels require
  explicit \`--expose-labels\`. The local metadata-only audit includes no
  raw requests, tokens, labels, screenshots, or snapshots.
- **Transport:** localhost TCP is used for cross-platform stdlib support.
  It is authenticated but **not encrypted**. No listener binds non-loopback
  interfaces. OS user isolation, IPC ACLs, and process integrity enforcement
  are **future hardening work**, not features of R1.

## Integration status

This rung is intentionally *not* mounted as an Agentora FastAPI endpoint.
The signed \`request_local\` client helper is available for a future operator
inbox, but should not be called from a remote endpoint. The normal cloud-hosted
Agentora UI cannot use the user's local broker without a separate approved
local component. There is no unattended merge, install, or destructive action.

## Tests

\`\`\`sh
PYTHONPATH=server python -m pytest -q server/tests/test_desktop_broker.py
\`\`\`

Mock tests validate localhost transport, fresh challenge, token rejection,
name redaction, strict request schema, disabled-by-default mutation, approval
guard, and malformed or oversized requests. GitHub CI does not access any
real desktop.

## Next rung

R2 should create a dedicated operator inbox and proposal-only contract,
prefer OS-protected named pipes / Unix domain sockets, enforce local OS
identity and per-app permission manifests, and separate broker privileges
before allowing any real autonomous action. Real Windows field testing and
third-party review must precede broad deployment.
