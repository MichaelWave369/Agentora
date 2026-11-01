# Φ DevLoop R2.3 · Solo Sovereign Review Dashboard

**Implementation status:** candidate until a genuine GitHub Actions dashboard run completes and its evidence is examined. The existing R0, R2.1 and R2.2 governance rules are unchanged. This feature is **read-only**.

## What this adds

The Review Dashboard combines three evidence streams in a single operator view:

1. **Current PR Review Queue:** open PRs, candidate lanes, exact head SHA, required CI, protected-main ruleset, and next *manual* action. It reuses the existing R2.2 strict queue logic.
2. **Historical merge decisions:** recent *retained* merge-decision artifacts from the trusted-base DevLoop workflow. A green workflow is **not** a successful merge. The dashboard separately checks GitHub's live PR record, exact original head SHA, main branch, and merger attribution to github-actions[bot].
3. **Post-merge next-rung handoffs:** recent retained read-only handoff artifacts. NO_PREAPPROVED_NEXT_RUNG means no task was preauthorized. READY_FOR_OPERATOR_DISPATCH means a read-only task handoff was prepared, **not** that an agent executed it.

Past R2.2 queue snapshots appear in their own history section and must retain can_merge=false. Failed or missing artifacts show EVIDENCE_HELD; they are never treated as green.

## Browser-only, no-local-install use

After reviewing and manually merging the implementation PR:

1. Visit [Phi Development Loop R2.3 - Review Dashboard](https://github.com/MichaelWave369/Agentora/actions/workflows/devloop-r23-dashboard.yml) on GitHub Actions.
2. Click **Run workflow** on main.
3. Open the completed run's **Summary**. It contains a read-only Markdown dashboard with live PRs, recent merge receipts and independent GitHub attribution, handoffs, queue history and missing-evidence warnings.
4. Download the devloop-r23-dashboard artifact for the machine-readable bounded JSON snapshot.
5. Review any candidate PR's **Files changed** directly in GitHub before personally applying its authorized label; the dashboard never labels or merges it.

The React app also gets a **Review Dashboard** route at /review-dashboard, next to /review-queue. That browser page uses GitHub's **public read-only API** to show open PRs and recent workflow statuses. It deliberately does **not** infer merge success or receipt content from a green workflow. The GitHub Actions dashboard performs those deeper checks with temporary read-only GitHub permissions.

**Deployment distinction:** this React route does not deploy its own GitHub Pages website. The Actions workflow is the hosted path; no local installation or cloud model is required.

## Evidence and boundaries

| Evidence | Source | What it proves |
| --- | --- | --- |
| Open PRs and CI | Live GitHub API, bounded R2.2 queue | Candidate scope/next-action advisory, **never authorization** |
| Merge-decision receipt | Trusted-main Actions artifact, schema agentora.devloop.merge-decision.v2 | What the governed gate reported |
| Verified bot merge | Receipt + GitHub PR matching number/head/main and bot attribution | GitHub bot actually merged the identified PR |
| Next-rung receipt | Trusted-main Actions artifact, schema agentora.devloop.next-rung-receipt.v1 | Whether a preapproved read-only handoff was prepared |
| Archived queue | R2.2 Actions artifact with can_merge=false | Point-in-time queue observation, not authority |
| Workflow status | GitHub Actions metadata | Whether a run completed, not whether the action in its title happened |

The dashboard has no write methods, no credential forwarding to PR code, and no worker/model dispatch. The workflow only requests contents:read, pull-requests:read, checks:read and actions:read; checkout targets **trusted main**, never PR code.

### Sampling and retention

- The GitHub Actions report samples the **12 most recent runs** of governed merge, **12** of post-merge handoff, and **6** of R2.2 Review Queue. This is **not an exhaustive history**.
- Existing artifacts are retained for **30 days**. Once deleted or expired, the dashboard marks evidence as missing. **Absence of evidence never proves an event did not happen.**
- The collector bounds ZIP and JSON size, ZIP members, paths and GitHub API list sizes; it rejects unknown schemas and unsafe redirects. A successful merge is counted only when the receipt and actual GitHub merge record agree.
- A green Actions run is neither an independently signed receipt nor a substitute for code review.
- GitHub GITHUB_TOKEN event-triggering restrictions can mean bot-initiated merges do not independently launch the post-merge handoff workflow. **A missing handoff is not automatically proof that nothing was approved.**
- When evidence cannot be read, the dashboard holds instead of inventing values. Metrics are limited to the sampled history.

## Qualification

First field run: manual workflow execution on merged main. Confirm current PR/CI/ruleset reads are valid, a known bot-merged PR such as [#59](https://github.com/MichaelWave369/Agentora/pull/59) or [#61](https://github.com/MichaelWave369/Agentora/pull/61) is VERIFIED_BOT_MERGE if its receipt remains retained, and handoff reports are correctly marked read-only. Verify the JSON has can_merge:false and can_dispatch:false.

Negative tests cover archive overflows, duplicate records, path traversal, changed or manually merged PR attribution, forged decisions, executable handoff claims, missing/expired artifacts, limited history, and failure reports.

**Ledger Above Ego. The dashboard observes the loop; it never becomes the loop's authority.**
