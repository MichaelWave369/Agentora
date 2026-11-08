# Fleet R9: persistent mission control and independent QA handoff

R9 introduces the first **multi-repository local mission queue** over the
merged RepoNerve R1, steward R2, fenced lease R3 and R0.4 infrastructure.

It is operational coordination, NOT general-purpose autonomous execution.
R9 issues real same-host ownership reservations, keeps a durable queue, limits
simultaneous assignments, hands implementer evidence to another QA worker,
and leaves disputed missions held until explicit reconciliation.

R9 does not start models, run shell commands, dispatch R5/R7 GitHub Actions,
write source files, publish PRs, merge branches, deploy, or assert completeness.
R8 is the separate optional explicitly authorized draft-PR publisher.

## Mission policies

The mission registry accepts only:
- PUBLIC_STANDALONE_READINESS_AUDIT: any currently visible, nonarchived
  public RepoNerve repository; **advisory review only**.
- PHIMADA_FIXED_TEST: the fixed public PhiMadaPrime GitHub ID used in R0.6.
- PHIMADA_MODEL_PROPOSAL_REVIEW: the same fixed public PhiMadaPrime ID.

These are *mission classifications*, not executable capabilities. The later
fixed test or model-proposal workflows still require their own exact-SHA,
operator and token policies and do not gain authority from an R9 assignment.
There is no generic repo write permission or arbitrary command payload.

A held R0.3 intake is checked for shape, source SHA, GitHub ID and request
digest. The current unarchived RepoNerve steward is checked as well.
Neither the intake nor the R1 scan proves the live remote GitHub HEAD.
Before any external effect, R0.5/R5/R7 must independently recheck it.

## Example local workflow

Prerequisite: collect public observations from PhiRepoNerve, ingest them in
the Agentora R2 steward DB, and prepare one held intake receipt per repo.

Queue an explicit public-only review mission:

    python scripts/fleet_r9_mission_control.py enqueue \
      --mission-id btm-readiness-001 \
      --kind PUBLIC_STANDALONE_READINESS_AUDIT \
      --intake ./btm-intake.json \
      --confirm ENQUEUE_PUBLIC_REVIEW_MISSION

Examine the bounded fair plan:

    python scripts/fleet_r9_mission_control.py plan

Claim the **next mission shown by the plan**, supplying the matching intake.
The CLI returns a no-execution receipt and writes a private R0.4 bearer
capability file. The lease is a real local reservation, not authorization
to run code or merge a PR.

    python scripts/fleet_r9_mission_control.py claim \
      --intake ./btm-intake.json \
      --worker implementer1 \
      --lease-file ~/.agentora/private/implementer1.lease

The operator may separately initiate the appropriate fixed runner under
its own source-revalidation and authorization policy. R9 does NOT dispatch
it. When ready for independent QA, record the **claimed**, not verified,
SHA-256 of a bounded external evidence artifact and release the
implementation lease:

    python scripts/fleet_r9_mission_control.py handoff \
      --mission-id btm-readiness-001 \
      --lease-file ~/.agentora/private/implementer1.lease \
      --evidence-sha256 <64_HEX_DIGEST>

This moves the mission to QA_QUEUED only after local lease release.
The digest is not an independently verified GitHub artifact receipt.

Separate QA worker, never the implementer:

    python scripts/fleet_r9_mission_control.py qa-plan

    python scripts/fleet_r9_mission_control.py qa-claim \
      --intake ./btm-intake.json \
      --worker independentQA \
      --lease-file ~/.agentora/private/independentQA.lease

QA can close its **local assignment** only as held for manual evidence
review, never as verified product completion:

    python scripts/fleet_r9_mission_control.py qa-hold \
      --mission-id btm-readiness-001 \
      --lease-file ~/.agentora/private/independentQA.lease

Inspect public-only, currently visible mission state:

    python scripts/fleet_r9_mission_control.py status

R9 keeps QA_HELD records blocked against new same-repository missions.
After resolving the evidence and confirming no live local lease exists,
an operator may archive the held record without approving work:

    python scripts/fleet_r9_mission_control.py archive-held \
      --mission-id btm-readiness-001 \
      --confirm ARCHIVE_HELD_WITHOUT_APPROVAL

It produces ARCHIVED_NOT_APPROVED. This permits a *new* explicitly enqueued
mission for the same repo while retaining the old history locally.
Expired or uncertain claims need independent reconciliation; a stale lease
is not evidence that remote workers or GitHub Actions have stopped.

## Fairness, bounds and trust barriers

The queue persists in the **same private SQLite file** as R0.4 leases,
default ~/.agentora/fleet-leases.sqlite3. Distinct persistent stewards remain
in ~/.agentora/fleet-stewards.sqlite3. The default capacity is two local
assignment slots and may be configured from 1 through 6.

- FIFO when priorities tie, with a history-based bias toward repositories
  with fewer previous assignment starts.
- Only presently public, unarchived stewards with exact matching GitHub IDs
  and names are eligible; stale source, renames or missing repos hold.
- One unresolved mission per repository. A mission ID is nonreusable.
- Slot caps count in-progress claims conservatively, not just completed ones.
- Actual R0.4 leases are issued with the existing private bearer token and
  generation fencing. Tokens are not printed or included in public status.
- Implementation must release before QA can acquire a separate fenced lease.
  The QA worker string must differ from the implementation worker.
- A process crash or lease contention leaves HELD_RECONCILE, never automatic
  retries, invisible workflow dispatch, fabricated QA success, or auto-merge.
- SQLite protects cooperating processes on one shared filesystem, not
  distributed runners. Registry and lease DBs are not one transaction; R3
  source double-check narrows but cannot remove that cross-DB race.

## R10 direction

Introduce authenticated, explicitly granted **mission execution
capabilities** mapped to fixed workflows with independent remote run
identifiers and evidence receipts; never rely on local SQLite alone to fence
remote GitHub Actions. QA should independently verify source, patch,
tests and policy at effect time. Only then should we consider safe
repeating rotations, optional repository-specific agents, or unattended
branch-only PR publication with separately controlled release decisions.
