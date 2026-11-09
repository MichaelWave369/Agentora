# Fleet R14: verified audit evidence into a human-controlled Mission

GitHub-only follow-up to the **successfully field-tested** R13 public metadata
audit and the separate automatic evidence QA workflow.

No local installation, SQLite, user-managed token, local agent, desktop CLI
or new infrastructure.

## What changes

R12 Issue #132 remains the authoritative mission planning record.
R13 remains two **read-only** GitHub-hosted jobs:

- Audit: https://github.com/MichaelWave369/Agentora/actions/runs/42551226704
- Separate automated evidence QA:
  https://github.com/MichaelWave369/Agentora/actions/runs/42551247697

R14 adds one owner-triggered GitHub Actions handoff that independently checks
the exact original R13 audit and R13 QA artifacts and appends an auditable
**R14 evidence comment** to Issue #132. It does not tamper with R12's existing
triage/proposed-role journal or misleadingly set it to QA_APPROVED.

It also offers a second **distinct owner acknowledgement** step.
The explicit statement indicates the owner has reviewed the evidence in
the browser. It does not make them an independent external human QA reviewer
or confer merge, deploy, or agent write authority.

## Browser-only workflow after PR merge

1. Open the original [R13 audit run](https://github.com/MichaelWave369/Agentora/actions/runs/42551226704) and [R13 automated QA run](https://github.com/MichaelWave369/Agentora/actions/runs/42551247697).
   Review their Summary pages. Inspect their retained artifact receipts if
   desired. Both run IDs must still be within seven days.
2. Open [Fleet R14 Verified Evidence to Owner Review Gate](https://github.com/MichaelWave369/Agentora/actions/workflows/fleet-r14-mission-handoff.yml).
   Choose Run workflow on main, and enter:

   - command: link
   - issue_number: 132
   - audit_run_id: 42551226704
   - qa_run_id: 42551247697
   - confirmation: LINK_VERIFIED_R13_EVIDENCE

   The workflow cross-checks the actual GitHub-owned source, run and ZIP
   evidence, then writes exactly one R14 Issue comment. That comment links
   both runs and their GitHub-verified SHA-256 digests. Any mismatch HOLDS.
3. Open [Mission #132](https://github.com/MichaelWave369/Agentora/issues/132)
   and inspect the new R14 evidence comment. The state should be
   EVIDENCE_LINKED_PENDING_OWNER_REVIEW.
4. After personally reviewing the two linked run summaries and receipts,
   run the same workflow a second time with:
   - command: acknowledge
   - issue_number: 132
   - audit_run_id: 42551226704
   - qa_run_id: 42551247697
   - confirmation: I_REVIEWED_R13_RECEIPTS_NO_MERGE_APPROVAL

   This creates a second R14 journal comment, state
   OWNER_REVIEW_ACKNOWLEDGED_NO_APPROVAL. It is an owner attestation about
   reviewing evidence, **not an independent human QA certificate**.

An R14 command runs once. Replays, changed Issue text, changed source HEAD,
expired artifact, forged approval, and mismatched run references HOLD.

## GitHub branch protection is a prerequisite for code-writing agents

The latest live check found the public PhiMadaPrime default branch main was
**not protected** (GitHub branch protection metadata: protected=false,
required status checks disabled). This is not a failure of R13 read-only
auditing; it is a blocker to any later autonomous code-write work.

Before any future code-writing worker is authorized, configure an effective
GitHub ruleset/branch protection policy through repository Settings:

- Require pull requests for changes to main
- Require independent human review of code changes, not self-approval
- Require the actual verified CI checks used by the target repository,
  only after checking their exact names and success history
- Block force pushes, deletions and unauthorized bypasses
- Keep agent credentials scoped to a branch/PR workflow, not broad main pushes

Exact options depend on repository/plan permissions and existing CI. R14
only **reads** branch protection status. It never silently changes settings.
Even protected=true would not, by itself, confer code-write authority: R14
always reports code_write_blocked=true. A later separately reviewed policy
must verify the complete ruleset, distinct QA, least-privilege installation
and protected default branch before granting code-write access.

## Trust boundaries

- The workflow is **owner-only**, manual, pinned to main with an explicit
  per-command confirmation; no schedule, Issue/PR trigger, model call or
  background task.
- R14 reads the original GitHub R13 audit artifact through R13's existing
  independent QA verifier, then downloads the original R13 QA ZIP and
  checks the GitHub artifact SHA-256 against the exact bytes.
- It cross-checks the QA receipt **field for field** against a fresh
  independent GitHub audit/Issue/source re-evaluation. The returned source
  SHA must still be live on the target default branch.
- The GitHub API bearer token is used only for GitHub calls. Original ZIP
  downloads use the hardened R11 allowlisted HTTPS signed-storage redirect,
  without forwarding Authorization headers.
- The only write is one bound **Issue comment**. No Issue edits, code writes,
  worker dispatch, PR creation/approval, merge or deployment.
- R14 journal records are authored by github-actions[bot], sequential,
  issue-body-digest bound and checked for editing. As with R12, this is
  an audit trail managed by GitHub, not a cryptographically signed ledger.
- A successful automated QA recheck remains **automated**. It is distinct
  from independent human approval; code_write_blocked remains true.
- GitHub Actions receipts are retained for 14 days, but original R13 ZIPs
  only for 7 days. Expired source evidence is a HOLD.

## Exact-head CI

GitHub CI runs the new 16 adversarial regression tests alongside all
existing Agentora backend and web checks. No local setup required.

After one successful R14 link/acknowledge field test, the next governed
rung should be a repository protection policy and *review-only* hosted
worker changes proposed as PRs. Never auto-enable generic code writes.
