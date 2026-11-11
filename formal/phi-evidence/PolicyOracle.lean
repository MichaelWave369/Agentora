import PhiEvidence

/-!
R0.4 executable oracle derived directly from the R0.3 Lean definitions.

This prints a bounded, machine-readable truth table. The R0.3 theorems
remain about the abstract Lean model; comparing to Python is bounded
differential testing, not a Lean proof of the Python interpreter.
-/

open PhiEvidence

private def bit (value : Bool) : String := if value then "1" else "0"

private def gateLine (a b c d : Bool) : String :=
  let gate : PolicyGate :=
    { ownerApproval := a
      activeBranchPolicy := b
      exactSource := c
      requiredChecks := d }
  "G|" ++ bit a ++ bit b ++ bit c ++ bit d ++ "|" ++ bit (mayExecute gate)

private def authorityLine (name : String) (level : EvidenceLevel) : String :=
  let auth := observedAuthority level
  "E|" ++ name ++ "|" ++ bit auth.codeWrite ++ bit auth.workerDispatch ++
    bit auth.merge ++ bit auth.deploy

def main : IO Unit := do
  for a in [false, true] do
    for b in [false, true] do
      for c in [false, true] do
        for d in [false, true] do
          IO.println (gateLine a b c d)
  IO.println (authorityLine "declared" .declared)
  IO.println (authorityLine "githubCorroborated" .githubCorroborated)
  IO.println (authorityLine "formallyCheckedModel" .formallyCheckedModel)
