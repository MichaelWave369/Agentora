# Φ Desktop Bridge · R6: Windows User-Restricted Native Pipe

This is an **opt-in Windows-only, observation-only** local IPC listener. It
builds alongside the R5 transport and does not change the existing desktop
adapter, broker, proposal inbox, or Operator Desk.

## What is different from R5

- At pipe creation, the server supplies an **explicit single-user DACL**.
  The single allowed ACE is the current Windows process user SID, rather
  than the default named-pipe ACL.
- The server reads the actual bound kernel object's DACL and refuses to
  start if its ACE contents do not match the expected single-user rule.
- The pipe uses **PIPE_REJECT_REMOTE_CLIENTS**.
- Each client still needs the R5 256-bit ephemeral session key for two-way
  challenge/response authentication.
- After session authentication and before dispatch, the server calls
  **ImpersonateNamedPipeClient**, reads the client token SID, and insists
  that it matches the server user SID. It **always reverts** impersonation
  before any accessibility operation.
- Supported operations are **ping** and **observe only**. There is no
  click, keyboard, shell, file, clipboard, web, or approval operation.
  No remote API endpoint or automatic service is introduced.

R6 uses **pywin32 312** optionally on Windows, to express Windows ACL and
token functions directly. It does not add pywin32 to the cross-platform
requirements. R6 remains unavailable if those functions cannot be loaded.

## Windows-only GitHub CI

The dedicated Windows Actions workflow installs only pytest and pywin32,
then uses a **real Windows named pipe** against the mocked desktop adapter.
Tests check creation-time security settings, the bound pipe's DACL,
authenticated same-user requests, deliberate wrong-key rejection,
simulated SID denial, remote-rejection flag, and absence of mutating
operations. No actual user desktop or sensitive files are touched.

A Windows GitHub runner is not evidence of the user's desktop configuration
or protection against same-user malware. Cross-user denial and user-token
security should undergo independent testing on an actual multi-user Windows
machine before interpreting this as a complete security boundary.

## Local preview (optional)

From an Agentora checkout with Python 3.12+ on Windows:

    python -m pip install pywin32==312
    $env:PYTHONPATH = "server"
    python -m app.services.desktop_windows_restricted_ipc doctor

To start an **opt-in** read-only pipe for a harmless app when the upstream
agent-desktop CLI is available:

    python -m app.services.desktop_windows_restricted_ipc start --app Calculator

The terminal displays a randomized local pipe address and private session
key. Never post, paste into chats, or commit the key. From another terminal:

    python -m app.services.desktop_windows_restricted_ipc request --address "<displayed pipe>" --op ping
    python -m app.services.desktop_windows_restricted_ipc request --address "<displayed pipe>" --op observe

The key is entered into a private password prompt. Nothing is executed
on the desktop beyond obtaining an accessibility observation, and labels
are hidden by default.

## Security limitations

- A DACL and SID check do **not** isolate different processes owned by
  the same Windows user. Trusted and malicious same-user code can share
  the SID. Administrators may have other means to inspect/control the
  process. This is not a full sandbox.
- The transport authenticates messages but **does not encrypt them**.
- The built-in Python multiprocessing challenge-response handshake is a
  transport mechanism, not a task-level approval grant.
- Impersonation is used solely to check identity, never to perform desktop
  actions, and is reverted before any operation.
- The R5 experimental Windows named pipe remains available as a legacy
  separate module. Prefer the R6 path for controlled Windows pilots; do
  not describe R5 as user-restricted.
- Actual upstream accessibility compatibility still needs human testing.
  Passing tests here proves only the tested Windows protocol properties.

References: Microsoft CreateNamedPipeW, Named Pipe Security and Access Rights,
and Impersonating a Named Pipe Client.

## Next

Before any autonomous click functionality, obtain independent security
review, Windows multi-account negative tests, explicit operator consent,
and a stronger separation between planner and privileged desktop broker.
