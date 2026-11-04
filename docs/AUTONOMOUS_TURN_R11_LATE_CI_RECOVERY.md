# Autonomous Turn R1.1: late-CI recovery

## Why it exists

In the first hosted R1 attempt, original run 41875250182 planned the task,
passed the exact owner approval, ran the bounded worker, published bot-authored
PR #87 at 2441faaddcdba66ab9261866d875a8db512413ed, and observed CI.
GitHub Actions job visibility was delayed: the observer returned
CI_PENDING_TIMEOUT, so the R1 merge gate correctly skipped. The required
push/PR backend and web checks subsequently became green. This **does not**
mean R1 automatically merged PR #87 or that product acceptance is complete.

The recovery workflow only handles a completed original R1 attempt-0
documentation task with max_repairs=0 and an immutable CI_PENDING_TIMEOUT
observation. It reuses the existing R1 finish() verifier: exact task,
original owner approval, original proposal and sandbox receipts, branch/tree,
required CI on the current immutable PR SHA, repository rules, review policy,
SHA-pinned squash merge and postmerge readback. It cannot generate code.

## Security boundaries

- Manual workflow_dispatch must be by the named owner on trusted main,
  attempt 1. A re-run of the recovery run does not count as a new approval.
- The original GitHub-owned environment review must still be valid.
- A **second** GitHub-owned environment review must be made on the fresh
  recovery run, with an exact recovery-specific comment containing task digest,
  original run ID, PR number and original immutable PR head SHA.
- Original run must be completed successful (not a failed or in-progress run)
  and the saved observer receipt must say CI_PENDING_TIMEOUT.
- Downloads immutable original-run task, proposal, sandbox, published PR and
  observer artifacts; no new worker process, App installation token or key.
- Current main must still equal the original authorized source SHA. This
  prohibits silent rebases, drift, unrelated merged infrastructure and changed
  tree contents. The original task expiry still applies.
- Recovery only serves docs attempt-0 without repair allowance. A task with
  code changes or later repair attempts is not eligible.
- A failed or missing current CI check cannot be overridden. No bypass flag,
  altered ruleset, automation label, forged approval or pending CI is accepted.
- Exact authorized PR merge may be blocked by GitHub rules or original task
  expiry. The workflow retains a bounded hold artifact and does not claim
  success.

## Operator procedure (after separately reviewing/merging infrastructure)

1. If the source of the old task has moved, **do not use recovery**. Instead
   prepare a fresh current-source task in PhiMada and approve that turn.
   The first #87 source is e2a31ff840c218d9a130b7f5ff6b57ba02130cc7:
   landing this infrastructure change on main will itself change that SHA.
   Thus this rung does not promise retrospective recovery of #87.
2. For an eligible future CI timeout whose source has not moved, open
   Actions → Autonomous Turn R1 - late CI recovery → Run workflow. Select main.
3. Provide the original completed R1 run ID, PR number, exact PR head SHA,
   and the original 64-character task digest. These are coordinates, not
   authorization.
4. Inspect the plan's summary and original artifact details. The plan must
   succeed, confirming original valid review, bounded scope, CI timeout and
   unchanged source.
5. Select Review deployments for autonomous-turn-owner. Personally approve
   with the **complete literal recovery-specific comment** from the new plan
   summary. A mere click with an empty or different comment will hold.
6. Inspect the finish job, actual PR merge record and recovered receipt.
   Success requires GitHub's real merge SHA, parent and blob readback; if held
   consult the retained reason and do not re-run the same approval.

For PR #87 specifically, the existing owner-applied docs phi-automerge label
may be used under its **separate existing** GitHub policy while its docs
diff/current CI are eligible. That path is not R1 merge-gate qualification.
Never have the bot apply its own owner authorization label.

## Evidence boundary

The synthetic API tests exercise successful same-source recovery and
negative approvals, changed heads, source drift, replayed runs and wrong
timeout artifacts. Hosted owner-review, artifact retrieval and a live recovered
merge are **not field-qualified** until an actual future recovery succeeds.
MERGED, AUTOMATED CHECKS PASSED and PROJECT VERIFIED COMPLETE stay distinct.
