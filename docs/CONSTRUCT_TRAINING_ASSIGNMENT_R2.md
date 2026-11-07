# ΦConstruct R2: Operator-reviewed training binding to an existing Agentora R3 lease

**Status:** local, read-only adapter. No worker launch or code execution.

R1 accepted digest-pinned ΦLoad/ΦConstruct training handoffs. R2 adds
a binding to a **separately prepared** Agentora R0.3 held source intake
and an already-issued, fenced R3 worker reservation. The existing
R2 steward registry supplies current observed public GitHub identity.

No new rights or bearer capability arise from training input.

## Workflow

1. In PhiRepoNerve, approve the exact knowledge pack and export its
   v0.1 Construct training handoff JSON.
2. In Agentora, prepare an R0.3 held source verification intake for
   the exact public repository GitHub numeric ID and source SHA.
   Ingest the current public-only RepoNerve observation into Agentora's
   steward registry.
3. Preview binding **without a lease**:

   python scripts/construct_training_assignment.py \\
     --handoff request.json --intake verification-intake.json

4. Separately obtain an R3 local reservation for that repository using
   the existing Agentora operator workflow. The worker ID **must exactly
   equal** the training handoff's agent_label.
5. Review and bind to that existing lease:

   python scripts/construct_training_assignment.py \\
     --handoff request.json --intake verification-intake.json \\
     --lease-file ~/.agentora/private/worker-alpha.lease \\
     --confirm BIND_TRAINING_TO_EXISTING_LEASE

## Validation

- Reuse Agentora R1's strict handoff reader, pinned Welcome Charter,
  false authority flags, and self-consistent handoff SHA256 digest.
- Reuse existing R0.3 validation. R0.3 describes **held** source claims,
  not authenticated HEAD.
- Reuse R3 steward eligibility (recent source, public present/unarchived
  repo, stable GitHub ID and matching name).
- In confirmed mode, verify the **existing** capability through the R0.4
  lease ledger's secret-token check, generation, source SHA, GitHub ID,
  request digest and exact worker identity.
- Require at least 60 seconds remaining and recheck the steward and
  capability before reporting a local reviewed binding.
- Return no token, private inventory, lease file path, or secret digest.

## Important limits

`LOCAL_TRAINING_BINDING_REVIEWED_NO_EXECUTION` is a **point-in-time
observation**, not a capability or dispatch approval. The source HEAD
has **not** been independently re-observed via GitHub, and a local R3
lease cannot attest a future remote runner. The operator confirmation
is a local text action, not proof of an authenticated person's identity.
The pack approval remains an unverified claim from RepoNerve's JSON.
This version writes no binding journal or replay-prevention ledger.

Even if the receipt says the lease was current at review, the worker
must obtain independent effect-time source/lease checks through Agentora's
R0.5/R4/R5 controls before any tool execution, and an independent
executor must authenticate output before capability scoring. A passing
training exercise authorizes **nothing** about merges or deployments.

## Tests

```bash
PYTHONPATH=.:server pytest -q server/tests/test_construct_training_assignment.py
```

