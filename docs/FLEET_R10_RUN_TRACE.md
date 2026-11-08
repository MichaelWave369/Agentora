# Fleet R10 · exact workflow-run trace for fixed PhiMada testing

**Scope:** add one inert request identifier to the **existing** Agentora R5
fixed workflow submission and R0.6 GitHub-hosted artifact, then verify that
identifier with the **existing** R0.7 read-only artifact verifier.

This is not general mission execution, a code generator, a scheduler, a new
GitHub publisher, or permission to approve, merge or deploy.

## The missing link

The R9 → R5 bridge already stores a deterministic request ID and one-shot
local dispatch intent. The historical R0.6 GitHub Actions workflow accepted
only the exact PhiMada source SHA and fixed confirmation string. GitHub's
workflow dispatch response typically returns HTTP 204 **without a run ID**.

Selecting a later run by time alone would be unsafe. Multiple manual or
scripted runs can target the same SHA. R10 therefore includes an optional
`request_id` string in the *existing fixed-workflow POST* only when
called through the R10 adapter. Existing direct R5 calls remain compatible:
they omit that extra input.

## Trusted runner artifact

The fixed R0.6 workflow retains its original source-HEAD checks,
read-only checkout, network-disabled Docker tests, and fixed workflow path.

For an R10 request, its trusted verifier emits `pilot-control/dispatch.json`:

```json
{
  "schema": "agentora.fleet.fixed-dispatch-trace.v1",
  "request_id": "r10r5-<40 hexadecimal characters>",
  "run_id": 1234567,
  "pilot_source_sha": "<actual requested 40-character SHA>",
  "dispatch_authorized": false,
  "merge_authorized": false,
  "verified_complete": false
}
```

All values are inert metadata. The ID is intentionally **not secret** and
must not be treated as authentication or authorization. It originates from
the workflow dispatch input; another actor with sufficient GitHub Actions
write authority could intentionally repeat it. This prevents **accidental
misattribution** and supports independent correlation. It does not prove
who submitted the request.

The unchanged GitHub artifact name `fleet-r06-phimada-<run_id>` remains
bound to the actual GitHub-owned run. The new marker is inside the same
downloaded ZIP. R0.7 independently validates GitHub run/repository/workflow
identity, completed success state, original source receipts, artifact SHA-256
from the GitHub API, and **then** the marker's exact run ID and source SHA.

Historical artifacts with only the original three files still pass R0.7,
but they return `dispatch_request_id: null` and
`dispatch_trace_present: false`. They cannot be retroactively linked
to an R10 request.

R0.7 explicitly reports `dispatch_origin_authenticated: false`. Neither
this output nor HTTP 204 implies an active runner, production acceptance,
a passed deployment check, or an automatic merge.

## Field qualification

1. Review and merge the CI-green privileged workflow change manually.
2. Prepare a new, expressly operator-authorized, fixed public PhiMada
   test mission using R9, its held intake and active local lease.
3. Confirm the exact current PhiMada SHA and invoke the R10 bridge's
   `--execute` path **only once**, with a narrowly scoped Actions-write
   token for Agentora.
4. Obtain the real GitHub Actions run ID and download its retained
   `fleet-r06-phimada-<run_id>` artifact ZIP.
5. Run `scripts/fleet_r07_evidence_review.py` against that run and ZIP.
   The review must verify `dispatch_request_id` equals the R10 ledger
   request ID. An absent or different marker is a hold.
6. A *separate future* reconciliation rung must bind that verified evidence
   to the R9 mission and arrange independent QA. **This change does not
   advance the mission state or automatically discover runs.**

## Verification

```bash
PYTHONPATH=server python -m pytest -q \
  server/tests/test_fleet_r5_guarded_dispatch.py \
  server/tests/test_fleet_r06_pilot.py \
  server/tests/test_fleet_r07_evidence_review.py \
  server/tests/test_fleet_r10_r9_r5_bridge.py
```

Synthetic tests cover traced and legacy POST bodies, fixed workflow path
and inputs, strict marker IDs, exact run/source binding, forged authority
flags, omitted historical marker and replay behavior. **The GitHub-hosted
field loop still needs an observed real run.**

Ledger Above Ego.
