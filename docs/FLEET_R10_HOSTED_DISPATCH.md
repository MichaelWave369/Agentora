# Fleet R10: GitHub-hosted docs dispatch pilot (no local Agentora installation)

**Status: draft implementation; live hosted qualification required.**
Canonical project mission: [Agentora #124](https://github.com/MichaelWave369/Agentora/issues/124).

## Why this exists

The existing Agentora R9 SQLite watcher in `scripts/fleet_r10_r1.py`
needs a continuously running local process, RepoNerve service and
owner-scoped personal tokens. The user does **not** want to install any
local service. The GitHub-native pilot instead uses scheduled GitHub
Actions, an explicitly owner-authored public issue, and an immutable
GitHub issue-comment dispatch fence to hand one narrow task to the
**existing** `autonomous-turn-r1.yml` workflow.

**This is not yet the persistent multi-repo R9 mission engine.**
It is a bounded, GitHub-hosted transport qualification that will inform
a durable hosted R9 state adapter. Do not claim that this workflow
automatically generates tasks, uses a model, processes the fleet,
reconciles the full R9 ledger or independently certifies merges.

## Setup and operator actions (all inside GitHub)

1. Review the privileged workflow in this PR, its Python dispatcher and
   adversarial tests. Merge only after normal reviews and CI, without
   weakening existing branch protections or GitHub environment review.
2. Leave repository variable `AGENTORA_R10_HOSTED_ENABLED` absent or not
   equal to `true` for initial observation-only runs. The schedule
   stays **dry-run**, not live dispatch.
3. For a controlled R1 docs pilot, create a public issue in Agentora:
   - Author must be `MichaelWave369` (numeric user ID `247459237`).
   - Title begins exactly `Fleet R10 docs request:`
   - Body must contain **only** a current-source, valid R1 docs task
     JSON conforming to `agentora.autonomous-task.v1`.
   - Only one file under approved docs paths, policy `docs`,
     no repair attempts, fixed `docs-contract` test, exact main SHA,
     bounded immutable old/new text and a future expiration.
   - This submission is intent, *not approval*. The task must survive
     the existing R1 plan and owner-authorization gate independently.
   - Never paste credentials or private task data into a public issue.
4. From Agentora Actions, run
   **Fleet R10 Hosted Docs Dispatch (qualification pilot)** while the
   repository variable remains unset. Its successful dry-run may report
   `ELIGIBLE_NOT_DISPATCHED`; check that no new workflow ran or
   authorization appeared.
5. Only after review, set the repository Actions variable
   `AGENTORA_R10_HOSTED_ENABLED` to exactly `true`, or leave it
   disabled if you do not want scheduled task dispatch. This variable
   is a deliberate operational opt-in, not a token. The workflow uses
   GitHub's own `GITHUB_TOKEN`; it requests Actions write, Issue write
   and bounded read permissions in the trusted default-branch workflow.
6. On the next eligible schedule (30-minute interval, subject to GitHub
   delays), the dispatcher fetches owner-authored open tasks, validates
   the immutable R1 task contract and current source, checks original
   GitHub-bot comments for an existing fence, posts the one-shot
   `SUBMISSION_UNCERTAIN` fence, **then** submits the exact task JSON
   by `workflow_dispatch` to existing Autonomous R1.
7. Inspect the original R1 run's frozen task artifact. If its exact
   digest and scope are acceptable, approve in the protected
   `autonomous-turn-owner` environment. R1 independently runs its
   own worker, tests, publisher, observer and merge gate. The hosted
   dispatcher cannot perform the environment approval.
8. GitHub's 2026 dispatch API can return the exact new
   `workflow_run_id` and `html_url` when requested. The dispatcher
   checks that returned identity and reports it when available; a
   legacy 204 response remains `FENCED_DISPATCH_ACCEPTED_RUN_UNCONFIRMED`.
   In either case, independently verify the actual run's frozen task,
   the resulting PR, both push and PR CI events, actual merge SHA and
   result artifact. A successful dispatch response does NOT verify
   a run or merge. Reconciliation to the canonical R9 queue remains
   additional work.

To disable future dispatch, delete the variable or set it to
`false`. No Windows Task Scheduler, locally installed Agentora,
user PAT, or desktop process is required by this transport pilot.

## Failure and security boundaries

- A GitHub-bot fence is written **before** dispatch. If the write
  response, dispatch response or subsequent workflow is lost, the
  dispatcher **never retries that issue**. An operator must inspect
  the original GitHub runs and receipts to resolve the uncertainty.
- Truncated issue or comment pages HOLD rather than silently ignoring
  a potential prior dispatch. At most one unfenced eligible task
  is submitted per scheduled run.
- A forged comment by a non-bot author is not an authentic fence.
  Manual deletion of the real bot fence or repository-admin
  intervention invalidates its protection and requires independent
  review; GitHub issue comments are not an immutable signed ledger.
- Expired, changed-source, malformed, private or unauthorized tasks
  cannot dispatch. The source, accepted task bytes, rules and
  protected review are checked again by Autonomous R1.
- R1's existing GitHub run-identity code originally accepted only
  owner-triggered runs. The pilot separately recognizes the fixed
  `github-actions[bot]` numeric identity **only** for a new,
  first-attempt `workflow_dispatch` against trusted `main`.
  A bot-authored issue, mixed actor, replayed run or wrong workflow is
  rejected. This does **not** make the bot an owner or approve any task:
  the protected environment still requires the real owner to submit
  `APPROVE <task-sha256>`, independently checked by the trusted
  publisher and merge gate.
- `GITHUB_TOKEN` writes do not ordinarily trigger new workflows,
  but GitHub documents an exception for explicit
  `workflow_dispatch` and `repository_dispatch` calls. This pilot
  uses only the former against the one fixed R1 workflow.
- Scheduled workflows require a default-branch YAML, may be delayed or
  disabled by GitHub, and cannot be equated with always-on hosted agents.
  The script itself uses no external model or arbitrary task execution.

## Exact acceptance and next step

1. PR CI passes on exact head.
2. Owner reviews and merges the privileged workflow.
3. Dry-run discovers a real valid task with no write.
4. With explicit repository opt-in, one scheduled event writes a bot
   fence **before** the workflow dispatch, and no replay can repeat it.
5. The original R1 run receives real owner approval and merges or
   produces an independently verified HOLD.
6. Only then build the **durable hosted R9 ledger adapter** against
   the *existing* R9 mission schema and semantics. This is necessary
   for multi-repo scheduling and continuing from RepoNerve inventory
   without creating a parallel orchestrator.

## Documentation

GitHub's current GITHUB_TOKEN exception for workflow_dispatch:
https://docs.github.com/en/actions/concepts/security/github_token

GitHub schedule behavior:
https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
