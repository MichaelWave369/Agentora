# Agentora Fleet R2: persistent logical stewards and fair advisory rotation

**Status:** operator-driven local prototype. A "steward" is a durable SQLite
record keyed by an immutable GitHub repository ID, **not** an active AI worker.
No automatic execution, job dispatch, approval, PR creation, merge, deployment,
GitHub mutation, or production verification occurs in this rung.

## Prerequisite

Requires the already merged RepoNerve R1 public-observation bridge. Locally
scan GitHub via RepoNerve R1. Then export the redacted public-only R1 contract:

    python scripts/export_phireponerve_public.py --output ./fleet-public.json

Do not upload private RepoNerve SQLite state to GitHub Pages.

## Operator workflow

    python scripts/fleet_stewards_r2.py ingest --input ./fleet-public.json
    python scripts/fleet_stewards_r2.py snapshot --output ./stewards-public.json
    python scripts/fleet_stewards_r2.py rotation --request-id pilot-001 --count 3

Default database: ~/.agentora/fleet-stewards.sqlite3. The three commands
operate only on local SQLite. Rotation records an **advisory planning turn**
and returns a list of stable steward IDs, not execution-ready jobs.

A request ID is idempotent; rerunning an existing request returns the same
planning IDs without incrementing worker-turn counts. The rotation selects
eligible present/unarchived stewards with the fewest recent turns. A missing
repository remains in the local history as NOT PRESENT in current observation,
not deleted or verified-private. Its older name is never exported.

Snapshots contain only public names from the most recently ingested complete
scan. Strict shape and provenance checks reject unexpected private columns,
forged authority flags, duplicate IDs, stale inputs, and out-of-order scans.
Since the source is a redacted R1 export, it cannot enumerate private projects.

## Authority, trust and limits

The source merely observes repositories accessible to the scanner. It does
not prove all private repos were covered, any tests passed, an app is complete,
or a human authorized execution. The planning generation is a *local* SQLite
coordination mechanism, not a distributed runtime lock. Existing Agentora
R0.4 repository reservations remain the mechanism for tentative worker
ownership. Eventually, dispatch must independently obtain policy approval,
revalidate exact HEAD and verify resource leases before any effect.

No public HTTP endpoint is added in R2. The local export is a manual handoff
candidate for a separately validated PhiMadaPrime viewer; it must not be
published blindly or treated as an authorization document.

## Next rung

Join the local steward state to Agentora's existing source-pinned intake,
operator-approved execution queue and bounded worker registry. Add heartbeats,
crash recovery and independent test/release receipts before any unattended
merge policy is considered.
