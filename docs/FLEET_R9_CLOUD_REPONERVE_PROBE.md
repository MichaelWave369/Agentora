# Fleet R9: cloud public RepoNerve event intake qualification

Canonical mission: [Agentora #124](https://github.com/MichaelWave369/Agentora/issues/124).
This is the **first hosted observation/admission slice**, not the production
cloud-persistent R9 scheduler. R9 continues to own the mission queue.

## What runs in the cloud

[`fleet-r9-cloud-reponerve-probe.yml`](../.github/workflows/fleet-r9-cloud-reponerve-probe.yml)
is a manually dispatched, **contents-read-only**, serialized GitHub Actions
workflow. It checks out Agentora's protected `main` and a pinned reviewable
public PhiRepoNerve revision, `a625e8ac34831420ab52f2372bf4ec9079258c4a`.

1. The real RepoNerve scanner uses GitHub's **public owner inventory**
   endpoint, `GET /users/MichaelWave369/repos`. The original anonymous scan
   was blocked in a hosted runner (the first log hid the HTTP error). The
   scoped contents-read GitHub Actions token now authenticates **only this
   fixed public endpoint**, through a destination- and query-validating opener.
   RepoNerve itself is still constructed with `token=""`, preserving its
   public inventory selection and refusing the private `/user/repos` route.
   The authorization header is nonredirectable; credentials are neither
   printed nor included in result artifacts. Public inventory is collected
   in a temporary local RepoNerve SQLite snapshot.
2. Agentora's existing `collect_public_observations` validates the complete
   public inventory plus bounded, paginated events from RepoNerve's existing
   read-only local data interface. The Python adapter accepts only the fixed
   `/api/summary`, `/api/repos`, and `/api/events` read routes, without an
   HTTP server, browser-accessible endpoint, or arbitrary path.
3. Only a currently visible, unarchived public **Agentora** RepoNerve event
   of an already allowlisted R9 event kind can enter the test lane. The source
   SHA is the trusted workflow's `main` checkout SHA, never a fabricated
   current HEAD claim. Repo identity is fixed to GitHub ID `1167870912`.
4. The **existing R2 StewardRegistry, R0.4 LeaseLedger and R9 MissionControl**
   ingest the observation and call `enqueue_observed`. A same-run replay
   must return `EVENT_ALREADY_QUEUED_NO_NEW_MISSION`. Independent SQL reads
   verify exactly one R9 mission and one `r10_event_links` row, with policy
   `PUBLIC_STANDALONE_READINESS_AUDIT`, no worker execution or GitHub writes.
5. The temporary RepoNerve and Agentora SQLite databases are **deleted** as
   the job exits. Only a non-sensitive summary is printed to Actions logs.

If the complete public scan finds no matching event in its bounded history,
the workflow reports `NO_ELIGIBLE_AGENTORA_EVENT` without inventing a task.
If the GitHub public API, current source, pinned RepoNerve revision, inventory,
source identity, or R9 admission is ambiguous, it fails closed.

## Deliberate limitations

- **No cross-run persistence.** A replay inside one ephemeral runner only
  qualifies existing R9 transaction/idempotence logic. It is NOT a persistent
  hosted ledger or production queue. This job does not schedule itself.
- **No RepoNerve distributed state.** A fresh scan with a fresh SQLite file
  may produce the same `first_observed` event IDs on a later run. Its event
  IDs must not be used across runs without an actual persisted RepoNerve
  observation lineage and R9 ledger.
- **No effect privileges.** No Actions write, issues write, PR permissions,
  owner approvals, worker dispatch, merge or deployment. The held intake
  explicitly denies execution and head revalidation.
- GitHub's public inventory API can still rate-limit or fail authenticated
  requests. The diagnostic reports only an allowlisted HTTP status category
  or a transport HOLD, never API response bodies or token material. No
  fallback to private enumeration, skipped pages or silent retries.

## Next engineering step

Give the **existing R9 SQLite lease/steward tables** and RepoNerve public
observation ledger durable, encrypted cloud storage, serialized writes and
optimistic conflict detection before enabling automatic scheduled admission.
Never check raw SQLite databases into the public repository, and never expose
owner credentials or worker token digests in a public artifact. Recover
snapshot state on a new hosted runner, ingest one real *new* RepoNerve event,
replay it after restart, and confirm one durable mission with no duplicate
dispatch. Only then connect admitted tasks to the already qualified bounded
R10/R1 owner-approval and merge lane.
