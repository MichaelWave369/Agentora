# Fleet R11 · GitHub-only evidence review (no local installation)

**For operators who build through GitHub PRs and GitHub Actions, not local
checkouts:** this workflow runs on an ephemeral GitHub-hosted Ubuntu runner.
It requires **no local Agentora install**, Python, SQLite, lease files,
Docker setup, developer machine, or terminal.

R11 is a safe alternative to the *local verification part* of Fleet R10.
It does **not** replace R10's private local ledger or claim that the local
mission queue has already coordinated a real remote team of agents.

## What is already available in GitHub

- [Fleet R0.6 PhiMada sandboxed pilot](../.github/workflows/fleet-r06-phimada-pilot.yml)
  is a fixed, manually triggered GitHub-hosted workflow. It accepts one
  exact public PhiMadaPrime main source SHA and the literal
  \`RUN_PHI_MADA_TESTS\` confirmation. It runs Node tests and Vite build
  in a network-disabled, non-privileged container.
- [Fleet R0.7 evidence review](../scripts/fleet_r07_evidence_review.py)
  verifies that a **real completed GitHub run** corresponds to the fixed
  workflow, repository, source SHA and unmodified artifact ZIP using GitHub
  SHA-256 metadata. Any historical untraced artifact remains *untraced*.

R11 puts that evidence reviewer onto GitHub's machines, so people do not
need to download ZIPs or install tools to see the result.

## How to use it in the browser

After this PR is merged into Agentora main:

1. Open **Agentora → Actions → Fleet R11 Cloud Evidence Review
   (No Local Setup)**.
2. Select **Run workflow** on \`main\`, enter the real existing PhiMada pilot
   **GitHub Actions run ID**, and launch the read-only review.
   For a legacy-example review, run \`41686772288\` was successful on
   November 3, 2026; its ZIP is scheduled to expire November 10, 2026.
   It predates R10 tracing and is **not** proof of a newer mission.
3. Open the run's **Summary** for an evidence verdict. The workflow retains
   a \`fleet-r11-cloud-review-<run_id>\` artifact with \`review.json\` and
   \`summary.md\`. No action is needed on your desktop.

For **new** manually launched R0.6 pilots, R11 also triggers automatically
on \`workflow_run: completed\`, using that actual GitHub run ID. A failed
or incomplete pilot creates an explicit **HELD** result, not a false pass.

The R0.6 workflow itself has a separate fixed-test confirmation; R11
**never triggers tests**. To run a fresh pilot, first use Agentora Actions
→ Fleet R0.6 PhiMada Sandboxed Verification Pilot → Run workflow, specify
the exact **current** PhiMadaPrime \`main\` SHA and required confirmation.
Do not reuse an old SHA without checking the current main branch.

## Trust boundaries

- R11 has GitHub Actions **read** and repository contents **read**
  permissions only, with no writable GitHub checkout credentials.
- The ZIP is downloaded via the GitHub API's signed artifact redirect.
  Its API token is used *only* at \`api.github.com\`; the signed storage
  URL is allowlisted HTTPS and receives a separate, **unauthenticated**
  request, so an OAuth bearer credential is never forwarded to blob storage.
- Archive size, structure, file names, SHA-256 and source/run integrity
  are bounded and checked by the existing R0.7 verifier. No ZIP member
  is extracted or executed. Incomplete/expired evidence fails closed.
- Every success report still includes:
  \`independent_qa_performed: false\`,
  \`product_verified: false\`,
  \`verified_complete: false\`,
  \`merge_authorized: false\`,
  \`dispatch_authorized: false\`.
- Traced R10 request IDs are included **as public metadata only**; they
  do not identify which human or bot submitted the run, and no local R9
  lease or QA state is inferred from them.
- A current GitHub workflow-run verdict is not deployment verification
  or full product qualification.

## Why this matters for the wider PhiOS ecosystem

The previous R9/R10 queue scripts were designed around a private
**local SQLite database and worker lease files**. They can be useful to
someone operating local agents, but they are not the right default for
a GitHub-first owner managing a large fleet of cloud-built repositories.

The next cloud-native architecture should use GitHub itself as the
source of truth: immutable workflow run IDs, reviewed Issues/PRs as task
records, retained evidence artifacts, scoped GitHub App credentials,
protected branches, independent QA, and narrow authorization gates.
A local database is optional infrastructure, **not a prerequisite** for
the owner. R11 is the first hosted evidence step, not that whole system.

## Verification

\`\`\`bash
PYTHONPATH=server python -m pytest -q \
  server/tests/test_fleet_r11_cloud_evidence.py \
  server/tests/test_fleet_r07_evidence_review.py
\`\`\`

The synthetic tests check legacy and traced artifacts, adversarial ZIP
digest and marker changes, incorrect workflow/run metadata, expired runs,
ambiguous/invalid artifacts, unsigned redirect host blocking, no token
forwarding, and the read-only GitHub Actions permission boundary.

**No live R11 workflow run has been executed until this change is merged
and GitHub Actions actually runs it.**

Ledger Above Ego. People Above Profit.
