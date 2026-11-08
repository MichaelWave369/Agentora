# Fleet R10 · Existing R9 mission → guarded R5 fixed workflow

**Status:** implementation candidate. Not field-qualified until the workflow
is actually invoked with a current PhiMadaPrime source, GitHub returns an
accepted request, and a separately observed run/artifact correlates with it.

R10 adds **no new GitHub write endpoint** and **no agent-selected workflow**.
It delegates one operator-confirmed fixed PhiMadaPrime test submission to
the existing [R5 dispatcher](FLEET_R5_GUARDED_DISPATCH.md).

## Trust boundary

- One actual R9 mission must be assigned in the **implementation** phase.
- Mission **kind** must be exactly \`PHIMADA_FIXED_TEST\`; a RepoNerve
  first-observed / activity event admitted as
  \`PUBLIC_STANDALONE_READINESS_AUDIT\` **cannot** dispatch through this bridge.
- Exact public repository is pinned to the existing PhiMadaPrime numeric
  GitHub ID, default \`main\`, source SHA, request digest, worker and lease
  generation. The same local R0.4 fenced lease must still be active.
- GitHub workflow path and active status must match R5's existing
  \`fleet-r06-phimada-pilot.yml\`. R5 observes exact current GitHub HEAD and
  repository identity before dispatch and uses a one-shot POST journal.
- A dry-run uses GitHub **GET only** and requires no Actions-write token.
- A real dispatch requires the operator's distinct literal
  \`DISPATCH_R10_R9_FIXED_PHI_MADA_TEST\` confirmation plus an Actions-write
  credential scoped to Agentora; the existing R5 gate also confirms its fixed
  workflow internally. A queued mission/lease is **not** permission to run.
- No model output may supply arbitrary repo names, paths, commands, or workflow
  inputs; the bridge does not load a model and does not run any source code.

## Operator steps (trusted local machine)

After a fresh, valid public RepoNerve ingest and matching held R0.3 intake:

1. In R9, manually enqueue \`PHIMADA_FIXED_TEST\` for the exact PhiMadaPrime
   ID and SHA, and claim it using R9's \`claim\` command. This produces a
   private, worker-specific R0.4 lease capability file. Do **not** put that
   file in a git repository, PR description, issue, or chat.
2. Verify the R9 mission is \`ASSIGNED_IMPLEMENT\`, not an event-generated
   readiness-review mission.
3. Dry-run the bridge with its current intake and lease:

\`\`\`bash
python scripts/fleet_r10_r9_r5_bridge.py \
  --steward-db ~/.agentora/fleet-stewards.sqlite3 \
  --lease-db ~/.agentora/fleet-leases.sqlite3 \
  --mission-id phimada-fixed-001 \
  --intake ./phimada-verification-intake.json \
  --lease-file ~/.agentora/private/worker1.lease
\`\`\`

The illustrative mission ID must be replaced with the R9-assigned ID.
A successful preview emits \`DRY_RUN_READY_NO_DISPATCH\`. It performs
real GitHub read-only checks but never creates an R5 or R10 dispatch intent.

4. Only after reviewing the mission and the exact current source, and only
   with a purpose-scoped GitHub Actions-write token supplied by the operator,
   add \`--execute --confirm DISPATCH_R10_R9_FIXED_PHI_MADA_TEST\`.

\`\`\`bash
python scripts/fleet_r10_r9_r5_bridge.py \
  --steward-db ~/.agentora/fleet-stewards.sqlite3 \
  --lease-db ~/.agentora/fleet-leases.sqlite3 \
  --mission-id phimada-fixed-001 \
  --intake ./phimada-verification-intake.json \
  --lease-file ~/.agentora/private/worker1.lease \
  --execute --confirm DISPATCH_R10_R9_FIXED_PHI_MADA_TEST
\`\`\`

The token is read from \`GITHUB_TOKEN\`, never included in the receipt.

## What survives a crash

The bridge computes a deterministic, 47-character R5 request ID from the
R9 mission ID. Before executing R5's one-shot submission it stores a
\`r10_r5_dispatch_links\` row **in the existing R9/R0.4 SQLite file** with
mission ID, R5 request ID, source SHA, source intake digest, repository ID,
lease generation, and \`POST_OUTCOME_UNKNOWN\`. It revalidates the mission
inside that transaction. R5 independently records its own fixed-workflow
intent before POST, using the **same** ledger/transaction domain.

A later attempt using the same mission ID is rejected, regardless of
whether the first request returned success, failed locally or timed out.
This is intentionally conservative: an unknown POST may already have
created a GitHub run, and retrying could create duplicate external work.

\`REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED\` means GitHub's 204 response
acknowledged a workflow request. It does **not** include a run ID and must
not be represented as proof that a runner started, tests passed, or a release
completed. Unknown/rejected outcomes remain reviewable local records.
A future reconciliation lane must independently identify an actual remote
run, verify its workflow, source, attempt, completed jobs, artifact digest and
result. Do not match a run to a request by timestamp alone.

The R9 mission remains assigned after R5 submission until an explicit,
separately authenticated evidence and QA handoff. This bridge does not
advance mission state, forge independent QA, complete a project, or merge.

## Tests

\`\`\`bash
PYTHONPATH=server python -m pytest -q \
  server/tests/test_fleet_r10_r9_r5_bridge.py \
  server/tests/test_fleet_r9_mission_control.py \
  server/tests/test_fleet_r5_guarded_dispatch.py
\`\`\`

The new synthetic cases cover preview purity; correct R9/R5 journal linkage;
one real fixed POST; replay refusal; uncertain network results; wrong mission
kind, state, repository and source; forged lease; stale HEAD; absent owner
confirmation/token; and disabled workflow.

Synthetic success does not imply a hosted GitHub dispatch has occurred.

## What's next

Independently correlate an actual GitHub Actions run and its exact workflow,
source SHA, jobs, logs and artifacts; then record a bounded verification
receipt against the assigned mission. Only after that should Fleet R10
consider a separately reviewed path for owner-authorized coding tasks.
R0.4 local leases never become distributed GitHub runner locks.

**Ledger Above Ego. People Above Profit.**
