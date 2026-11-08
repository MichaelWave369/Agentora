# Fleet R10: verified run evidence → exact mission → independent QA

**Scope:** the last local bridge in the existing RepoNerve → R9 → R5 →
R0.6/R0.7/R4 pipeline. It is opt-in, fixed to the public PhiMadaPrime
sandboxed test/build workflow, and makes **no new GitHub write request**.

The code does not initiate a test, merge a PR, install an application, deploy,
grant an agent new credentials, or certify product completion.

## Why

R5 stores a one-shot workflow submission intent. PR #127 added an optional
bounded request ID into the fixed R0.6 workflow artifact and an exact GitHub
run check in R0.7. R4 already independently cross-checks the GitHub artifact
SHA-256, exact public source revision, workflow success and local fenced lease.

This rung returns R0.7's trace through R4 and stores **one** matching verified
run next to the **original R9 mission**. The second explicit operation uses
R9's existing implementer-to-independent-QA transition, not a new queue.

## Before correlating

From your trusted local checkout:

1. Ingest a current public-only RepoNerve observation into R2.
2. Create one R9 `PHIMADA_FIXED_TEST` mission for an exact current
   `MichaelWave369/PhiMadaPrime` source SHA and claim the implementation lane
   with an R0.4 private lease. The maximum local lease TTL is 1800 seconds.
3. Dispatch once through `fleet_r10_r9_r5_bridge.py --execute` with its
   explicit owner confirmation and a narrow Agentora Actions-write credential.
4. Identify the **real** R0.6 GitHub Actions run and download its retained ZIP
   from GitHub, containing `preflight.json`, `steps.json`,
   `final.json` and the new `dispatch.json` marker. The ZIP must be
   downloaded while available; the workflow retains it for seven days.

**Important:** R4 requires that the pilot's pre/post execution timestamps
fall within the same still-active R0.4 lease window and that the exact
PhiMadaPrime HEAD remains unchanged when inspected. Runs delayed past the
lease window are a **HOLD**, not assumed safe. This is a known limitation
of the conservative pilot, not a reason to relax the evidence checks.

## Correlate a run (read-only GitHub access)

```bash
python scripts/fleet_r10_mission_evidence.py \
  --steward-db ~/.agentora/fleet-stewards.sqlite3 \
  --lease-db ~/.agentora/fleet-leases.sqlite3 \
  --mission-id phimada-fixed-001 \
  --lease-file ~/.agentora/private/worker1.lease \
  correlate \
  --intake ./phimada-verification-intake.json \
  --run-id 1234567890 \
  --artifact-zip ./fleet-r06-phimada-artifact.zip \
  --confirm CORRELATE_R10_FIXED_PILOT_RUN
```

Replace the illustrative mission, run ID and paths with real values.

The code requires the R9 assignment to still be `ASSIGNED_IMPLEMENT`, with
exact repository ID, source SHA, intake digest, implementer identity and
current lease generation. The R10 and R5 dispatch journals must both record
the **same accepted request**, not an unknown or rejected POST.

R4 independently checks the fixed GitHub run, workflow, source and uploaded
artifact SHA-256 through GitHub's read-only API, before and after matching the
local lease/source. The artifact's `dispatch.json` request ID must equal
the R10 mission's exact locally recorded request ID and its run ID must equal
the actual GitHub-owned run. A missing legacy marker, failed run, altered
archive, expired source/lease, wrong workflow, wrong request, or misleading
authority flag is held.

The resulting `r10_evidence_links` row resides in the **existing private
R9/lease SQLite database**, keyed uniquely by mission ID and GitHub run ID.
It retains the exact source, lease generation, workflow run ID, artifact ID,
GitHub-validated artifact SHA-256, request ID, and local correlation state.
The same run cannot be credited twice. Run verification is independent of
the worker's untrusted test log text.

The receipt states `CORRELATED_PENDING_QA` and explicitly preserves:
`independent_qa_complete: false`, `product_verified: false`,
`verified_complete: false`, `merge_authorized: false`.

**Trace attribution limits:** the request ID is inert public metadata,
not a signing key or proof of who caused the workflow dispatch. Correlation
ties the GitHub artifact to the locally recorded request, but an actor with
GitHub Actions write access could deliberately reuse an ID. This pilot
does not claim `dispatch_origin_authenticated`.

## Handoff for another QA worker

After inspecting the correlation record:

```bash
python scripts/fleet_r10_mission_evidence.py \
  --steward-db ~/.agentora/fleet-stewards.sqlite3 \
  --lease-db ~/.agentora/fleet-leases.sqlite3 \
  --mission-id phimada-fixed-001 \
  --lease-file ~/.agentora/private/worker1.lease \
  handoff --confirm QUEUE_R10_INDEPENDENT_QA
```

This uses R9's existing lease release and `handoff_to_qa` state machine.
It changes `ASSIGNED_IMPLEMENT` to `QA_QUEUED` with the *actual GitHub
artifact digest*. An independently named QA worker must claim the next
review, inspect the evidence and issue its own finding. This handoff is
**not** that review. It never labels or merges a PR.

If the process exits after R9 has queued QA but before updating the local
R10 evidence link, repeating `handoff` reconciles the exact matching
`QA_QUEUED` state without releasing the lease twice. Other interrupted or
uncertain states require manual reconciliation; they cannot auto-green.

## Test suite

```bash
PYTHONPATH=server python -m pytest -q \
  server/tests/test_fleet_r10_mission_evidence.py \
  server/tests/test_fleet_r4_steward_evidence.py \
  server/tests/test_fleet_r07_evidence_review.py \
  server/tests/test_fleet_r10_r9_r5_bridge.py
```

Tests cover mission/run uniqueness, tampered or missing dispatch trace,
wrong source, missing/rejected R5 journals, expiration, explicit approval,
separate QA assignments, no-release-on-error and crash reconciliation.

**Next:** field qualify the complete fixed PhiMada pilot with one fresh
source, runner and artifact. Only then consider event-driven run discovery,
broader agent assignments or separately authorized self-service
docs changes. The R9 queue never grants GitHub merge authority.

Ledger Above Ego. People Above Profit.
