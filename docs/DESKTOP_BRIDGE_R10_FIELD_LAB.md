# Phi Desktop Bridge R10: Offline Windows Field Lab

R0-R9 established a governed local desktop adapter, a read-only Windows
named pipe, supervised observation receipts, a local field journal and a
read-only Operator Desk readiness panel. Those CI checks do NOT prove
that a real end-user desktop was tested.

R10 adds a standalone, **zero-install PowerShell preflight and manual
field-test plan**. It does not install Python, pywin32 or the upstream
desktop CLI and does not launch or operate any application.

## Review without installing anything

Review tools/desktop-field-lab/FieldLab.ps1 before using it. GitHub
Actions runs the script with the built-in Windows PowerShell runner and
tests the fixed sanitized JSON schema, false-only security claims, and
lack of file creation. This is a script validation, NOT an end-user PC
test.

The preflight calls only built-in PowerShell features:
- Get-Command for visibility of python and agent-desktop commands.
  Command visibility does not prove either installation works.
- Test-Path for four Agentora modules in the same checkout.
- Built-in OS platform detection and static instructions.

There are no package installs, remote calls, subprocess launches,
user-account operations, UAC prompts, security-policy changes, app
interactions, background jobs or writes to disk.

## Optional local Windows usage

After reviewing the script in your Agentora checkout, run:

    .\tools\desktop-field-lab\FieldLab.ps1

For a machine-readable, sanitized report printed to the terminal only:

    .\tools\desktop-field-lab\FieldLab.ps1 -Json

No usernames, absolute paths, session keys, UI labels, screenshots or
app data appear in the report. The -Plan switch prints the same guidance
as the default invocation.

If PowerShell execution policy blocks this convenience script, do not
weaken system execution policy solely to run it. The same commands are
available manually in the code and the existing R6-R9 documentation.

## Manual field-test sequence (never automated by R10)

1. Inspect and understand the R6 read-only security boundary.
2. Verify that Python, optional pywin32 312, and the upstream
   agent-desktop CLI are installed and functional on the PC.
3. Manually open Windows Calculator (or another harmless app).
4. In an interactive local terminal A, run the R6 named-pipe server
   with "--app Calculator" and without "--expose-labels".
5. In another interactive terminal B, run R7 "doctor" and optional
   two-observation "probe" using the local pipe address and secret
   prompt. Type consent phrases only if you choose to continue.
6. Explicitly save a sanitized R7 receipt if you wish. Inspect it
   locally, then optionally self-report the outcome into R8 with
   the separate RECORD confirmation.
7. View the R9 Field readiness (read-only) panel.
8. Stop terminal A with Ctrl+C. Do not post pipe keys anywhere.

R10 prints these instructions but never performs them.

## Remaining limitations

- No end-user Windows desktop test has been performed by CI.
- Independent cross-account denial testing remains outstanding.
- Same-user programs and elevated programs are not isolated by R6.
- The R8 journal is an operator self-report, not signed evidence.
- The R9 readiness panel cannot certify desktop compatibility.
- No autonomous action grants or execution permissions exist in R10.

This is a practical preparation rung, not a new security boundary or an
approval to control the desktop. Keep that distinction explicit.

## GitHub verification

The dedicated Windows job exercises -Json and -Plan without touching
the desktop, and confirms that no Agentora data appears in an isolated
temporary user-profile directory. The existing full backend and web CI
still run on the PR. Manual testing on an actual Windows PC remains
separate and optional.
