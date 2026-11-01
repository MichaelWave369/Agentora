# Φ Development Loop R2.2: Solo Sovereign Review Queue

**Status:** implementation candidate; read-only queue requires one successful field run on merged main before calling it operational. This rung **does not change any existing merge policy**.

## Goal

Show an operator one actionable view of open Agentora pull requests, candidate lane, bounded risk/scope, exact head SHA, required GitHub Actions checks, current main-branch rules and the **next human action**. Never confuse a queue recommendation with permission to merge.

R2.1 Solo Sovereign already succeeded on [PR #59](https://github.com/MichaelWave369/Agentora/pull/59): the owner manually applied \`phi-solo-automerge\`, the three required CI checks were green, the governance log reported \`R21_SOLO_EXACT_HEAD_CI_GREEN_MERGED\`, and GitHub attributed the resulting merge to \`github-actions[bot]\`. R2.2 adds visibility, **not broader automation**.

## No-local-install browser workflow

1. Open **[Φ Review Queue on GitHub Actions](https://github.com/MichaelWave369/Agentora/actions/workflows/devloop-r22-review-queue.yml)** after this implementation PR is manually merged.
2. Click **Run workflow** and select the default \`main\` branch.
3. Open the resulting Actions run, then its **Summary** section. It displays a Markdown table of the open PRs, candidate lanes, required CI state and exact next action.
4. Optionally download the 30-day \`devloop-r22-review-queue-<run_id>\` artifact containing the \`agentora.devloop.review-queue.v2.2\` JSON evidence snapshot.
5. Open each PR's **Files changed** tab to review its real exact-head diff. Do not rely on a previous or cached snapshot to authorize a later commit.
6. For eligible owner-authored solo UI changes, only **after** checking green CI, the diff and the exact SHA, manually apply \`phi-solo-automerge\` yourself. **Do not click Merge** if the intent is to test the governed auto-merge lane. The existing trusted \`devloop-automerge.yml\` is the only merge authority.

No local Agentora installation, SaaS relay, external model, or second collaborator is needed just to view the browser-only queue report.

## Agentora React page

The \`Review Queue\` navigation entry opens \`/review-queue\` in the existing React app. It uses the **public GitHub REST API directly** (read-only, no browser token, no local FastAPI dependency). Select **Inspect evidence** for a PR to load its exact SHA, file list, required check runs and ruleset evidence on demand. It links out to GitHub to inspect the real diff and actions.

**Deployment honesty:** This adds a route to Agentora's existing React source. It does not itself deploy or activate a public GitHub Pages URL. The GitHub Actions workflow above is the available browser-only path regardless of local hosting. Unauthenticated GitHub REST calls have rate limits and may be blocked in some browsers; errors must be displayed as **unverified**, never as an empty queue or approval.

## Queue interpretations

| Lane | Scope | What makes it a candidate | Required owner action |
| --- | --- | --- | --- |
| Docs | \`README.md\` and markdown under \`docs/\` only | 1–10 added/modified files, no holds, required CI green | Review exact diff and then apply \`phi-automerge\` |
| Solo | Owner-authored, one modified \`web/src/components/Nav.tsx\` file, at most 10 added + 10 removed and 16 total changes | Exact PR head, bounded complete patch and required CI green | Review exact diff and then apply \`phi-solo-automerge\` |
| Independently reviewed UI | 1–2 modified allowlisted UI components with size limits | Verified separate non-author GitHub collaborator approval on current SHA, plus green CI | Owner reviews and then applies \`phi-code-automerge\` |
| Manual | All other files, forks, drafts, broad changes, uncertain evidence | Not eligible for the automated lanes | Review manually, no automatic approval label |

The queue marks **OWNER_REVIEW_REQUIRED**, **CI_PENDING**, **CI_FAILED**, **REVIEW_REQUIRED**, **HELD**, **RULES_UNVERIFIED**, **OUT_OF_SCOPE**, etc. These are advisory classifications, not mergeability claims.

Every row includes \`merge_authorized: false\` in the JSON snapshot. In particular, an owner-facing instruction to apply a label is **not** an instruction for an agent to apply it automatically.

## Technical safety and limits

- GitHub Actions uses a \`workflow_dispatch\` trigger, **read-only** \`contents: read\`, \`pull-requests: read\` and \`checks: read\` permissions. There are no calls to label, approve, close or merge APIs.
- All data reads use HTTP GET against the fixed \`MichaelWave369/Agentora\` repository. The workflow checks out **trusted main scripts only** and never executes proposed PR code.
- The queue reads **all open PR pages up to a bounded maximum** and fails closed rather than silently claiming a complete list if more may exist. It also refuses incomplete small diffs, missing check records, truncated check lists and unexpected check providers. The public browser page visibly marks a possibly truncated 100-PR list.
- Active \`main\` ruleset inspection verifies that all three required CI contexts are still configured. If GitHub cannot provide those details, the recommendation is **RULES_UNVERIFIED**, not approval.
- If the GitHub REST call fails, the workflow emits a failing/held report and best-effort JSON artifact. It never replaces an API failure with an invented clean bill of health.
- For independently reviewed code, the server-side snapshot reuses Agentora's separate human-review verifier; the React UI deliberately does **not** claim to authenticate collaborator reviews.
- Review queue results are point-in-time observations. Apply labels only after fresh PR review. No guarantee of security is made from an allowlist or passing tests.
- The queue does not update the existing \`devloop-automerge.yml\` policy, expand the solo allowlist, install agents, dispatch next tasks, or merge any PR.

**Ledger Above Ego.** Keep the human authorization boundary visible, no matter how tempting it is to automate the last remaining click.
