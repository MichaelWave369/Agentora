# Fleet R10 · RepoNerve event → one durable Agentora R9 review mission

**Scope:** one operator-confirmed, local-only handoff using the **existing** R9
SQLite mission queue. This is **not** agent dispatch, credentialed GitHub
execution, an autonomous coding grant, a PR publisher, or permission to merge.

## Why

RepoNerve already provides bounded, public-only observation exports. Agentora's
steward registry already validates and stores their source scan/digest, and R9
already owns the persistent mission queue. Previously the operator had to
manually choose a mission ID and the event identity was not bound to a queue
record. This rung connects those existing pieces and rejects stale or
unrecognized observation bytes before creating one review mission.

## Prepare one real public observation

From the local RepoNerve CLI, export a **public-only** observation according to
its [Agentora R1 handoff contract](https://github.com/MichaelWave369/PhiRepoNerve).
Do not use private fleet inventory or publish local steward/lease databases.

Then, from your trusted local Agentora checkout, ingest that exact JSON:

```bash
python scripts/fleet_stewards_r2.py ingest --input ./public-observations.json
```

Choose an event ID from the `recent_events` array and have one existing held,
non-authorizing R0.3 `verification-intake.json` for **that exact public repo
identity**. The public observations do not carry a trusted GitHub HEAD; the
R0.3 intake SHA is an unverified claim until rechecked at a later action gate.

Queue a review, not execution:

```bash
python scripts/fleet_r9_mission_control.py enqueue-observed \
  --observations ./public-observations.json \
  --event-id 501 \
  --intake ./verification-intake.json \
  --confirm ENQUEUE_PUBLIC_REVIEW_MISSION

python scripts/fleet_r9_mission_control.py plan
python scripts/fleet_r9_mission_control.py status
```

Replace the illustrative `501` with a genuine current observation event ID.

Only `first_observed`, `visible_again` and
`push_activity_observed` are accepted for this first **readiness-review**
mission type; any other event is a HOLD pending a separately designed policy.
No event-generated text is executed. No model instructions are consumed.

## What is persisted

Inside the pre-existing private R9 lease/mission SQLite file:

- One `r9_missions` row, with deterministic
  `r10-e<EVENT_ID>-gh<GITHUB_ID>` mission ID, kind
  `PUBLIC_STANDALONE_READINESS_AUDIT` and policy
  `PUBLIC_REVIEW_ONLY_NEVER_EXECUTE`.
- A same-transaction `r10_event_links` row with unique source event ID,
  mission ID, public GitHub repository ID, RepoNerve scan ID, exact local
  observation payload digest and source event type.
- A repeat of the *same* event, source SHA, intake digest, public repo and
  mission kind returns `EVENT_ALREADY_QUEUED_NO_NEW_MISSION`.
  Conflicting replay returns `EVENT_REPLAY_CONFLICT`.

The bridge rejects a missing/incomplete/untrusted observation, a stale or
different locally ingested scan, repo ID/name mismatch, disallowed event type,
operator-confirmation omission, archived/missing steward, or a conflicting
existing R9 mission. The local source digest is a **consistency check**,
not GitHub/RepoNerve authentication. Data is read from ordinary operator-held
files, not automatically fetched from remote GitHub. A previous scan's event
cannot be replayed after the steward registry advances to a new scan.

The Registry and R9 mission DB live in separate SQLite files. An advancing
scan between validation and admission can still be a race; R9 rechecks the
current steward scan during enqueue. **No external effect is authorized** even
if local review admission succeeds.

## Verification

```bash
PYTHONPATH=server python -m unittest discover -s server/tests \
  -p 'test_fleet_r9_mission_control.py' -v
```

Added cases exercise a real persisted queue entry, idempotent repeat after
controller restart, altered observations, missing event IDs, wrong intake
identity, missing operator confirmation, scan drift, conflicting replay,
and false authority claims.

**Next R10 step (not part of this rung):** a separately reviewed, authenticated,
allowlisted job-dispatch capability with exact HEAD checks and independent GitHub
run receipts. R9's local lease is not a distributed GitHub runner lock. A
successful review mission does **not** approve PRs or prove release completion.

Ledger Above Ego. People Above Profit.
