# Φ Desktop Bridge · Rung 3: Native Operator Desk

R3 gives Agentora a standalone local graphical review window built with
Python Tkinter. This is a **proposal inbox**, not a new desktop automation
endpoint. It builds directly on merged R0, R1 and R2.

## Features

- Native window showing pending, reviewed, rejected, expired or all proposals.
- Readable intent detail: app, requested operation, reason, untrusted target
  hint, source label, correlation ID, content digest, and expiry.
- Per-app review manifest with exact names, explicit Boolean observe/click
  choices, no wildcard support, and **deny by default** for unknown apps.
- Every displayed record is re-read through R2's digest verification.
- A fresh exact-phrase confirmation is required to mark intent reviewed or
  rejected. Stale or expired entries cannot be reviewed.
- Rejected intents never reach manual handoff. Reviewed intents can display
  R2's plaintext manual follow-up instructions.

**Important: reviewing does not execute, authorize or approve a desktop
click.** The GUI does not import or call R1, R0, Agentora /api/actions,
any shell, any remote API or a browser. An operator who wants to act must
separately run the R1 broker, capture a fresh observation, and confirm each
click in the broker's own terminal.

## First preview on Windows

The native window only requires Python 3.12+ with Tk support, as well as
the local Agentora source checkout. You do NOT need to install the
agent-desktop binary, models, or launch an agent merely to preview proposals.

From the local Agentora repository root in PowerShell:

    $env:PYTHONPATH = "server"
    python -m app.services.desktop_inbox submit --app "Calculator" --op observe --reason "Inspect the calculator display"
    python -m app.services.desktop_operator_desk --policy "examples/desktop-bridge/operator-policy.example.json"

The example manifest permits **Calculator observation reviews only**.
It refuses review of click proposals, even if they are present in the inbox.
To change the manifest, make a local copy and restart the desk using your
own explicit --policy path. The manifest determines review eligibility only,
not broker authorization or OS permissions.

This graphical program is not installable/runnable through GitHub Actions,
cloud browsers, or the existing hosted Agentora web interface. Its headless
controller and policy tests *can* run in CI. Tk graphical availability and
real Windows usability still require a supervised local field test.

## Operational boundaries

- R2's local SQLite inbox remains under the user's local home directory.
  The GUI never sends proposal content over the network.
- R2 stores rationales and target hints unencrypted in local SQLite. Never
  put secrets, passwords, screen captures, clipboard contents or private
  app data into them.
- Source labels are untrusted attribution, not verified identities.
- Manifest policies are read at startup; use OS file permissions to protect
  them. The current code does not implement Windows ACL enforcement,
  sandboxing or a separate privileged local service.
- A human confirmation dialog is useful accidental-action friction, but
  isn't an OS-backed authentication boundary against compromised processes.
- SHA-256 proposal digests are not a cryptographic signature; attackers
  able to modify both payload and digest can forge records.
- The inbox's review status is **metadata, not an action token**. R1 does
  not consume it as a permission grant.
- A GUI selection is compared to the current proposal digest before
  changing status. Transactional R2 changes still enforce one-time review.
- Neither clicking Mark reviewed nor opening Manual handoff can call
  agent-desktop or operate the desktop.

## CI

    PYTHONPATH=server python -m pytest -q server/tests/test_desktop_operator_desk.py

GitHub CI also runs Python 3.12, Python 3.13 and the existing React build.

## Next

R4 should harden local IPC with OS-specific identity and ACLs, introduce
independent execution-result evidence (not just delivered-unverified), and
field-test Windows accessibility behavior before enabling any additional
automation. Remote browser/Agentora API authorization remains out of scope.
