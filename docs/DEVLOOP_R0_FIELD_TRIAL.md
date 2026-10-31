# Φ Development Loop R0: Online field qualification

This is a harmless documentation-only change to verify Agentora's GitHub-native,
owner-authorized auto-merge pilot. The PR that adds this file is not a request
for a model to review code, grant itself permissions, or dispatch another rung.

## Test procedure

1. Confirm the repository's **Agentora Safe Auto Merge** branch ruleset is active
   and requires `backend (3.12)`, `backend (3.13)`, and `web` on `main`.
2. Inspect the proposed documentation-only PR and its current head SHA.
3. Confirm the exact `phi-automerge` label exists in repository settings.
4. As repository owner, apply that label to this PR.
5. Observe the GitHub Actions workflow named
   **Phi Development Loop - governed auto-merge pilot**.
6. Confirm the workflow requests native auto-merge for the current head SHA
   without checking out PR code or bypassing branch protection.
7. Confirm GitHub merges only after all required checks have passed.
8. Record the merge result and workflow run URL before widening the pilot.

## Expected outcome

A completed test establishes only that this narrow, documentation-only,
owner-authorized auto-merge path worked on this exact PR. It is not evidence
that automatic code review, generalized auto-merging, model relays, or
next-rung dispatch are production-ready.

If the workflow fails or auto-merge does not engage, leave the PR open.
Review the action log and ruleset configuration rather than force-merging
the candidate simply to declare the trial successful.
