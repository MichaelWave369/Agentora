# Fleet R8: independently reviewed R7 artifact to draft PR

**Current status:** local operator-controlled publisher. It does not run
automatically, does not invoke an AI model, and cannot approve, merge,
release or deploy. This rung does NOT give GitHub write authority to
the R7 model or its GitHub Actions test runner.

## Safety and provenance chain

1. A model's R7 public proposal is treated as untrusted.
2. R7's manual GitHub Actions workflow checks out PhiMadaPrime at an
   exact public source commit, applies the single-file change, and runs
   fixed tests/build with no GitHub source-write permission.
3. The operator downloads the resulting short-lived ZIP artifact.
4. The R8 local independent reviewer fetches the GitHub Actions run
   metadata and artifact digest directly from GitHub, and requires the
   fixed R7 workflow, trusted Agentora controller SHA, successful
   single-attempt run, fresh timestamp and exact artifact SHA-256.
5. R8 reads exactly six small archive members without extracting them;
   it refuses unknown paths, duplicates, symlinks, unsafe ZIP sizes and
   unsupported archive content.
6. R8 retrieves the real source file from the exact PhiMadaPrime commit
   through GitHub's contents API. It checks the Git blob identity, the
   R7 proposal's original SHA-256, all provenance and authority flags,
   the exact one-file replacement, the candidate and patch SHA-256, and
   the reported zero exit codes. Current source HEAD is independently
   checked before and after the audit.
7. R8 outputs a review-only receipt and a dry-run publication plan.
   **This is still not a security approval or release certification.**
8. Only a separately initiated, explicit operator approval can use a
   limited-scope token to create a branch containing the independently
   reconstructed file and then open a **draft** pull request.

The model's untrusted JSON never determines destination repo, branch,
merge permission, GitHub API endpoint or arbitrary file paths. The only
current target is public MichaelWave369/PhiMadaPrime, main,
src/reponerve.jsx. R8 is not yet a cross-repository system.

## Requirements

- Agentora contains R7 and R8 on a reviewed local branch.
- A **completed successful** workflow_dispatch run of
  Fleet R7 Public Model Proposal Candidate and its downloaded artifact ZIP.
  The R7 workflow has to have actually run; a merely green Agentora
  implementation PR is insufficient.
- GitHub run ID and exact trusted Agentora controller commit SHA.
  Independently review the fixed workflow at that SHA before trusting it.
- A reviewed patch: the operator must compare the patch and its SHA-256
  before approving branch publication.

Review and dry-run, with no write token required for public content:

    python scripts/fleet_r8_reviewed_pr_publisher.py \
      --run-id 123456789 \
      --artifact-zip ./fleet-r7-public-model-candidate.zip \
      --trusted-agentora-sha <REVIEWED_AGENTORA_WORKFLOW_SHA> \
      --request-id review-001

The dry-run fetches GitHub metadata, source and HEAD, checks the archive,
and prints the actual candidate patch hash, artifact digest, proposed
branch and no-authority fields. No local publication journal is written.

After independently reading the exact patch, supply a GitHub credential
with **Contents: write** and **Pull requests: write** for PhiMadaPrime
only. No Actions token or repository credential should be given to Ollama
or to the untrusted R7 sandbox.

Then deliberately publish ONE draft PR:

    python scripts/fleet_r8_reviewed_pr_publisher.py \
      --run-id 123456789 \
      --artifact-zip ./fleet-r7-public-model-candidate.zip \
      --trusted-agentora-sha <REVIEWED_AGENTORA_WORKFLOW_SHA> \
      --request-id review-001 \
      --reviewed-patch-sha256 <EXACT_R8_DRY_RUN_PATCH_SHA256> \
      --execute --confirm PUBLISH_REVIEWED_PHI_MADA_DRAFT_PR

The publisher creates a new uniquely derived review branch **from the
pinned source SHA**, writes only src/reponerve.jsx to it using GitHub's
Contents API with the original Git blob SHA, and creates a draft PR to
main. No auto-merge, PR approval, release or production deployment is
requested or performed.

## One-shot journal and unknown outcomes

The local private journal lives at
~/.agentora/fleet-r8-pr-publish.sqlite3 by default.

Before the first write the publisher reserves the requested run, branch
and request ID in an atomic SQLite transaction. A second attempt with
the same run or branch is refused. GitHub timeouts, unexpected responses
or partial failures **are not retried automatically**. The operator
must reconcile the real GitHub branch/PR and the private journal first.
A partially created branch is not silently removed, rewritten or merged.

The source HEAD is independently rechecked before branch creation,
before the Contents API write, and before opening the draft PR. If it
moves, the workflow holds. This narrows but does not eliminate
concurrency races between remote writes. A draft PR is not proof the
model's patch is secure or semantically correct.

## Current limitations and next rung

- R8 is manually initiated. It does not dispatch R7 model inference or
  automatically manage hundreds of repositories.
- R7 Actions workflow success plus digest agreement supports a bounded
  provenance claim, **not** a cryptographic runner attestation, independent
  test reproduction, threat-model approval, or full product verification.
- A caller-supplied trusted controller SHA must already have been reviewed;
  matching that SHA does not automatically establish trusted code.
- It is still separate from R3's local lease: GitHub cannot attest that a
  local SQLite fence was enforced when running R7.
- The new PR requires normal independent human code review, GitHub
  branch protections, relevant tests, and an explicit separate merge
  decision. Model self-review is not sufficient.
- Before automating R8 across PhiOS, PhiOS Web, PhiOS Mobile and PhiOS XR,
  introduce per-repository policy, protected-path classification,
  runner-to-mission attestation, independent QA, and action-time fencing.
