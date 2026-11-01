# Φ Desktop Bridge · Rung 2: Governed Proposal Inbox

**Status:** local preview, proposal-only. This is not remote desktop access.

R0 introduced a guarded local agent-desktop adapter. R1 added a separately
started authenticated localhost broker. R2 now makes it possible to record
and review *intent* without granting execution rights to agents.

## The trust boundary

\`\`\`text
Agentora/PhiServe/PocketBrain (propose only)
             |
             v
    Local desktop proposal inbox
  [immutable intent + digest + expiry]
             |
      human local review
             |
     "reviewed" or "rejected"
             |
             v
 MANUAL FOLLOW-UP IN R1 BROKER
 [fresh snapshot + separate broker approval]
\`\`\`

**Reviewing never runs a desktop action.** Neither proposing nor reviewing
imports or calls the R1 broker, R0 CLI, Agentora \`/api/actions\` endpoints,
or OS automation. The inbox has no \`execute\` or \`approve\` method; the
only terminal decisions are \`reviewed\` or \`rejected\`. In particular, this
does not use the existing Agentora approval API, because that API can execute
a tool.

## What is included

- Local SQLite-backed proposal queue stored by default at
  \`~/.agentora/desktop-inbox.db\` (outside the checkout).
- Narrow typed intent: source label, exact app name, \`observe\` or \`click\`,
  rationale, optional target description, correlation ID.
- Snapshot refs are *prohibited* in proposals because refs expire; the
  operator must observe the current app again at execution time.
- Content SHA-256 digest for accidental mismatch detection, expiry, pending
  limit of 100, transaction-protected one-time state changes, metadata-only
  event history.
- CLI for local submit, list, show, review and manual handoff.
- Pure \`submit_agentora_proposal(...)\` helper for future local orchestration
  integration, with no route or autonomous execution hook.
- Unit tests for expiry, concurrent review, schema rejection, privacy,
  directory security, and confirmation gate. No real desktop used in CI.

## Local CLI example

From your local Agentora checkout with Python 3.12+:

\`\`\`powershell
$env:PYTHONPATH = "server"

python -m app.services.desktop_inbox submit --app "Calculator" --op observe --reason "Read the display"
python -m app.services.desktop_inbox list
python -m app.services.desktop_inbox show <proposal-id>
python -m app.services.desktop_inbox review <proposal-id> --decision reviewed
python -m app.services.desktop_inbox handoff <proposal-id>
\`\`\`

The local review command requires an interactive terminal. It shows the
proposed intent and asks you to enter an exact, fresh \`REVIEW ...\` phrase.
This is **workflow friction, not cryptographic human identity verification**.
A program with control of the operator process or a sufficiently compromised
same-user desktop could bypass it.

For the optional intent to click, submit with \`--op click --target-hint "Digit 7"\`.
**The inbox never guesses a ref or forwards a click.** Follow the handoff
instructions to obtain a *new* snapshot and approve exactly one click in
the separately running R1 broker. R1 itself is read-only unless started
with \`--enable-click\`.

Example local integration in Python (no network):
\`\`\`python
from pathlib import Path
from app.services.desktop_inbox import ProposalInbox, submit_agentora_proposal

inbox = ProposalInbox(Path.home() / ".agentora" / "desktop-inbox.db")
proposal = submit_agentora_proposal(
    inbox, run_id=42, app="Calculator", operation="observe",
    reason="Inspect the active display",
)
print(proposal["id"])
\`\`\`

## Safety and deployment constraints

- **No public FastAPI/React mutation endpoint is added.** Agentora's
  existing API uses permissive CORS and includes approval routes with
  execution semantics. This inbox must not be mounted on those paths.
- The \`source\` value is **untrusted attribution**, not authentication.
  Any same-user process may submit proposals locally. Only allow trusted
  local programs to access the SQLite database and operator terminal.
- On POSIX, new DB and directory are created mode 0600/0700 and permissive
  existing files/directories are rejected. Windows ACL hardening and
  process isolation remain unimplemented; do not call this an OS sandbox.
- SQLite includes proposal rationale and target hints. Do not put secrets,
  personal messages, passwords, sensitive windows, screenshots, accessibility
  trees, browser data or clipboard content into it. Events store only
  IDs, time and status, and are not tamper-evident against an attacker
  able to edit the database.
- The SHA-256 digest detects mismatches on read; without a keyed signature
  or external trust anchor it is **not** an anti-tampering mechanism.
- The proposed application's visible labels are untrusted. Neither
  accepting a proposal nor clicking a benign-looking target guarantees safety.
- No cloud-connected model, GitHub Action, or agent can control a local
  desktop from this rung.

## Run checks

\`\`\`sh
PYTHONPATH=server python -m pytest -q server/tests/test_desktop_inbox.py
\`\`\`

GitHub CI runs backend Python 3.12/3.13 and the web build, with no real
desktop access.

## R3 path

Build an authenticated *local* operator inbox UI (not existing cloud API),
with OS-permissioned IPC and per-app policy manifests, then field-test
the broker against actual accessibility sessions on Windows and Linux.
Only after this review should PhiOS/PhiOperator expose approved
desktop controls to model planners.
