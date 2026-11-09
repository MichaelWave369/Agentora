# Fleet R12: GitHub-only mission board

GitHub Issues are mission work orders, GitHub Actions records owner-authorized
transitions, PR links identify proposed implementation, and R11 Actions runs
provide separately verifiable test evidence.

No installation, local SQLite, local Agentora server, or terminal is required.

## Browser-only setup

1. In Agentora, open Issues > New Issue > Phi Fleet Mission.
   Fill in one public MichaelWave369 repository, an allowlisted kind,
   desired outcome and acceptance criteria. Submit the Issue.
2. Open Fleet R12 Mission Command in Agentora Actions. Run on main using
   the TRIAGE action, the new Issue number, and the literal confirmation
   RECORD_FLEET_MISSION_TRANSITION.
3. Run PROPOSE_WORKER with the same Issue number, a role such as builder_a,
   and that confirmation. This records a proposed role but launches NOTHING.
4. Optional for PhiMadaPrime: LINK_EVIDENCE using a successful R11 cloud
   review run ID. This links a historical GitHub receipt, not proof that
   this mission caused the test or received QA approval.
5. Once there is a real open PR on the target repository default branch,
   run QUEUE_QA with the PR number and a different reviewer role, such as
   qa_independent. The result is QA_QUEUED_UNVERIFIED, never QA_APPROVED.
   The QA_HOLD command can park it without approval.
6. Open Fleet R12 Mission Board in Actions and manually Run workflow on
   main. The resulting Summary lists open mission Issues and recorded
   states. The JSON board snapshot is stored as a GitHub Actions artifact.

Direct browser links:
- New mission Issue: https://github.com/MichaelWave369/Agentora/issues/new/choose
- Mission Command: https://github.com/MichaelWave369/Agentora/actions/workflows/fleet-r12-mission-command.yml
- Mission Board: https://github.com/MichaelWave369/Agentora/actions/workflows/fleet-r12-mission-board.yml

## State machine

Command / Before / After

- triage / UNTRIAGED / TRIAGED
- propose_worker / TRIAGED / ROLE_PROPOSED
- link_evidence / ROLE_PROPOSED or QA_QUEUED_UNVERIFIED / unchanged
- queue_qa / ROLE_PROPOSED / QA_QUEUED_UNVERIFIED
- qa_hold / QA_QUEUED_UNVERIFIED / QA_HELD

Every journal receipt preserves worker_started=false,
independent_qa_complete=false, verified_complete=false,
merge_authorized=false and dispatch_authorized=false.

## Security and trust

- The Mission Command accepts only owner-triggered manual GitHub Actions
  dispatches on main with an explicit confirmation token.
- Only an owner-created open mission Issue can be transitioned.
- Target repository must be a public, active MichaelWave369 repo. The
  current default branch, live source SHA and numeric repository identity
  are read through GitHub API, not accepted from Issue text.
- Issue bodies are parsed strictly from the structured Issue form.
  Edited Issue bodies invalidate prior journal records through an exact
  SHA-256 body digest.
- Bounded sequential JSON journal events are stored in GitHub Actions bot
  Issue comments. Spoofed author, edited bot comment, duplicate transition,
  wrong Issue, invalid state, and source identity drift are held.
- Bot comments are GitHub-managed but not cryptographically signed.
  Other workflows with equivalent Issue-write permissions could mint
  lookalike comments. This is a guarded project coordination journal,
  not an append-only cryptographic ledger.
- Source code and untrusted Issue text never execute. This system cannot
  checkout a target project, call a model, dispatch a worker, approve a
  review, modify a PR, merge, deploy or publish.
- The read-only Mission Board uses contents:read and issues:read.
  The manual Command uses contents:read, issues:write,
  pull-requests:read and actions:read. No contents:write or PR write.
- A proposed role is not a real worker, and a linked PR is not a QA pass.
  A green R11 run is merely an evidence link, not an attributed mission
  verification. The existing R11 fixed PhiMada verification stays separate.
- The existing DevLoop R2.2/R2.3 PR review dashboard is reused, not replaced.
- The prior R9/R10 local DB is preserved for optional local deployments but
  is NOT required by the new GitHub-first owner workflow.

## First field qualification

Create ONE owner-authored mission Issue, run triage, then propose_worker,
then manually run the read-only board. Confirm that Issue comments
and board Summary agree. No agent runs or code writes occur.

The board reports at most 40 mission Issues across the first 200 open Issue
records; if the scan is incomplete it explicitly marks truncated=true.

CI command (runs on GitHub, not your PC):
PYTHONPATH=server python -m pytest -q server/tests/test_fleet_r12_github_missions.py

The next rung is real hosted worker claiming, isolated code branches,
exact-head PR CI receipts and independent QA. This initial release only
creates the governed coordination substrate.

People Above Profit. Ledger Above Ego.
