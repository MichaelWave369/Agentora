# Φ Development Loop R2.1: Solo Sovereign Mode

**Status:** implementation candidate. The R2.1 solo-code merge lane is **not field-qualified** until a real one-file test PR is automatically merged by `github-actions[bot]` with a successful, inspectable decision receipt. Do not mark the new lane operational based on CI alone.

## Why this lane exists

Agentora has a proven docs-only auto-merge lane (`phi-automerge`) and a separate independent-review code lane (`phi-code-automerge`). The repository owner currently has no second collaborator to review code. R2.1 adds a **strictly bounded owner-authorized code lane** instead of fabricating independent approval or lowering the requirements of the existing code lane.

Owner authorization is **not independent review**. It means the owner inspected the proposed changes and deliberately applied a label to the current PR head after the required tests finished. The automation then performs repeatable policy checks and the actual merge.

## Owner-operated procedure

1. Create the GitHub issue/PR label `phi-solo-automerge` in Agentora. Do not apply it to the R2.1 implementation PR.
2. Create a normal, open, **owner-authored**, same-repository PR to `main`, modifying **only** `web/src/components/Nav.tsx`. Do not include workflows, backends, dependencies, access controls, manifests, tests or a second file.
3. Wait until `backend (3.12)`, `backend (3.13)`, and `web` pass on the exact PR head SHA. A green advisory report is not equivalent to green CI.
4. Personally inspect **Files changed**, make sure it is the same commit that passed CI, and check for unexpected new behavior.
5. **As the repository owner**, add the exact `phi-solo-automerge` label. Do not combine it with `phi-code-automerge` or `phi-automerge`. Applying the label is a deliberate, owner-only approval event. An AI agent or integration must not apply it for you.
6. Inspect the `Phi Development Loop - governed auto-merge pilot` GitHub Actions run. Successful decisions emit `R21_SOLO_EXACT_HEAD_CI_GREEN_MERGED`, and the `devloop-merge-decision-...` artifact records `lane=solo`. Confirm the final PR shows `github-actions[bot]` as the merger.
7. If a gate holds, review the reason. For a changed commit or an early label, only reapply the label **after** re-reviewing the exact new head and its green CI. Never use retry as a substitute for review.

## Non-negotiable constraints

- Only `MichaelWave369` is permitted as both **the PR author** and **the user who applies** `phi-solo-automerge`.
- Same-repository, ready, open PR targeting `main`. No forks, no draft PRs, no bot-authored PRs in this first pilot.
- Exactly one **modified** file: `web/src/components/Nav.tsx`. Never add, delete or rename files.
- At most 10 added, 10 removed, and 16 total changed lines. Reject omitted/truncated patches and other invalid diff evidence.
- Reject simultaneous docs, reviewed-code, or solo-code labels, and every explicit hold/security-review label. The docs and independent-review lanes also reject the solo label when mixed.
- GitHub's required CI contexts must all show complete **success on the exact head SHA** and originate from GitHub Actions. Pending, failed, missing, forged, or truncated evidence causes a hold.
- Re-fetch PR identity, labels, exact head, merge-base SHA and the live file list immediately before sending a SHA-pinned squash merge. Repeat required CI checks and verify the main branch ruleset again.
- No GraphQL queue, auto-merge while CI is pending, self-modifying policy, privileged workflow changes, model-executed PR code, force/admin bypass, or cross-repository write.
- GitHub still enforces its branch ruleset. A refused merge is a hold, not permission to bypass a rule.

## Safety model and limitations

Small diffs are **not guaranteed harmless**. An intentionally malicious tiny JSX change can still be dangerous. This is an **owner-reviewed** path, not an automated security audit. No AI-generated comment can substitute for the owner's review. Keep sensitive code changes on a separate human-review workflow.

The initial allowed file is intentionally narrower than R2's two-file independent-review lane. Do not expand that allowlist, size budget or author permission merely because a first trial succeeds. Changes to policy or workflows always require manual review and merge.

The post-merge next-rung handoff remains **read-only**. No future task is automatically executed unless another separately authorized feature is built and qualified.

## Qualification matrix

A successful field run requires a genuine auto-merge receipt and GitHub merger attribution. Negative tests must reject: non-owner label event, other author, fork, stale SHA, renamed/added/deleted file, non-allowlisted path, too-large diff, conflicting or hold label, pending or forged check, moved merge base, and a changed file patch between reads.

**Ledger Above Ego: a green CI check proves those checks passed, not that the code was independently reviewed.**
