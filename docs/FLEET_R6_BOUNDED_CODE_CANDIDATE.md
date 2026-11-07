# Fleet R6: first bounded code-change candidate

**Status:** one manually initiated, fixed-scope patch-producing worker pilot.
It edits a disposable checkout, builds an inspectable patch, and runs fixed
automated tests/build in a network-disabled container. The runner has
no GitHub write scope. A merge, branch push or release **does not happen**.

This is NOT an autonomous LLM coding agent. The first R6 mission is a
reviewed deterministic repair so we can qualify the execution and evidence
boundaries *before* accepting generated coding proposals.

## Actual repair chosen

The current PhiMadaPrime RepoNerve reservations dashboard labels a value
"Reserved at display time", but it is computed when the user imports a
snapshot. R6 proposes the more accurate "Reserved when imported".

The fixed one-file replacement happens in PhiMadaPrime's
src/reponerve.jsx at a pinned public source SHA. R6 refuses if the
old text is missing, appears more than once, has already been fixed,
the checkout is dirty, or the repository HEAD is not the expected SHA.
Only a patch artifact is produced. No changes are pushed back to
PhiMadaPrime. The operator can independently review the patch and
choose whether to adopt it in a later PR.

## How to run the workflow

In the Agentora repository, select GitHub Actions,
"Fleet R6 Bounded PhiMada Code Candidate", and Run workflow.

Provide:
- source_sha: the current exact 40-character PhiMadaPrime main SHA
- confirmation: PROPOSE_PHI_MADA_COPY_FIX

No Actions-write token is passed into the tested repository. The workflow
runs with contents:read only and no GITHUB_TOKEN environment inside Docker.

The workflow performs these phases:

1. Trusted Agentora Python preflight independently verifies the public
   PhiMadaPrime identity and exact GitHub HEAD, twice.
2. GitHub Actions checks out that exact commit with credentials not
   persisted and no Git submodules or LFS.
3. R6 produces a single deterministic local source edit and immutable
   original/candidate/patch SHA-256 metadata. It checks the Git checkout SHA.
4. Dependencies are installed using npm --ignore-scripts.
5. Tests and build execute in ephemeral, non-root Docker containers with
   no network, no extra capabilities, a read-only source mount, CPU/memory
   bounds, process-count limits and no sensitive environment.
6. The trusted host finalizer checks patch hashes, exact scope, checkout
   integrity and current GitHub HEAD again, plus the fixed exit codes.
7. The patch, metadata, and test results are uploaded as a short-lived
   review-only GitHub Actions artifact. No branch or PR is created.

A successful R6 receipt is named
agentora.fleet.code-candidate-result.v0.6 and reports only
CANDIDATE_AUTOMATED_CHECKS_PASSED_AT_SHA. It does not claim manual browser
verification, a signed runner attestation, a release, or a merged PR.

## Connections and limits

R1-R5 supplies repository discovery, logical stewards, fair rotations,
local exclusive reservations, independent source observation, sandboxed
test execution and carefully gated workflow dispatch.

R6 is the **code-change candidate** half of that picture. It intentionally
does not reuse R5's limited dispatcher, which is pinned exclusively to the
existing R0.6 read-only test workflow. Adding R6 to R5's allowed mission
registry is a separate policy and lease-fencing change.

The R6 workflow itself is manually triggered and rechecks HEAD, but does
not require a local R3 lease; it cannot claim the remote GitHub runner was
fenced by a local SQLite reservation. The R6 proof is a bounded code edit
plus automated checks, NOT a fully autonomous agent or a review-approved
release.

## Next rung

Introduce a versioned agent-proposal JSON envelope, constrained edit scopes,
trusted local operator mission approval, immutable exact-SHA snapshots,
independent QA and a reviewed branch-only PR handoff. Only after verifying
the integrity and safety of that path should model-generated proposals be
accepted. GitHub contents or merge permissions remain separate from the
isolated worker runtime.
