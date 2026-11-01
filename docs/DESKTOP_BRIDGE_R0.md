# Φ Desktop Bridge · Rung 0 (Agentora)

**Status:** experimental, opt-in, local-only. This is a usable guarded adapter for
[vercel-labs/agent-desktop](https://github.com/vercel-labs/agent-desktop),
not a system-wide desktop-control permission grant.

## What ships

- Read-only native accessibility snapshot of one explicitly allowlisted app.
- Snapshot-bound clickable refs, with incomplete and stale observations rejected.
- One optional ref click, requiring an interactive operator terminal and a fresh,
  single-use exact approval phrase. Default is **read-only**.
- A second snapshot after a click, marked **observed, not verified**. The caller
  must judge task success separately; no mutating command is automatically retried.
- Local metadata-only audit records with no screenshots, clipboard, accessibility
  text, terminal input, action names, or raw backend errors.
- Pure mock tests, so GitHub CI runs without reaching any real desktop.

## Usage on the machine being controlled

Requires Python and a locally installed compatible \`agent-desktop\` CLI. The
actual desktop control **cannot run in a GitHub Actions job or cloud browser**.
On Windows, run PowerShell in an interactive session:

\`\`\`powershell
npm install -g agent-desktop
agent-desktop version
cd Agentora
$env:PYTHONPATH = "server"
python -m app.services.desktop_bridge --app "Calculator"
\`\`\`

This observes Calculator and prints clickable element names and refs **in your
own terminal**. It does not click. To test a single operator-approved click:

\`\`\`powershell
python -m app.services.desktop_bridge --app "Calculator" --enable-click
\`\`\`

Choose a displayed element number, then enter the freshly displayed approval
phrase. **Only click a harmless test target.** Applications can label dangerous
actions innocently. This experiment is not a sandbox or a guarantee that a
click is safe. Each invocation allows at most one approved click.

Optional private ledger:
\`\`\`powershell
python -m app.services.desktop_bridge --app "Calculator" --audit-file ".local/desktop-audit.jsonl"
\`\`\`

Do not upload terminal transcripts, full snapshots, screenshots, clipboard
contents, or .local audit files to GitHub. Keep this module inaccessible from
public HTTP endpoints. Do not attach it to Agentora auto-execution.

## Threat model and limits

An agent controlling this same local Python process or terminal could spoof
confirmation. The TTY challenge is a **human workflow guard**, not an OS
privilege boundary or cryptographic authorization. Before integrating any
autonomous model, implement a separate trusted local broker, authenticated IPC,
per-process permissions, target restrictions, and a real independent operator
approval surface. No network listener, remote desktop service, or background
daemon is installed by this rung.

Accessibility labels are untrusted, including names supplied by the app itself.
The protected-word filter is only defense in depth. Even apparently benign
clicks can have side effects. Limit tests to disposable, non-sensitive apps.

The adapter intentionally excludes typing, clipboard, screenshots, shell
commands, coordinate clicks, purchases, destructive actions, elevated windows,
and any automatic acceptance of external instructions. If the backend returns
an error or an uncertain delivery, the bridge fails closed and does **not**
retry the action. Partial snapshots are rejected.

\`agent-desktop\` CLI refs are tied to snapshot state; a changed UI can
produce stale refs. The post-action snapshot does not verify the *intent*
of the action. The upstream docs describe the envelope's disposition semantics:
https://github.com/vercel-labs/agent-desktop/blob/main/docs/json-output.md

## Implementation plan

- **R0 (this PR):** reusable local Python service, explicit opt-in CLI,
  approval on every individual click, mock tests and audit.
- **R1:** dedicated local broker with separated process privileges and
  authenticated operator approvals; accessible app allowlists and granular
  policies. No cloud-exposed execution routes.
- **R2:** optional Agentora/PhiOperator task *proposals* and local approval
  inbox, plus task-level result assertions, not silent retries.
- **R3:** PhiServe/PocketBrain planning and PhiOS adapter support under the
  broker, with offline-by-default snapshots and privacy boundary checks.

Test locally from Agentora root:
\`\`\`sh
PYTHONPATH=server python -m pytest -q server/tests/test_desktop_bridge.py
\`\`\`

Source project is Apache-2.0. This adapter calls the installed CLI; it does
not vendor third-party source or redistribute its binaries.
