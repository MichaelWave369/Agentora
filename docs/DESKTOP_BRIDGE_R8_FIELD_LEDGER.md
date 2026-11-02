# Φ Desktop Bridge · Rung 8: Local Field Trial Ledger

R8 is a local **operator self-report and readiness ledger** built on R7.
The purpose is to remember what a human *reports observing* during a
supervised Windows field test, without promoting that report to a security
attestation or an authorization token.

No GitHub PR, cloud service, agent, background task, web route or desktop
automation is involved in saving or reading the ledger. GitHub CI runs only
synthetic receipts, with no access to a real desktop.

## Workflow: optional local Windows field test

After reviewing this PR and if you later choose to run an optional
supervised trial on your own Windows computer, use a local checkout of
Agentora and Python 3.12+.

1. Follow docs/DESKTOP_BRIDGE_R6_WINDOWS_SID_PIPE.md to launch a
   read-only R6 named-pipe broker for a harmless app (e.g. Calculator).
   The R6 optional Windows backend uses pywin32==312.
2. In another local PowerShell terminal, choose a non-sensitive filename:

       $env:PYTHONPATH = "server"
       python -m app.services.desktop_windows_field_validation probe --address "<local-pipe-address>" --two-observations --receipt-file "calculator-observation.json"

   The operator must confirm READ ONLY, privately enter the local session
   key, then optionally make ONE harmless manual UI change and confirm
   SECOND. The pipe listener never clicks, types or runs shell commands.
   The receipt is created **only** because --receipt-file was supplied.
   It contains only sanitized R7 metadata and is stored under
   ~/.agentora/field-trials/. It never includes the pipe address or key.
3. After inspecting the outcome yourself, optionally append a self-report:

       python -m app.services.desktop_field_ledger record --receipt "calculator-observation.json" --status observed

   Or record a problem:

       python -m app.services.desktop_field_ledger record --receipt "calculator-observation.json" --status issue --issue inaccessible-ui

   A fresh interactive RECORD challenge is required. This saves a local
   minimal record and never executes or authorizes an action.
4. Show the local readiness summary:

       python -m app.services.desktop_field_ledger readiness
       python -m app.services.desktop_field_ledger recent

## What can and cannot be claimed

- A recorded entry is **operator-reported**, not a digitally signed,
  independently witnessed claim. Another process running as the user
  could fabricate entries or edit the local database.
- R8 validates every field against the exact redacted R7 schema and stores
  only receipt ID/timestamp, observation count, first target count,
  truncation state, and a bounded issue category. It rejects unknown
  fields so accidental raw UI content and passwords cannot be imported.
- An observed result is not proof that a user task completed successfully.
  Neither the ledger nor the optional probe can grant desktop privileges.
- No part of the ledger can declare autonomous execution ready.
  Cross-user negative testing, external security review, and
  same-user-process separation remain unverified.
- On POSIX, R8 requires a private 0700 directory and 0600 SQLite file.
  On Windows, it relies on the user's profile ACL inheritance; this rung
  DOES NOT verify or strengthen those ACLs.
- The database is local SQLite with uniqueness per receipt ID, not
  append-only authenticated evidence, a remote audit log, or a tamper-proof
  chain. Privacy depends on protecting the user's own OS account.

## What happens if an operator declines?

No receipt is saved without the explicit --receipt-file flag.
No ledger record is created without a live interactive terminal,
an exact randomized RECORD challenge, and a valid sanitized R7 receipt.
No automatic background processes or schedules are created.

## Automated tests

    PYTHONPATH=server python -m pytest -q server/tests/test_desktop_field_ledger.py

The existing backend (Python 3.12/3.13) and web CI remain required.
An additional Windows test job validates the offline receipt workflow,
but does not run any real desktop operation.

## What still needs manual proof

- Windows GUI compatibility and accessibility in the actual target apps.
- Independent multi-user negative tests confirming another Windows user
  cannot access the broker's protected named pipe.
- Third-party OS security review and threat-model sign-off.
- Stronger separation among processes sharing the same user SID.
- Human-approved, per-action verification if execution is ever introduced.

These are deliberately left **NOT VERIFIED**, regardless of how many
self-reported entries appear in the ledger.
