# Fleet R13: first genuine cloud-hosted read-only mission worker

R13 moves beyond role proposals. It runs one deterministic, owner-confirmed
GitHub API metadata audit as a hosted worker, then launches a separate,
automated read-only QA evidence-verification workflow.

**No local install, SQLite, desktop terminal, token files, or running server.**

## First live mission

Existing Mission [#132](https://github.com/MichaelWave369/Agentora/issues/132)
has already been created, triaged, and given proposed worker role builder_a.
It requests a read-only audit of MichaelWave369/PhiMadaPrime.

After the PR is merged:

1. Open Agentora Actions and select
   [Fleet R13 Hosted Read-Only Mission Audit](https://github.com/MichaelWave369/Agentora/actions/workflows/fleet-r13-readonly-audit.yml).
2. Click Run workflow on main.
3. Enter Issue number 132.
4. For confirmation, type RUN_FLEET_R13_READ_ONLY_AUDIT.
5. Run the workflow and inspect Summary and the fleet-r13-audit-<run-id>
   artifact. A successful result means a real deterministic GitHub-hosted
   worker inspected the live public repository metadata, checked the head
   commit and recorded exact source identity. It is **not** an AI model
   creating new code or running tests.
6. A successful completed audit automatically starts
   [Fleet R13 Separate Audit Evidence QA](https://github.com/MichaelWave369/Agentora/actions/workflows/fleet-r13-independent-qa.yml).
   This workflow uses a separate verifier implementation on trusted main,
   downloads the actual GitHub ZIP, independently verifies the GitHub artifact
   SHA-256, revalidates Issue #132's journal and live repository metadata,
   and checks all audit receipt claims. A changed HEAD or stale/tampered
   receipt triggers HOLD.
7. The QA workflow records independent *automated evidence corroboration*.
   **Independent human QA is still pending.** No GitHub Issue or PR is marked
   approved and nothing is merged or deployed.

The QA workflow also supports manual Run workflow with an existing R13
audit GitHub Actions run ID, for review of recently completed runs.

## Supported mission and source

- Only an open, owner-created structured Fleet Mission Issue
- Mission kind must be Read-only audit
- R12 journal must be exactly ROLE_PROPOSED and the worker role builder_a
- Repository must be public, unarchived, enabled, owned by MichaelWave369
- Source identity (numeric repo ID, default branch and exact HEAD SHA)
  must be live and unchanged between pre/post checks
- Inspect public/active state, default-branch protection and HEAD commit
  identity/signature metadata, all as observations, not security clearance

## Permission boundaries

Both workflows receive **read-only** GitHub tokens.

- Audit workflow: contents:read and issues:read, triggered manually by the
  owner on main with an explicit confirmation. It only calls GitHub GET APIs.
  Target source code is not checked out or executed.
- Independent QA: contents:read, issues:read and actions:read; automatically
  triggered by a completed audit workflow or manually with a run ID. It
  rejects unexpected workflow path, actor, event, attempt, status, ZIP
  archive content, artifact digest, source/mission drift or unsupported claims.
- Original ZIP is downloaded using the existing R11 hardened signed storage
  redirect handling, with a separate unauthenticated HTTPS request. GitHub
  bearer credentials are not forwarded to storage.
- No writes to Issue comments, PRs, repositories, labels, branches, code,
  Actions dispatches or deployments. No self-approval.
- Artifacts expire after 7 days. A stale run or expired artifact is a HOLD.
- The R12 board remains a source of mission planning state. The R13 audit
  and QA evidence are available as separate GitHub Actions runs; R13 does
  **not** falsely mutate the R12 mission journal into QA_APPROVED.

## Evidence and status

Audit receipt state:
AUDIT_RECEIPT_CAPTURED_PENDING_SEPARATE_QA

Successful automated QA receipt state:
AUDIT_METADATA_CORROBORATED_PENDING_HUMAN_QA

No matter what, the outputs explicitly report
independent_qa_complete=false, verified_complete=false,
merge_authorized=false, deployment_authorized=false.

The worker is a small deterministic script with no LLM runtime. It is a
genuine cloud job, but should not be mistaken for a delegated self-directed
coding agent. That connection is a future, separately authorized rung.

CI contract:
PYTHONPATH=server python -m pytest -q server/tests/test_fleet_r13_hosted_audit_qa.py

Ledger Above Ego. People Above Profit.
