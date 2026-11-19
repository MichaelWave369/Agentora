# Fleet R9 durable volume state (pre-deployment implementation)

Canonical mission: [Agentora #124](https://github.com/MichaelWave369/Agentora/issues/124).
This is **not yet a deployed cloud-persistent queue**. The first
GitHub-hosted read-only intake qualification passed on
[run 44634302918](https://github.com/MichaelWave369/Agentora/actions/runs/44634302918),
with `EPHEMERAL_ADMISSION_REPLAY_QUALIFIED`, one real public Agentora event
and one original R9 mission. Its databases were deleted with the job.

This patch supplies an opt-in, **POSIX-only volume state adapter** for that
*same* RepoNerve/R9 SQLite ledger. It does not add a replacement queue.

## Exact state preserved

A private mounted-volume directory holds:

- `reponerve.sqlite3`, the original RepoNerve scans, repositories, event
  IDs and scan lineage;
- `r9-stewards.sqlite3`, the original `StewardRegistry` source digest,
  steward identities and rotation;
- `r9-leases.sqlite3`, the original R0.4 lease ledger, R9 missions,
  `r10_event_links`, and R1 turn records.

The adapter checks file ownership, permissions, symlink avoidance, required
schema tables and SQLite integrity before accepting a restored state. It
serializes the **whole** scan + source-ingest + R9 transaction under a single
nonblocking POSIX `flock` lock. It creates a first seed in a staging directory,
then renames it to `active` only after all three databases pass verification.
A crashed first seed is retained and future boots HOLD. An existing active
state gets an `.r9-inflight-writer.json` guard before any scan; a crash,
partial write, or uncertain result leaves that guard and future boots HOLD
instead of silently resetting or replaying an unproven task.

An already recorded RepoNerve event is checked against the **original**
`events` table, `r10_event_links` and original R9 mission ID, repository,
source scan ID and event type. Its old source SHA/digest remains immutable
even after new Git commits and later public scans. It returns
`DURABLE_REPLAY_VERIFIED` only after a successful volume commit. A
conflicting history, corrupt DB, duplicate writer, or missing state holds.

## Explicit activation requirements

The normal GitHub-hosted public-intake workflow **does not** pass a state
directory and remains the same read-only ephemeral qualification as before.

A separately reviewed, volume-backed **single service instance** must
provide a real POSIX filesystem volume at a trustworthy mount, for example
`/data`. Opt-in requirements for the runner are:

- `AGENTORA_R9_DURABLE_ENABLED=true`
- `AGENTORA_R9_VOLUME_MOUNT=/data` (must be a real OS mount point)
- `--state-dir /data/agentora-r9` (must be inside the mount)
- Trusted source checkout verified against the expected original commit SHA
  and the numeric Agentora repo ID.

This is a software contract, **not instructions to deploy to a paid service
without owner approval**. Credentials remain only in runtime environment;
the same read-only public inventory URL guard is used. No API secrets,
unredacted private inventory, universal tokens, executable job payloads or
model-generated scripts belong in this volume.

## Qualification still required before production activation

1. Run adversarial tests for initial seed, process restart, real previous
   event binding, wrong scan provenance, corruption, lock collision and
   crash-marker replay.
2. Select a provider with a genuinely persistent private volume and data
   backup/recovery policy; configure **exactly one** writer. Do not equate
   a default GitHub Actions filesystem or artifact with durable storage.
3. Cold-boot the service with a clean mounted volume and one public scan;
   confirm one original R9 mission, with **no R1 execution authority**.
4. Restart/replace that process without losing its volume. Re-scan the
   same public RepoNerve source; verify the original event ID and mission
   are read back from the actual volume, never recreated.
5. Inject a terminated writer, corrupt file, and competing writer in a
   controlled staging environment. Confirm HOLDs and perform a documented
   recovery that re-verifies immutable GitHub evidence.
6. Only after those tests can scheduled cloud R9 intake and eventually
   bounded R9→existing R10/R1 dispatch be considered separately.

The script does **not** authorize owner approval, PR publishing, merging,
deployment, broad work generation, multi-repo operations or public issue
writes. Nothing in this PR changes GitHub branch protection, the hosted
R10 docs dispatcher or its owner-protected execution gate.
