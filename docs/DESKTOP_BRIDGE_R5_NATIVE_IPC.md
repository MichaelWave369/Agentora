# Phi Desktop Bridge R5 · Native IPC, Observation Only

R5 introduces a **separate local IPC transport prototype**, without changing
the R0-R4 behavior. Its purpose is to reduce dependence on loopback TCP
while retaining explicit authentication and preventing execution by design.

## Platform behavior

- **Linux:** private Unix domain socket in ~/.agentora/desktop-ipc, under
  a 0700 directory with 0600 socket permissions. The server compares
  SO_PEERCRED UID to the current effective user. Authentication uses a
  separate 256-bit ephemeral session key via Python's stdlib connection
  challenge-response protocol.
- **Windows:** experimental Python stdlib AF_PIPE named pipe with
  challenge-response session authentication. Named pipe endpoint name is
  randomized per launch. **The Windows pipe DACL and connecting process
  identity are NOT validated in this rung.** Treat it as a functional
  local prototype, not a verified user-only ACL-protected Windows broker.
- **Other POSIX:** Unix sockets can be created, but peer UID verification
  requires a supported getpeereid mechanism; fail closed otherwise.

Neither protocol encrypts payload content. Authenticated clients can only
request **ping** or **observe**. Attempts to send a click, shell, clipboard,
network, or other action are rejected, and the broker must have
enable_click=False at construction.

No FastAPI routes, remote URLs, automatic startup, privilege grants or
cloud action integration were added.

## Non-install trial

GitHub CI exercises the R5 protocol entirely through a mocked upstream
backend. It adds a Windows Python 3.12 workflow job to smoke-test actual
AF_PIPE transport on a GitHub Windows runner, with no desktop control.
All code can be reviewed and merged without modifying your own PC.

## Manual local preview

For the **same local user on the same machine**, in a terminal under the
Agentora repository root:

    $env:PYTHONPATH = "server"
    python -m app.services.desktop_local_ipc doctor

To observe an app, you must have the upstream agent-desktop CLI installed
locally and available on PATH. Then start terminal A:

    python -m app.services.desktop_local_ipc start --app "Calculator"

It prints a randomized IPC address and one-time session key. Do not post
these to GitHub, chats, files or logs. In terminal B:

    $env:PYTHONPATH = "server"
    python -m app.services.desktop_local_ipc request --address "<local address>" --op ping
    python -m app.services.desktop_local_ipc request --address "<local address>" --op observe

You enter the session key at a hidden password prompt in terminal B, not
as a command-line argument. It is not a broker execution credential,
because R5 implements **no mutation API**. The default observation
response excludes accessibility element names.

## Safety limitations

- Same-user malware or a compromised session can read local process memory
  or enter commands regardless of this module. Session-key authentication
  and OS peer checks do not establish a sandbox.
- Windows AF_PIPE authorization is NOT a verified OS ACL boundary. Future
  Windows hardening must validate explicit user SID DACLs, remote-client
  rejection, and process token identity with independent Windows testing.
- A Windows GitHub runner test is useful for protocol mechanics only. It
  is **not** proof the local Windows desktop is safe or compatible.
- R5 intentionally cannot click and cannot accept review decisions from
  R3. Review status never grants an execution token.
- The R1 localhost TCP broker remains for backwards compatibility; R5 does
  not replace it or route its click operation.
- If the upstream CLI cannot observe an app, the IPC service reports a
  denial. No sensitive snapshots are written into GitHub Actions logs.

## Tests

    PYTHONPATH=server python -m pytest -q server/tests/test_desktop_local_ipc.py

R5 adds a dedicated Windows runner for the same mocked tests. On Linux,
the regular Python 3.12 and 3.13 suites also exercise private socket mode
and peer authentication. No real desktop operation occurs in CI.

## Next rung

R6 should introduce verified Windows user-SID-only pipe DACLs and peer token
identity, with OS-level review. Only after that and real local field tests
should we consider adding trusted, per-action execution through IPC.
