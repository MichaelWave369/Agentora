import Init

set_option autoImplicit false

/-!
# Phi Evidence Wire R0.3: proof of an ABSTRACT authority model

This is deliberately not a proof of Python source code, compiled machine code,
GitHub API behavior, human identity, or the real security of any deployment.
It encodes a small, operator-reviewed non-escalation policy: evidence by
itself never confers action authority. No model or theorem here adds an
automatic approval or merge permission to Agentora.
-/

namespace PhiEvidence

inductive EvidenceLevel where
  | declared
  | githubCorroborated
  | formallyCheckedModel
  deriving DecidableEq, Repr

structure Authority where
  codeWrite : Bool
  workerDispatch : Bool
  merge : Bool
  deploy : Bool
  deriving DecidableEq, Repr

/- Evidence observations are not an authorization source. -/
def observedAuthority (_ : EvidenceLevel) : Authority :=
  { codeWrite := false
    workerDispatch := false
    merge := false
    deploy := false }

/- Independent permission inputs are required before any action. -/
structure PolicyGate where
  ownerApproval : Bool
  activeBranchPolicy : Bool
  exactSource : Bool
  requiredChecks : Bool
  deriving DecidableEq, Repr

def mayExecute (gate : PolicyGate) : Bool :=
  gate.ownerApproval && gate.activeBranchPolicy &&
  gate.exactSource && gate.requiredChecks

theorem observations_never_authorize (level : EvidenceLevel) :
    (observedAuthority level).codeWrite = false ∧
    (observedAuthority level).workerDispatch = false ∧
    (observedAuthority level).merge = false ∧
    (observedAuthority level).deploy = false := by
  cases level <;> decide

theorem owner_hold_prevents_action (gate : PolicyGate)
    (h : gate.ownerApproval = false) : mayExecute gate = false := by
  simp [mayExecute, h]

theorem branch_policy_hold_prevents_action (gate : PolicyGate)
    (h : gate.activeBranchPolicy = false) : mayExecute gate = false := by
  simp [mayExecute, h]

theorem source_mismatch_prevents_action (gate : PolicyGate)
    (h : gate.exactSource = false) : mayExecute gate = false := by
  simp [mayExecute, h]

theorem incomplete_checks_prevent_action (gate : PolicyGate)
    (h : gate.requiredChecks = false) : mayExecute gate = false := by
  simp [mayExecute, h]

theorem stronger_evidence_is_not_an_approval
    (a b : EvidenceLevel) : observedAuthority a = observedAuthority b := by
  cases a <;> cases b <;> rfl

-- Expose exactly which axioms Lean reports for these theorems.
#print axioms observations_never_authorize
#print axioms owner_hold_prevents_action
#print axioms branch_policy_hold_prevents_action
#print axioms source_mismatch_prevents_action
#print axioms incomplete_checks_prevent_action
#print axioms stronger_evidence_is_not_an_approval

end PhiEvidence
