# Φ Evidence Wire R0.4 · bounded Lean ↔ Python correspondence

**Status:** Candidate pending real GitHub CI, Lean oracle execution and
operator review. No auto-merge authorization.

R0.3 already established six mathematical statements of an abstract
evidence/authority model. R0.4 tests whether an actual, **read-only
adapter in Agentora's existing** `scripts/devloop_r2_policy.py` agrees
with the corresponding Lean calculations for *all finite inputs*.

## What is connected

- `formal/phi-evidence/PolicyOracle.lean` imports the **existing**
  `PhiEvidence.lean`, evaluates `mayExecute` for **all 16** boolean
  PolicyGate combinations, and evaluates `observedAuthority` for all
  **three** evidence tiers. There are no hardcoded expected oracle rows.
- `scripts/devloop_r2_policy.py` now includes
  `correspondence_policy_snapshot`, a deliberately pure, **advisory**
  function. It does not change, invoke or replace any privileged DevLoop
  merge/check/approval routine.
- `scripts/phi_policy_correspondence.py` runs the actual pinned Lean
  oracle, parses exactly 19 expected rows, executes **48** Python adapter
  combinations and fails closed on any mismatch or extra/missing row.
- The GitHub workflow kernel-checks the R0.3 theorem model first, then
  executes the R0.4 finite comparison on **the same GitHub checkout**,
  preserving separate SHA-256 source-bound JSON receipts.
- `server/tests/test_phi_policy_correspondence.py` includes deliberately
  corrupted Python gate logic, authority escalation, malformed oracle
  rows, missing vectors, wrong source SHA and toolchain drift.
  These regression fixtures do not pretend to run Lean themselves; CI
  runs Lean separately.

## Why the result is carefully named

The R0.3 function `mayExecute` computes the conjunction of **four
abstract boolean inputs**: operator approval, active branch policy,
exact-source binding and required check completion. It does **not**
authenticate or fetch those facts, and it does **not** grant merge
authorization. The companion Python adapter mirrors this calculation
but always returns `action_authorized=false`, even for all four true.

**Model coherence is not implementation verification.** The Lean theorem
proves properties only of the Lean model. This finite differential test
establishes that the *tested* Python adapter gives the same values for
the specified bounded inputs. It does **not** prove the entire Python
policy, the actual DevLoop privileged merge path, GitHub authentication,
machine code, cryptography, or that real-world observations are valid.

The result is therefore named
`LEAN_PYTHON_FINITE_CORRESPONDENCE_REVIEW_ONLY`.
It is not a mathematical proof of Python code. It gives no code-write,
merge, dispatch, deployment or model-routing permissions.

## Reproduce locally

Install the repo-pinned Lean 4.35.0 and Lake version. From repository root:

```bash
cd formal/phi-evidence
lake build --wfail
lake env lean -DwarningAsError=true PhiEvidence.lean
lake env lean --run PolicyOracle.lean
cd ../..
python scripts/phi_policy_correspondence.py \
  --expected-sha "$(git rev-parse HEAD)" \
  --output /tmp/phi-evidence-r04.json
```

On Windows PowerShell, pass the result of
`git rev-parse HEAD` using PowerShell syntax and select a receipt path
**outside** the repository.

The model runner requires strict source files, a pinned toolchain,
and the actual Lean evaluator. Mismatches exit with code 2 without
creating a success receipt. No tokens, GitHub writes or model inference
are required.

## What qualifies a later rung

After genuine PR and post-merge CI, R0.5 could use independently
designed adversarial fixtures to compare narrow **existing, privileged
gate functions** under mocked API conditions, and validate required
check attribution / SHA drift / manual authorization. That remains
behavioral testing, not a Lean proof of implementation. A stronger
formal assurance claim requires a reviewed refinement relation between
the formal specification and production semantics plus a trustworthy
checker and source mapping.

**Logic Above Lies · Family Above Indifference · Truth Above Slop.**
