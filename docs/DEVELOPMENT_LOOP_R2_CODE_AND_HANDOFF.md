# Φ Development Loop R2: governed code lane and next-rung handoff

**Status:** Candidate implementation. Do not call this code lane field-qualified until a genuine code PR merges through a successful, audited run. R0 documentation auto-merge remains a separate, already field-qualified lane.

## What R2 adds

1. **Tiny UI-code eligibility.** Only modifications to `web/src/components/Nav.tsx` and `web/src/components/TemplateGallery.tsx` qualify (1–2 files, no renames/additions/deletions, max 75 added and 40 removed lines, max 100 combined). Other paths, backend code, actions, scripts, tests, configs, dependencies and secrets stay ineligible.
2. **Human review gate.** The code PR must receive an actual GitHub `APPROVED` review on the **current exact head SHA** from a non-bot, non-author collaborator whose live permission is `write` or `admin`. An outstanding latest `CHANGES_REQUESTED`, stale approval, bot approval or unverifiable permissions cause a hold.
3. **Separate owner authorization.** Only `MichaelWave369` applying `phi-code-automerge` triggers the code lane. `phi-automerge` remains documentation-only. A PR with both labels is held.
4. **CI is non-negotiable.** All three existing Agentora required contexts (`backend (3.12)`, `backend (3.13)`, `web`) must have already passed on the exact PR SHA, and the main branch ruleset must still be enforced. R2 does **not** queue code merges while tests are pending or failed. Apply the label only after reviewer approval and passing CI.
5. **Explicit audit.** Every invoked governed merge run emits `agentora.devloop.merge-decision.v2` in a 30-day Actions artifact, recording PR identity, exact SHA, lane, disposition and bounded outcome/reason. Failed safety gates keep failing Actions visibly; no audit result grants merge authority.
6. **Post-merge handoff.** On each merged Agentora PR, a separate **read-only** workflow tries to find a task in the `approved-next-rung.json` manifest **as committed on the PR's pre-merge base SHA**. If a matching entry was approved before the source PR merged, it emits an exact-identity `READY_FOR_OPERATOR_DISPATCH` artifact. Otherwise it emits `NO_PREAPPROVED_NEXT_RUNG`. **This never dispatches an agent, opens a PR, or executes the task.**

## Operator field trial

First, review and manually merge the R2 implementation PR after normal CI is green. The implementation PR itself changes protected code/workflow files and is **not eligible** for either autonomous merge lane.

For the first code-lane trial, have a **second trusted GitHub collaborator with write or admin access** review an independently created, tiny PR changing only one of the two allowlisted UI components. The author cannot count as the independent reviewer. Wait for the three required CI jobs to succeed; inspect the diff and review, then **as MichaelWave369** apply `phi-code-automerge`. The workflow verifies those requirements again before sending a SHA-pinned squash merge. Confirm both the GitHub merge record and the `devloop-merge-decision-...` artifact.

If there is no independent reviewer with verified collaborator write permission, the lane correctly holds at `R2_INDEPENDENT_WRITE_REVIEW_REQUIRED`; do not invent a model approval or disable that check. You can still use the existing docs-only lane.

## Approving one future handoff

Before the *source* PR merges, add a manifest entry in a **separate, already-merged, reviewed commit to main**. The manifest at `examples/development-board/approved-next-rung.json` begins empty on purpose:

```json
{
  "schema": "agentora.devloop.approved-next-rung.v1",
  "items": [
    {
      "source_pr": 123,
      "source_head_sha": "0000000000000000000000000000000000000000",
      "approved_by": "MichaelWave369",
      "target_repo": "MichaelWave369/Agentora",
      "task_id": "agentora-next-123",
      "title": "Review the next bounded Development Board proposal"
    }
  ]
}
```

Replace example number and SHA with the real prospective source PR, **never use the all-zero example SHA**. `approved_by` is a declaration in a reviewed repository manifest, not cryptographic identity proof. The workflow reads the manifest from GitHub's immutable **pre-merge base commit**, not from files changed by the source PR, then compares the source PR number and SHA. A changed head invalidates the entry. It does not automatically run the task.

## Safety and limitations

- A UI change can still be dangerous. Path/size classification is only an eligibility screen, **not** a security audit. Independent review is mandatory.
- There is no self-review, model-judged merge authority, fork merging, workflow/policy self-modification, PAT, privilege bypass, generalized code-automerge, cross-repo writes or remote model relay.
- The privileged merge job checks out **trusted main only**, never PR-head code. The second handoff job runs with **contents: read**, and its manifest is fetched by exact pre-merge SHA.
- The Github Actions upload-artifact evidence is retained only 30 days and is not a permanent, independently signed ledger. A later stage should add durable evidence storage and independent replay.
- The next-task handoff is **read-only**. Integrating Agentora, PhiBot or PhiServe for actual next-rung creation requires another explicit, separately audited permission boundary.
- R0 still has an unqualified *pending-CI native GraphQL* path. R2 intentionally only merges already-green code; errors remain holds, not excuses to weaken checks.

**Ledger Above Ego. An approval is evidence for a narrow action, not an invitation to start building whatever an agent dreams up.**

## Read-only online code advisory

The additional `Phi Development Loop R2 - code candidate advisory` GitHub Actions workflow reacts to PR openings, changes, reopening, draft-to-ready transitions and review submissions/dismissals. It checks out **only trusted main**, then fetches PR metadata, its bounded changed-file list and any current-SHA independent reviewer evidence through read-only GitHub APIs. It publishes a 30-day `devloop-r2-advisory-...` JSON artifact with `LOW_RISK_UI_CANDIDATE` or an explicit out-of-scope reason. An advisory report is **not** CI approval, a security review, or permission to merge. The actual code merge gate independently performs fresh required-CI, review, author and exact-head checks after the owner applies the label. The advisory cannot modify a PR or invoke a merge.

The workflow intentionally does not download or execute model weights or candidate source. If a user modifies a PR after an approval, the review must be repeated on the changed SHA. The advisory's receipt is a convenience, not a durable signed audit.
