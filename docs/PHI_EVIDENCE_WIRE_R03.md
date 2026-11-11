# Φ Evidence Wire R0.3: a REAL Lean kernel check of an ABSTRACT model

**Status: experimental PR candidate, not production authorization.**

This rung adds a genuine Lean 4 proof checker for a deliberately small formal
model of the Phi369 ecosystem's **capability-is-not-authority** principle. It
builds on Agentora R0.1 (GMED/R14/CLAVIS receipt correlation) and R0.2
(live GitHub evidence re-observation); it does not clone AlphaProof Code.

## Existing systems stay in their lanes

- **Agentora** holds development orchestration, audited mission evidence and
  independent review.
- **GMED** rechecks merge/CI evidence, not actual program semantics.
- **PhiStream/CLAVIS** maintains local research/model evidence, not merge power.
- **SuperPhiVessel** holds a separate signed operator governance boundary.
- **PhiMathAtelier** renders mathematical artwork. It is *not* a proof checker.

## What the formal model defines

`formal/phi-evidence/PhiEvidence.lean` defines three levels of observed
evidence and four potential permissions (code write, worker dispatch,
merge and deploy). Its theorems establish:

1. An evidence-only observation does **not** grant any of the four permissions,
   whether its declared tier is unverified, GitHub-corroborated or
   formally checked.
2. An explicit owner-approval HOLD prevents a modeled action.
3. A missing active branch-policy gate prevents a modeled action.
4. A mismatched exact source SHA gate prevents a modeled action.
5. Incomplete required CI prevents a modeled action.
6. A stronger evidence classification alone cannot change observed authority.

These theorems are checked by Lean's own kernel. This is a proof **about the
defined Lean model**, **not** a proof that our Python implementation matches it.

## Reproduce

The toolchain is pinned in `formal/phi-evidence/lean-toolchain`:
`leanprover/lean4:v4.35.0`. There are no Mathlib dependencies.

```bash
cd formal/phi-evidence
lake build --wfail
lake env lean -DwarningAsError=true PhiEvidence.lean
```

From Agentora root, after Lean and Lake are installed:

```bash
python scripts/phi_proof_model.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --output /tmp/phi-proof-model.json
```

The CLI checks the expected Git SHA, pinned toolchain, source size and
placeholder/unsafe-term guard, then **runs** Lake and Lean itself and creates
a JSON receipt only after both commands succeed. The receipt binds the
observed Git commit and SHA-256s of the Lean model, toolchain and the two
existing Python evidence adapters. It deliberately states
`source_code_behavior_proven=false` and `compiled_machine_code_proven=false`.

CI uses the SHA-pinned `leanprover/lean-action` installer and a read-only
token to run the same checker, then uploads the receipt as an expiring
GitHub Actions artifact. The ordinary Agentora pytest job executes offline
negative fixtures for wrong SHA, version drift, stale/missing files, forbidden
proof placeholders, failed checker commands and misleading authority claims.

## What this emphatically does NOT certify

- It **does not verify actual Agentora/PhiStream Python semantics or machine
  code**, compiled cryptography, security of Signal, or an actual GitHub
  merge policy. A formal model can be correct while an implementation
  diverges.
- It **does not** authenticate third-party GitHub metadata, R13 artifact
  bytes, cryptographic signatures or owner identity.
- It **does not** upgrade any agent or deployment permission.
- It is not a required branch-protection check yet. Treat the new workflow as
  **pilot evidence** until one real CI run is checked.
- A GitHub Actions result or receipt digest does not make the job an
  independent external prover; it records the tool run and exact source
  snapshot on that GitHub runner.

## Next rung, after CI field qualification

R0.4 should define a reviewed source-to-spec correspondence contract and
independently test it (including negative mutations to implementation code).
Only a later qualified, trustworthy checker of the **actual implementation**
could justify a stronger security claim or a reviewed required-check policy.
Never silently extend this model-only proof into automatic merge authority.

**Logic Above Lies · Ledger Above Ego · Truth Above Slop.**
