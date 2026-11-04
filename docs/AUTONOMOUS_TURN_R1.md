# ΦMada Prime / Agentora: Autonomous Turn R1

Status: implementation candidate. A passing implementation PR is not a completed
autonomous turn. Hosted qualification requires an actual owner review, isolated
worker run, App-published PR, exact-SHA CI, trusted merge and independently read
GitHub merge record. No such run is claimed by this document.

## The bounded vertical slice

PhiMada's existing One-Repo Completion Lane gains an Agentora task panel. It reads
the public repository's numeric ID and current main SHA twice, prepares one
useful exact-edit task and opens a prefilled GitHub issue form. The operator
submits that request without copying source files. The issue is **untrusted
intake**, not approval. The existing R8/R0.3 export and receipt-return paths are
preserved; their unsigned local receipts do not gain execution authority.

The new workflow validates the event snapshot, freezes canonical task bytes and
prints a SHA-256 digest. Before any worker starts, GitHub pauses at the
`autonomous-turn-owner` environment. Its owner review must contain exactly
`APPROVE <task-sha256>`. The trusted stages independently GET GitHub's original
run and environment review history, verifying numeric owner ID `247459237`,
repository ID `1167870912`, main, workflow path, controller SHA, run ID, first run
attempt and the exact digest. An issue, comment, label, generated report or JSON
field cannot authorize itself. Rerunning an old run is refused; submit a new
request and review instead.

The worker uses **deterministic, preapproved literal edits**, not free-form model
generation. Every replacement binds the complete prior file's SHA-256 and one
unique old string. It validates paths, cumulative diff size and at most two
repair revisions. It has no publisher key, write token or merge credential.
No model execution, model reasoning, or external inference service is claimed;
there are no model API credentials or model charges in this slice. GitHub hosted
minutes/storage, npm/image downloads and App maintenance remain operational
costs. General model-written patches are outside R1's qualified scope.

Fixed tests run in nonroot, no-network, read-only-root Docker containers, with
dropped capabilities, no-new-privileges, memory/CPU/PID/time limits and a
read-only candidate mount. No token, socket, host control folder or publisher
secret is mounted. npm dependency resolution uses `--ignore-scripts` on the
credential-free worker host. Image tags remain mutable; this is process/container
isolation, not a reproducible-build or hostile-kernel security attestation.

A separate publisher receives only a JSON proposal and host-recorded sandbox
receipt. It checks their digest against trusted job outputs, repeats live owner
authorization/source checks, reconstructs the exact authorized edits and creates
a task-specific branch and actual PR. It preserves all other Git tree entries,
including file modes, and checks the complete resulting tree. The publisher App
is separate from the worker. GitHub's Contents/PR write permissions technically
also permit some merge actions; R1 keeps the App key exclusively in trusted
publisher code and never invokes a merge there. GitHub does not offer a general
"create PR but never merge" token permission. Do not describe this as an absolute
GitHub-enforced separation between publishing and merging.

The CI observer waits for all genuine `backend (3.12)`, `backend (3.13)` and `web`
check runs from `.github/workflows/ci.yml` on the exact current PR SHA. Both push
and PR runs must pass. A same-name check from another App/workflow, truncated
evidence, additional failed/security check, source drift, conflicting merge
label or hold causes refusal. For a failure it obtains bounded real job logs;
signed log redirects never receive the API bearer token. A repair must match a
single approved check/log signature in the original task and stay within its
original full diff budget. Unknown/multiple failures or exhausted repairs hold.
No commands, checks, tests, workflows or policies are rewritten to get green.

The separate merge gate re-reads authorization, complete PR identity/tree,
source, required CI, active rulesets and current GitHub mergeability. Docs reuse
the existing DevLoop docs path classification; code reuses its tiny UI file
classification and current-SHA independent write/admin collaborator review.
The existing owner-label docs/reviewed/solo policies are preserved unchanged.
The new task lane uses environment approval of **exact edits** instead of
applying an owner label on the owner's behalf. It does not broaden the solo
lane or impersonate an independent reviewer. GitHub can refuse the ordinary
SHA-pinned squash merge; there is no bypass flag.

After merging, it reads the actual PR, merge commit, parent and resulting blobs.
It writes a bounded result artifact and a GitHub-Actions check on the tested PR
SHA. PhiMada reads that public result and independently correlates the owner
review, trusted run/job, current PR SHA, actual CI workflow and merge record.
No browser credential or manual receipt copying is required. The result is a
live GitHub metadata correlation, not an independent full policy/security audit.

## One-time installation (owner action)

1. Review the infrastructure PRs, especially privileged workflow/API code. Merge
   them only after normal CI and human infrastructure review. These changes do
   not qualify for any existing automatic merge lane.
2. In Agentora Settings → Environments create **autonomous-turn-owner**. Set
   **only MichaelWave369** as required reviewer. Limit deployment branches to
   `main`, and disable administrator bypass. Leave "prevent self-review" off
   if you are both the requester and the sole reviewer. This is owner approval,
   not independent review. Keep the environment free of application secrets.
3. Create/install a GitHub App on **Agentora only**. Give it repository Contents
   write, Pull requests write, Actions read and Checks read (plus metadata read). Give it no
   administration, deployments write, workflow write, or branch-rule bypass.
   Store its numeric App ID as repository variable
   `AUTONOMOUS_PUBLISH_APP_ID` and its private key as repository Actions secret
   `AUTONOMOUS_PUBLISH_APP_KEY`. Do not paste the key into chat, a task or a PR.
   The installation token is short-lived and revoked by the token action.
   The normal Actions token cannot replace it: pushes/PRs made with that token
   do not trigger fresh ordinary CI events. A connector session is not a
   deployed credential available to a future workflow.
