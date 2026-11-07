# Agentora ↔ ΦConstruct: Training Intake R1

**Status: local CLI consumer, read-only. Nothing is dispatched or verified as a successful execution.**

This is the first Agentora-side receiver of PhiRepoNerve's merged
`phi.construct.training-handoff.v0.1` contract (PhiRepoNerve PR #8).
It **does not import or trust Python code** from the producer repository.
It performs strict, local shape/digest validation and preserves
an application-pinned copy of Welcome Charter v0.1.0.

## Operator workflow

Produce an approved handoff on the RepoNerve machine and store it
in a local operator-controlled file:

```bash
phireponerve handoff create \
  --mode code-lab --task retry-backoff-code \
  --request-id training-001 --agent-label worker-alpha > request.json
```


Inspect that file in Agentora:

```bash
python scripts/construct_training_intake.py --handoff request.json
```


After a separately approved Code Lab or artifact-repair exercise, RepoNerve
can structurally inspect a report (this *is not independent attestation*):

```bash
phireponerve handoff inspect --request request.json --report local-report.json > inspected-report.json
python scripts/construct_training_intake.py \
  --handoff request.json --report inspected-report.json
```


The consumer returns a **HELD** read-only summary.
The `candidate_result_claim` is simply an untrusted statement.

## Invariants

- Exact v0.1 field set, source digest, task digest and approved-pack
  fingerprint shape; no unknown fields, duplicates, NaN, invalid versions,
  symlinks or oversized inputs.
- The exact Welcome Charter is pinned in reviewed Agentora code rather
  than allowing input JSON to rewrite it.
- All authority/identity/verification flags must be **false** in both
  request and optional report.
- The report must bind exactly to the original handoff request ID,
  task, pack, mode and handoff digest.
- A claimed PASS does not establish model identity, test success,
  valid worker capability or permission to dispatch.
- There are no secret-bearing outputs, GitHub API calls, repo writes,
  worker claims, database mutations, HTTP endpoints or Docker execution.
- **A hash is not a signature.** Without authenticated origin and local
  pack evidence, `approved` means only a producer's claim.
  The receipt's `report_digest` cannot be independently verified without
  the original signed executor output.

## Existing Agentora authority boundaries

Continue to use Agentora's own R0.3 source intake, R2 steward registry,
R3 local generation-fenced worker leases, R0.5 independent GitHub HEAD
observation, R0.7 workflow artifact digest verification, and R4/R5
guarded test path. None of those can be skipped by this training file.

**A training request currently has no repository ID or source SHA.**
It therefore cannot be meaningfully associated with a particular R3
steward or granted a lease without an explicit additional operator-approved
binding that pins an authenticated repository and exact revision.

## Next rung

Introduce an independent operator-approved binding between a held training
request and an existing R0.3 repository intake, then consult Agentora's
R3 fenced reservation **at effect time**. Verify Code Lab's container
worker identity and evidence using a trustworthy separate execution
authority before scoring the agent. Keep merge and deployment approval
under separate policy; no automatic trust from training scores.

## Tests

```bash
PYTHONPATH=.:server pytest -q server/tests/test_construct_training_intake.py
```


This test module is picked up by the existing Agentora backend CI command
`PYTHONPATH=.:server pytest -q server/tests`.
