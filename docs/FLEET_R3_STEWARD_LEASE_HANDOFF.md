# Agentora R3: steward-qualified local worker reservations

The R3 claim command connects R2 persistent logical steward identities to the
existing R0.4 local SQLite lease service. This is actual exclusive *reservation*
state, but it is NOT AI execution, independent HEAD verification, a release,
GitHub write authorization, or unattended merge capability.

## Operator workflow

First use RepoNerve R1 to scan locally and Agentora R1 to export the redacted
public observations. Ingest them into the R2 steward registry. Create a
held R0.3 verification-intake receipt for a chosen public repository and
specific source SHA.

The R3 explicit operator commands are:

    python scripts/fleet_r3_steward_claim.py claim --intake ./verification-intake.json --worker worker1 --lease-file ~/.agentora/private/worker1.lease
    python scripts/fleet_r3_steward_claim.py status
    python scripts/fleet_r3_steward_claim.py renew --lease-file ~/.agentora/private/worker1.lease
    python scripts/fleet_r3_steward_claim.py release --lease-file ~/.agentora/private/worker1.lease

Defaults are separate local SQLite files at:
- ~/.agentora/fleet-stewards.sqlite3
- ~/.agentora/fleet-leases.sqlite3

The claim requires matching immutable GitHub ID and canonical repo name, a
current source scan, and an unarchived, visible logical steward. The existing
R0.4 lease engine enforces expiry, exclusive same-repo ownership, renewal,
release and generation fencing. A private capability token stays only in
the operator-controlled lease file, never the printed result or local status.

The status output is limited to presently public and unarchived repo identities
and does not include token, request hashes, or previous private/hidden names.

## Boundaries

- Local-only CLI. No new browser or network API, startup daemon, GitHub
  mutation, worker execution, auto-merge, or public publication.
- Two separate SQLite databases are not one distributed transaction. A second
  identity read after reserving narrows the race, but future real executors
  must revalidate source HEAD, policy authority, and current fencing token
  immediately before any effect.
- R0.3 verification-intake does not independently authenticate its sender or
  prove the current HEAD; the claimed source SHA is merely input metadata.
- A lease expiration does not necessarily stop a rogue/stuck worker. Actual
  code execution needs its own sandbox and effect-time fencing checks.
- Archived or missing RepoNerve identity prevents new claims/renewals, but
  always permit safe release of a previously issued capability to avoid
  holding a lease unnecessarily.
- RepoNerve and this R3 prototype operate on public-only exports. A private
  fleet requires a separate authenticated operator-only channel.

## Next rung

Implement a narrow, operator-approved, sandboxed, source-SHA-verified worker
for fixed low-risk tests. It must bind the worker capability to the lease
generation and supply independent evidence before release or merge consideration.
