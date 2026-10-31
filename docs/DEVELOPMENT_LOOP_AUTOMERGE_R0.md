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

The label must have been applied by MichaelWave369; the remote PR still must have that label. The workflow checks out trusted main, never the proposed PR head. Its GitHub token requests only contents read and pull-requests write. It never runs model-generated instructions, never grants a model merge permissions, and never exposes secrets to PR content.

This is intentionally only the first controlled pilot. Later rungs can add independent code review, risk classifications, repair queue integration, per-repo policies, and post-merge next-rung dispatch, each separately field qualified. Extending this implementation to general code merges without additional controls is not recommended.
