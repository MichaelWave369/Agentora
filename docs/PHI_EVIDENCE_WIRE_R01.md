# Phi Evidence Wire R0.1 · stitch the evidence, not the authority

**Status: draft integration, not an enabled release gate.** This adds one
read-only CLI to the existing Agentora orchestrator. It consumes the **actual
current schemas** of three already-built systems, rather than starting a new
repository or copying another project's formal-verification implementation.

## Existing systems and responsibilities

| Source | Existing surface | What R0.1 consumes |
| --- | --- | --- |
| **GMED** | `src/verifier.js`, `scripts/gmed.mjs` | A `gmed-report:v1` JSON report for the exact **merged commit SHA** |
| **Agentora** | Fleet R13 independent evidence QA + R14 owner handoff | The `agentora.fleet.r14.evidence-handoff.v1` JSON record for that exact target default-branch source SHA |
| **PhiStream** | CLAVIS R0.3 offline qualification | Optional **public summary** `phistream.clavis.qualification-review.v0.3`; never private prompts, answer keys, or receipts |
| **SuperPhiVessel** | Signed passport and governed operator ledger | Remains its own authority domain. R0.1 **does not** treat a Vessie approval as software merge permission |
| **PhiMathAtelier** | Offline mathematical art, VJ and alchemical geometry | No integration to proof verification; it is not a Lean/theorem prover |

**Important SHA boundary:** GMED reports the PR's merged commit SHA; R14
reports an audited default-branch source SHA. They can be correlated **only**
when these are actually the same 40-hex commit. An older R14 report and a
newer merge must HOLD rather than imply a shared outcome.

## Usage: local offline reconciliation

Produce the GMED JSON using GMED's existing CLI after GitHub confirms the
merge, and export the R14 JSON from the existing Agentora R14 owner handoff
receipt. Run a live independent GitHub recheck **separately** before trusting
either copied JSON file.

```sh
python scripts/phi_evidence_wire.py \
  --repo MichaelWave369/PhiStream \
  --sha 0123456789abcdef0123456789abcdef01234567 \
  --gmed /path/to/gmed-report.json \
  --r14 /path/to/agentora-r14-record.json
```

For an optional *sanitized, local* PhiStream CLAVIS qualification summary:

```sh
python scripts/phi_evidence_wire.py \
  --repo MichaelWave369/PhiStream \
  --sha 0123456789abcdef0123456789abcdef01234567 \
  --gmed /path/to/gmed-report.json \
  --r14 /path/to/agentora-r14-record.json \
  --clavis /path/to/clavis-public-summary.json
```

The SHA shown is **illustrative**. Use the *real exact source SHA* from both
evidence sources, not a branch name or a guessed value. R14 currently
operates on a bounded, owner-selected public mission and may have no
matching record for a proposed target; in that case no correlation is
possible. CLAVIS private dataset, blind pack, key and source receipts
must not be uploaded or supplied here.

Output on success is a versioned JSON receipt with state
`CORRELATED_REVIEW_ONLY` and SHA-256 fingerprints of the *supplied*
summaries. Exit code 2 means HOLD. There are no network requests, model
calls, GitHub API writes, PR actions or automatically granted permissions.

## Security invariants

- The target repository and exact 40-character source commit must match
  the declared R14 target/source and the GMED merged commit.
- GMED must declare a merged PR, a successful observation, coherent
  check-run arithmetic and at least one actual success. A skipped or
  neutral check alone is never sufficient.
- R14 owner acknowledgement is **not** QA independence. Every receipt
  must explicitly deny code writes, worker execution, merge and deploy.
- CLAVIS is research-only, not source-commit-bound, not formal software
  verification and not evidence of a qualified specialist model.
- The wire never issues or verifies cryptographic signatures, queries
  GitHub or executes a theorem checker. Copied JSON can be forged.
- `CORRELATED_REVIEW_ONLY` means the supplied reports are internally
  compatible, **not** independent source authentication, a valid Lean
  proof, successful human review, permission to dispatch a model, or
  approval to merge software.

## Qualification and next honest rung

CI runs `server/tests/test_phi_evidence_wire.py` under Agentora's
existing backend pytest job. Synthetic fixtures exercise normal input and
fail-closed cases (stale SHA, wrong repository, counterfeit green, false
owner acknowledgement, privilege escalation, leaked CLAVIS fields).

**R0.2 should be a separate reviewed PR:** a trusted GitHub-hosted,
read-only verifier should fetch and independently corroborate actual GMED
and R14 evidence from pinned GitHub runs and current target SHA, avoiding
reliance on self-declared JSON. A later, separately supervised proof
backend can execute an approved, reproducible Lean/other proof checker over
pinned implementation and theorem sources, and record its independently
observed result. Only after those are field-tested should the governed
operator discuss whether proof evidence can become a *required CI check*.
No generic code auto-merging is authorized by this wire.

**Logic Above Lies · Ledger Above Ego · Truth Above Slop.**
