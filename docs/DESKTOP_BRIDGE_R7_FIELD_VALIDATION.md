# Φ Desktop Bridge R7: Supervised Windows Field Validation

R0–R6 established a local adapter, authenticated broker, governed proposal
review, read-only observation evidence, native IPC, and a Windows pipe with
user-SID restrictions. R7 adds the **next honest milestone: a validation
protocol a Windows operator can run while retaining direct control**.

This PR contains NO automated desktop actions. It adds NO remotely callable
API routes, persistent services, scheduled jobs, startup entries or uploads.

## Stage 1: zero-install review

GitHub Actions runs the R7 headless tests on Linux and the existing Windows
named-pipe smoke tests on a Windows runner. R7 validates strict response
schemas, redaction, no-mutation contracts, replayed snapshot detection and
the prohibition on claiming autonomous operation is ready.

CI never runs an actual desktop UI.

## Stage 2: optional local readiness check

After deciding to try the already-merged Agentora components on your own PC,
run this in a Windows terminal from the Agentora checkout:

    $env:PYTHONPATH = "server"
    python -m app.services.desktop_windows_field_validation doctor

This is a read-only self-assessment: it prints whether the Windows ACL
dependency is available and explicitly records untested items. It does not
open the desktop, connect to a pipe or save a report.

## Stage 3: optional supervised observation probe

Only for an explicitly chosen harmless local application, first start the
separate R6 broker in terminal A (see the R6 documentation):

    python -m app.services.desktop_windows_restricted_ipc start --app Calculator

Do **not** use --expose-labels. In a second local Windows terminal:

    python -m app.services.desktop_windows_field_validation probe --address "<R6-pipe-address>"

Or capture an optional second observation after a deliberate harmless
MANUAL interaction with the application:

    python -m app.services.desktop_windows_field_validation probe --address "<R6-pipe-address>" --two-observations

The probe insists on:
- A real interactive Windows terminal and the exact READ ONLY consent phrase.
- A private R6 session key through a password prompt (never a CLI argument).
- A broker ping stating clicks are disabled and identifying the R6 transport
  version. This marker prevents accidental R5 use; it is NOT cryptographic
  attestation and does not establish host/process integrity.
- A valid bounded observation response with accessibility names fully redacted.
- Distinct snapshot IDs before and after the optional manual action.

The probe prints one sanitized JSON receipt containing metadata counts and
explicit NOT_PERFORMED / NOT_VERIFIED flags. It never copies pipe addresses,
keys, refs, element labels, raw snapshots or screenshots to the report.
The response count can reveal the number of clickable elements in the app,
so treat the receipt as local-only unless reviewed.

## Stage 4: separate manual security validation (NOT AUTOMATED HERE)

The following remain *unverified* by GitHub CI and the probe:

1. Real accessibility compatibility on the intended Windows PC.
2. Cross-account pipe denial on a multi-user Windows installation, including
   a standard second account and a restrictive account boundary. Do not
   create or modify local accounts just to pass this rung.
3. Independent Windows DACL/token security review.
4. Resistance to a compromised process already running under the same SID.
   The latter is not provided by per-user DACLs.
5. Independent user-level task verification and safe cancellation behavior.

No receipt may mark the system ready for unattended clicks. A successful
observation does not prove a user task succeeded.

## Review and test

    PYTHONPATH=server python -m pytest -q server/tests/test_desktop_windows_field_validation.py

The Windows workflow includes an R7 end-to-end test that opens the actual R6
named pipe, verifies multiple sequential requests, and uses only a mocked
accessibility backend. R6's separate Windows smoke test is also retained.
Neither exercises a real desktop. Full backend Python 3.12/3.13 and web
builds remain required.

## Next step

After a supervised Windows field test with safe non-sensitive apps, decide
whether to integrate the observed state into the Operator Desk. Any future
execution mechanism requires a separate threat-model review, explicit
consent, and isolation stronger than a shared Windows user SID.