4. Preserve the active Agentora Safe Auto Merge ruleset and its three required
   checks. R1 does not create, disable or edit repository protections.

If environment metadata/review history is inaccessible, the publisher App is
missing, or GitHub refuses a write, the run remains HELD. Granting broad tokens,
fabricating an approval, applying an owner label through a bot, or manually
merging the field task is not a workaround for qualification.

## Approve and run one task

In PhiMada Mission Board → One Repo Finish Lane, choose **Agentora**, inspect its
current HEAD, then open **Autonomous Turn R1**. Prepare the documentation task.
It clarifies how source pushes invalidate code-review approval. Inspect the
scope and use **Submit this task request in GitHub**, then submit the prefilled
form. A GitHub Actions run appears under **Autonomous Turn R1**.

Open the run and inspect `autonomous-task-RUN_ID/task.json`. In **Review
deployments**, approve the environment using the exact comment shown in its
plan summary: `APPROVE <64-character task digest>`. This is the one scope
approval for that turn. Submission alone grants nothing. The default tasks
expire after four hours and authorize zero repair attempts; custom reviewed
tasks can authorize up to two signatures/edits, never an unrestricted repair.

The worker → publisher → observer → merge gate stages then run without manual
branch creation, file copying, PR creation or Merge clicks. Return to PhiMada,
refresh recent turn PRs and inspect the result. Its public GETs may be limited
by GitHub's unauthenticated rate limits; retry after the limit resets.

After the documentation turn is actually proven, prepare the small code task.
It changes `Link` to React Router `NavLink` in the existing Nav component so
assistive technology can identify the active page. Its `reviewed-code` policy
deliberately holds after green CI until an independent non-author collaborator
with write/admin permission approves the exact SHA. It cannot use the existing
owner-authored solo lane because an App-authored PR is not owner-authored.
If review is unavailable the PR remains open with a truthful checks-passed
receipt; the owner may use the normal human process. Do not claim automatic
code-merge qualification from that result.

For operator CLI preparation, from a clean approved checkout:

```bash
python3 scripts/autonomous_turn.py example --source . --kind docs --directory task-out
```

The alternative manual workflow input accepts the exact task JSON as data. No
arbitrary repository, shell command, model URL or credential input is accepted.

## Recovery and evidence

Artifacts are retained for 30 days: frozen task, original review correlation,
proposal/patch, host sandbox exits, published PR identity, CI observation/log
tails and final receipt or hold. Public check results and GitHub PR/run URLs
provide the return surface; artifact retention is not permanent signed storage.
Archive required evidence before expiration.

Branch names include task ID and run ID. Publisher retry reuses a matching
commit/branch/PR only after full tree revalidation; diverged branches hold.
Ref changes are non-forced and use the observed parent. A lost merge response
can be recovered by re-reading actual merge records, rather than merging a
second time. However full workflow reruns are deliberately ineligible because
an old owner review must not authorize another run attempt. Recovery requiring
a new execution needs a fresh task and approval; partially published branches
are retained for inspection. No source change is silently rebased.

The three visible outcomes are distinct:

| Outcome | Evidence | Product acceptance |
| --- | --- | --- |
| AUTOMATED CHECKS PASSED | Exact-SHA required CI, open PR if held | Still outstanding |
| MERGED | Above plus actual GitHub merge record, commit parent/blob readback | Still outstanding |
| PROJECT VERIFIED COMPLETE | Not granted by this implementation | Requires separate project contract/device/human acceptance |

## Requirement coverage and remaining limits

Controlling specification: operator-supplied **ΦMADA PRIME + AGENTORA — The First
Autonomous Development Turn**, supplied in this Work session. This milestone
implements its authorized single-task Agentora vertical slice. PaperGhost's
manually dispatched R0.8 pilot remains separate; at initial inspection PR #82
was OPEN at `f9b49e21164a59b26943e7d1003123b310ac9fa1`, not merged. R0.6–R0.8
verification-only pilots are preserved. No PaperGhost change or run is implied.

| Requirement | Implementation | Verification hook |
| --- | --- | --- |
| A: bounded genuine owner authorization | strict contract + original environment review GET | forged/digest/run/expiry negative tests |
| B: coding worker without write credentials | deterministic exact-edit worker + restricted Docker commands | real disposable checkout worker test; sandbox command/env tests |
| C: trusted publisher, real CI | App publisher + exact tree/PR/CI observer | synthetic API integration; real PR CI; hosted trial pending |
| D: ≤2 scoped repairs | immutable task signatures + genuine bounded CI logs | refusal and two-revision tests |
| E: separate merge gate | fresh auth/tree/check/rules/readback, existing code review policy | synthetic merge/hold/race tests; hosted merge pending |
| F: PhiMada outcome return | GitHub result check + independent public record correlation | JS positive/forged/stale record tests |

Implementation and local/synthetic verification do not prove the hosted loop.
Unqualified until observed: protected environment permissions and review UX,
App CI triggering, hosted Docker execution, repair from a real failing check,
actual trusted merge and live PhiMada return. No general model coder, cross-repo
publisher, unattended task selection, auto-deployment, durable signed ledger or
project-complete authority is introduced. Runtime permissions do not change
repository policy. A reviewed infrastructure deployment and genuine owner
approval are prerequisites, not simulated successes.

Ledger Above Ego. People Above Profit. Peace Above Drama.
