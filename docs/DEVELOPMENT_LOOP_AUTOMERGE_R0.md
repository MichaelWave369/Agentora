# Phi Development Loop R0: governed GitHub-native auto-merge

Status: opt-in candidate, not yet field qualified. This rung does not build code or select a new development rung. It needs no local runtime, external AI host, or relay.

## Operator setup

1. Agentora Settings -> General -> Pull Requests -> Allow auto-merge must be enabled.
2. Agentora Settings -> Rules -> Rulesets: create an ENFORCED branch ruleset targeting the default main branch. Require ALL of the following named GitHub CI checks:
   * backend (3.12)
   * backend (3.13)
   * web
3. Check that these names exactly match actual GitHub check contexts before saving. Agentora's historical protec ruleset was disabled and only covered deletion/force-push. That is NOT an adequate merge gate.
4. Create the GitHub label phi-automerge. Do not have a bot apply it.
5. Review and merge this implementation PR manually, after its normal CI completes and the privileged workflow code is inspected.

## R0 usage

Open a same-repository, non-draft PR to main with between one and ten changed files. Only added/modified root README.md or Markdown files under docs/ qualify. Code, workflows, manifests, deletions, renames, and forks do not qualify.

After reviewing the diff, as the repository owner, apply the phi-automerge label to the PR. This is the single deliberate authorization for that exact PR head SHA. The trusted-base GitHub Actions job:
- re-fetches the current PR and rejects a moved head;
- rejects held PRs or missing labels;
- checks for an active, main-targeting required-status-checks ruleset with all three named CI contexts;
- checks the complete small diff against the docs-only allowlist;
- requests GitHub native auto-merge with an exact expected head SHA, using squash mode.

GitHub may merge immediately if all requirements are already met, or wait for them. The workflow does not override required checks or administrator policies.

On a later head push, draft conversion or removal of the label, another workflow run attempts to revoke pending native auto-merge. Because webhook events are asynchronous, this is an additional guard, not an absolute guarantee against a race. Reapply the label explicitly for a changed head only after re-reviewing the diff.

## Required qualification

First test a harmless documentation-only PR and preserve the PR and Actions run URLs. Check both positive and negative paths: no ruleset, missing CI context, stale SHA, fork, draft, blocked label, non-doc diff, and head-update revocation. Do not treat a green unit-test run as evidence that the privileged GraphQL API mutation worked in production.

## Scope and constraints

The label must have been applied by MichaelWave369; the remote PR still must have that label. The workflow checks out trusted main, never the proposed PR head. Its trusted-base GitHub Actions token requests `contents: write` and `pull-requests: write`, because GitHub's repository metadata API **omits** `allow_auto_merge` without contents write access. This is broader privilege than R0 originally requested. The workflow does not check out a PR head, run PR-provided code, perform source writes, or attempt to bypass branch rules. If merge settings are unavailable, the gate reports a distinct missing-permission error rather than claiming the setting is disabled. It never runs model-generated instructions, never grants a model merge permissions, and never exposes secrets to PR content. **R0.2 adds an explicit REST exact-head merge fallback only when GitHub GraphQL reports that native auto-merge was rejected because the PR is already in clean status**. This fallback independently reads the exact head SHA's complete, GitHub-Actions-sourced required checks; rechecks the active branch ruleset; re-fetches and revalidates the live PR, label, SHA and docs-only diff; and then submits a squash merge with `sha` pinned. GitHub still enforces its branch policies and may refuse the merge.

This is intentionally only the first controlled pilot. Later rungs can add independent code review, risk classifications, repair queue integration, per-repo policies, and post-merge next-rung dispatch, each separately field qualified. Extending this implementation to general code merges without additional controls is not recommended.

## R0 field trial diagnosis: token-visible merge settings

The first owner-labeled documentation trial was held with `NATIVE_AUTO_MERGE_DISABLED` despite repository-level auto-merge being enabled. GitHub only exposes merge settings in its REST repository object when the calling token holds **both contents read and write**. The original workflow used `contents: read` plus `pull-requests: write`; the absence of `allow_auto_merge` was misclassified as a disabled setting. The corrective PR gives this one trusted-base workflow `contents: write`, adds a regression test for missing fields, and reports `AUTO_MERGE_SETTING_HIDDEN_CHECK_TOKEN_CONTENTS_WRITE` for missing data.

After merging the corrective PR manually, **remove and re-apply** the `phi-automerge` label on the still-open documentation test PR as repository owner. This generates a new labeled event with the corrected trusted-main implementation. Do **not** bypass or manually merge the test PR merely because its earlier gate failed.

A second real trial is still required. If the next run fails at the GraphQL mutation, retain the fail-closed behavior and inspect only sanitized diagnostics rather than broadening privileges again without evidence.

## R0.2: second field-trial diagnosis and clean-status fallback

The owner reapplied `phi-automerge` to trial PR #52 after merging the R0.1 token-permission fix. The live [govern run 41239409972](https://github.com/MichaelWave369/Agentora/actions/runs/41239409972) then passed the repository policy checks but failed at `GRAPHQL_MUTATION_REJECTED`. Because R0.1 suppressed the actual GraphQL error, **the precise cause of that run is unknown**. All three required CI contexts on the test head were already green by then. GitHub documents that native auto-merge is intended for PRs still blocked by merge requirements and can reject already-clean PRs.

R0.2 introduces **bounded, non-secret diagnostic codes**: `AUTO_MERGE_ALREADY_CLEAN`, `GRAPHQL_TOKEN_ACCESS_REJECTED`, and `GRAPHQL_REJECTED_OTHER`. Only an exact sole GraphQL clean-status error activates the direct REST merge fallback. Any authorization or unknown error remains a HOLD. The fallback obtains extra `checks: read` permission but never checks out PR-head source, executes untrusted code, passes an admin-bypass flag or overrides protections.

For the next real trial, after manually merging the R0.2 workflow PR with green CI and reviewing its privileged change, remove and re-add `phi-automerge` on still-open PR #52. Observe the latest Action run. If that run reports `GRAPHQL_TOKEN_ACCESS_REJECTED`, investigate repository Actions permissions rather than weakening the gate or injecting a broad PAT without separate operator review.
