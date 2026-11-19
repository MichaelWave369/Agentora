# Fleet R10: Windows R9 -> R1 watcher (owner workstation)

**Status: implementation candidate; Windows field acceptance required.**
This is a per-user Task Scheduler adapter for the **existing** Agentora R9/R1 code
in scripts/fleet_r10_r1.py, not another queue, worker or merge controller.

It can start the existing watch --dispatch command on Windows 11 when the owner
signs in. It does **not** invent missions, approve frozen tasks, create an App
publisher, override repository rules, or turn a successful CI result into product
acceptance. The two already-merged docs trials were started by explicit intake,
not by this scheduled host.

## Preconditions

- A locally reviewed, clean **main** checkout of MichaelWave369/Agentora.
- Python 3.11+ and dependencies installed and able to import the existing
  R9/R1 modules. PhiRepoNerve's same-user local loopback service and the
  persistent ~/.agentora SQLite paths must be available as in
  [the R10 runbook](FLEET_R10_R9_TO_R1.md).
- The original protected environment autonomous-turn-owner, publisher App,
  branch policies and tests remain configured on GitHub.
- Two **expiring, fine-grained, Agentora-only** tokens created by the owner:
  1. Dispatch: Actions **read/write**, to start only the existing R1 workflow.
  2. Observer: Actions, Contents, Pull requests and Checks **read**, including
     authenticated artifact downloads. Use minimum permissions validated in
     the R10 runbook.
- Windows PowerShell 5.1 and the built-in ScheduledTasks module.
- Your account must be signed in. This task uses **Interactive** logon and is
  not a machine service that can run before sign-in or while signed out.

**Never put tokens in chat, a PR, a script argument, task XML, repository
secrets, public browser JavaScript, or a committed .env.** Enter them only
at the hidden local prompts.

## Install from a PowerShell terminal on the runner PC

From the **reviewed** local Agentora checkout:

    git switch main
    git pull --ff-only
    git status --short

Inspect scripts/windows/Invoke-R9R1Watcher.ps1 and the exact main commit before
granting credentials. The following executes the installer:

    $runner = (Resolve-Path .\scripts\windows\Invoke-R9R1Watcher.ps1).Path
    & $runner -Mode Install

Specify -PythonExe with a full python.exe path if your python command resolves
to a Windows Store alias. Optionally specify -SnapshotPath with a local,
operator-controlled redacted PhiMada development snapshot destination:

    & $runner -Mode Install -PythonExe "C:\Path\To\python.exe" -SnapshotPath "C:\Path\To\PhiMadaPrime\public\fleet\r9-turns.json"

Only use a snapshot location that your existing PhiMada cockpit expects, and
confirm the path is ignored by source control. The default is a local-user AppData
file, not the public hosted Pages site.

The installer prompts invisibly for both tokens and exports SecureString fields
via **Windows DPAPI user-bound CLIXML** into:

    %LOCALAPPDATA%\Phi369\AgentoraR9R1\credentials.clixml

It stores the trusted Agentora checkout path, Python executable path,
snapshot path, and **exact Git HEAD SHA** in runner.json. The scheduled task
runs a copy of the reviewed PowerShell launcher from the user's AppData folder,
not a possibly changed script inside the Git checkout. Its command-line
argument contains only that local .ps1 path and Mode Run, never a token.

It creates Phi369-Agentora-R9R1, configured to start **at user logon**,
without elevation, ignoring duplicate task starts and restarting on limited
failure. It does not start a dispatch during installation.

## Observe, start, inspect and remove

Run an observation-only probe (one tick, **no new dispatch POST**):

    & $runner -Mode Probe

A probe can still update the local queue's readback/reconciliation state.
A missing or ambiguous GitHub result remains HELD or requires an operator
review, never an automatic second POST.

Start the long-running scheduled task:

    Start-ScheduledTask -TaskName "Phi369-Agentora-R9R1"

Inspect Windows' task status and last run result:

    & $runner -Mode Status
    Get-ScheduledTaskInfo -TaskName "Phi369-Agentora-R9R1"

Observe the redacted snapshot at the configured path and the GitHub workflow,
PR and receipt **for a specific admitted R9 task**. A running task is not proof
that a mission was admitted, dispatched, approved, merged or released.

To remove both the task and the locally encrypted tokens:

    & $runner -Mode Remove

## Safeguards and limitations

- Every start checks the checkout is at the **same reviewed commit** and
  has no modified tracked files. New commits or checkout moves require
  owner review and reinstall. An installed user task must not silently
  execute newly fetched source with the token.
- Tokens are encrypted at rest using the current Windows user's DPAPI keys.
  They are available as process environment variables only inside the
  launcher and its Python child. This is not protection against malware
  running as the same user or an administrator, and it is not a remote secret
  manager. Use narrow expirations, rotate regularly and revoke if exposed.
- The watcher polls R9 once per minute and reuses the durable local mission,
  submission fence and bounded recovery in the existing implementation.
  Three consecutive failed cycles exit nonzero for Task Scheduler recovery.
- The local computer must be online, signed in, and able to reach GitHub,
  RepoNerve and its persistent SQLite state. Windows sleep, shutdown, sign-out,
  task installation failure or expired credentials stop progress.
- No Windows host qualification has been performed by this PR. The first
  deployment must confirm the probe, task launch/restart, lack of duplicate
  submissions, source SHA pin behavior, secure credential handling, an
  explicitly approved actual dispatch, and the independent GitHub receipt.
- A source-tree clean/HEAD guard is a useful control, not a sandbox or a
  complete supply-chain attestation. Keep the PC and repository trusted.

**Acceptance:** one locally admitted, narrowly authorized Agentora docs
mission proceeds from R9 to a real hosted R1 dispatch via the scheduled
watcher, receives the original owner review, and reconciles the actual
GitHub merge or an honest HOLD. No manual workflow launch or merge button.
