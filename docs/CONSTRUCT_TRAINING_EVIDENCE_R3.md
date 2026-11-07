# ΦConstruct R3: independent source HEAD and local lease evidence

**Status:** read-only, operator-confirmed evidence correlation in Agentora.
Training execution and its results remain **unattested**.

PhiRepoNerve delivers a versioned, digest-pinned training request. Agentora
R1 validates its untrusted JSON shape and pins the Welcome Charter. R2
binds that request, upon explicit review, to a public repository intake
and existing R3 same-host lease. **R3 adds independent GitHub source HEAD
observations before and after the review.**

## Usage

First complete the existing R0.3 public intake, R2 steward registration,
and R3 lease reservation. The leased worker name must match the
training request's agent label. No new lease is created by this command.

```bash
python scripts/construct_training_evidence.py \
  --handoff ./request.json \
  --intake ./verification-intake.json \
  --steward-db ~/.agentora/fleet-stewards.sqlite3 \
  --lease-db ~/.agentora/fleet-leases.sqlite3 \
  --lease-file ~/.agentora/private/worker-alpha.lease \
  --confirm CORRELATE_CONSTRUCT_SOURCE_AND_LEASE
```


An optional `--report ./inspected-report.json` accepts
PhiRepoNerve's **unattested** `handoff inspect` result.
Even if that result claims `reported_pass`, R3 will
**not** mark an agent competent or its training execution verified.

## Evidence checks

- Reuse R2's strict handoff and Welcome Charter validation.
- Reuse R0.3 intake, R2 steward visibility/freshness, and the existing R3
  generation-fenced SQLite lease with matching worker, GitHub ID, repo,
  requested source SHA, and request digest.
- Require explicit operator review and 60 seconds minimum lease lifetime.
- Independently request public repository identity and current branch HEAD
  from GitHub through **existing R0.5 read-only GET**. Re-read HEAD twice
  per observation, repeat the observation after initial evidence review.
- Fail closed on move/rename/archive/privacy/lease expiry/fence/step mutation.
- Recheck R2 steward + lease once more after both independent observations.
- Report only the observed SHA, timestamps, worker label, local generation,
  and task/pack fingerprints; no bearer token or private database dump.

## What is *not* proven

This confirms a public GitHub HEAD **at review time** and the locally valid
lease on the same host. It does not authenticate the operator, remote worker,
PhiRepoNerve's claimed pack approval, or a task-specific sandbox executor.
The local R3 reservation was not enforced by a remote runner.
A later HEAD change remains possible, and local lease validity is not a
distributed execution fence.

R0.7's existing GitHub Actions artifact verifier is **specific to the fixed
PhiMadaPrime pilot**. Its success cannot be used to authenticate an
unrelated Construct training run. Training score/competence claims remain
false until a task-specific, independently corroborated executor artifact
with trusted provenance exists.

No Github writes, Docker runs, worker startups, deployment, merge, execution,
or broad competence assertions. No new required dependencies.

## Tests

```bash
PYTHONPATH=.:server pytest -q server/tests/test_construct_training_evidence.py
```


## Next

Define a fixed, authorized and resource-isolated training runner that emits
task-digest-bound results from an independent authority, then verify
GitHub run metadata and artifact SHA256 before accepting even a
bounded practical test result. Never promote directly from a JSON score
to remote code execution or merge authority.
