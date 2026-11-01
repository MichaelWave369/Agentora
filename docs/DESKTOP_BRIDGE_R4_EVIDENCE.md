# Φ Desktop Bridge · Rung 4: Evidence Field Trial

R4 is an **offline, read-only supervised test harness** for the merged R0
desktop adapter, R1 local broker, R2 proposal inbox, and R3 Operator Desk.

**The distinction:** an API reply of "delivered" does not verify a task.
R4 offers two independently timed accessibility observations with one
**predeclared exact role/name expectation** (appear or disappear).
It gives an evidence receipt with three possible outcomes:

- supporting_observation: the required UI-element change was observed.
- contradicting_observation: the specific required change was not observed.
- inconclusive: the observation was stale, ambiguous, duplicated, or invalid.

Every receipt explicitly has task_verified=false. An observed change may
support a particular claim, but is not proof the entire user task succeeded.
App-provided accessibility labels remain untrusted. Only ref-bearing nodes
exposed by the upstream interactive snapshot are observable by this rung.

## Safe preview before any local install

GitHub CI runs mock tests with no desktop attached. This PR can be reviewed
and merged online, with no changes to the user's machine.

On a local Agentora checkout with Python 3.12+:

    $env:PYTHONPATH = "server"
    python -m app.services.desktop_evidence doctor

This prints a local read-only capability report. It does not run any desktop
automation. It calls out **not_implemented** for OS-level IPC isolation and
Windows ACL hardening. Presence of Tk and the upstream CLI on the PATH
does not prove either actually works.

## Supervised Windows field trial

Only after intentionally choosing to install the upstream agent-desktop CLI,
test with a harmless app on your own Windows computer:

    npm install -g agent-desktop
    agent-desktop version

Run a read-only trial using a non-sensitive application and an expected
visible accessibility element transition, for example:

    $env:PYTHONPATH = "server"
    python -m app.services.desktop_evidence trial --app "Calculator" --role "button" --name "OK" --expect appeared

The example role/name is **illustrative only**. Use a real unique role/name
from your chosen app's accessibility tree. R0's interactive snapshots may
omit noninteractive content, and not every app exposes usable accessibility
labels. A failed or inconclusive trial is a useful compatibility finding.

The trial requires an interactive local terminal. It asks you to type START,
takes the initial read-only observation, asks you to make one harmless
**manual change in the app**, then asks you to type CAPTURE before taking the
second observation. The trial itself **never clicks, types, runs shell
commands, calls the broker, issues HTTP requests, or triggers actions**.

The emitted JSON receipt has counts, an evidence status, an expiry-independent
timestamp, and a random receipt ID. It contains no app name, target role/name,
element refs, screenshots, clipboard contents, tokens, or raw trees. It is
printed locally and not sent to GitHub or a model service. Do not paste or
publish terminal output if it includes your private surrounding context.

## Limits and next security work

- The observer uses the *same local user's desktop session*, not an OS-isolated
  independent witness. It is independent of action delivery reporting, not
  independent of the host computer's trust boundary.
- Exact accessibility role/name predicates can be spoofed by applications.
  They are evidence about exposed UI state, not proof of underlying behavior.
- An automated system must **never** treat supporting_observation as an
  execution grant, merge approval, purchase approval, or confirmation of any
  sensitive operation.
- R1's authenticated loopback TCP is not encrypted and has no OS-permissioned
  IPC ACLs. R4 does not claim to have hardened these areas.
- R3 remains proposal review only; no R1 execution or remote action API routes
  are added by this rung.
- Nothing is added to local startup, background services, desktop permissions,
  Windows registry, or server endpoints.
- For future OS hardening, evaluate authenticated OS-specific named pipes on
  Windows and Unix sockets with peer credentials on Linux, with threat-model
  review and user-specific ACLs before enabling unattended computer use.

## CI checks

    PYTHONPATH=server python -m pytest -q server/tests/test_desktop_evidence.py

GitHub Actions additionally runs the full backend suite on Python 3.12 and
3.13 plus the React build. Passing mocked CI is **not** a substitute for an
actual supervised desktop field test.
