# Operation ANCHOR R5 — local Agentora operator harness

Experimental opt-in integration, simulation only. No changes to existing
runtime startup, actions, API routers, UI, agent tools, approval endpoints,
MCP, databases or remote execution. The operator is a trusted local Python
caller; this is not an authenticated human identity or real consent service.

The reference harness imports ANC R1/R4 on demand. Reproduce with ANC at
merge commit 0174bec5e87ba97768727efc88c1f1efa68edfac (R4), using a separate
local checkout and its requirements-r4.txt. From Agentora root with ANC
checked out at ../ANC:

    python -m pip install -r ../ANC/requirements-r4.txt
    PYTHONPATH=server:../ANC python -P -m unittest discover -s tests -p test_anchor_operator_r5.py -v

Use Python 3.12 or 3.13. The -P safe-path option is required from the
repository root so the root app.py cannot shadow server/app. CI asserts
the import origins of both backend app and the pinned ANC package before
running the tests. On Windows PowerShell, set $env:PYTHONPATH to
'server;../ANC' and run the same python -P -m unittest command separately.

## Lifecycle

SyntheticOperator(path, initial_units=10) initializes a separate SQLite
file. Reopen without initial_units. Only simulation/sim:local/sim:credit
proposals accepted. propose() snapshots and validates the normalized R1
proposal, returning its digest. Reusing the request ID with different fields
fails closed. decide(digest, approve=True, now=...) is a trusted local
operator call and reserves exact integer credits atomically; deny is terminal.
cancel() releases reserved units once, even after expiry. No automatic
expiration/reconciliation; operators must cancel expired reservations.

simulate(digest, wire, trust=..., expected_issuer=..., now=...) requires an
approved unexpired proposal and R4 evidence for the fixed audience
agentora-anchor-simulation. Only safe/allow/zero-signal evidence is eligible
for simulated completion. Other signals require operator review outside
the harness. Replay claims use the same SQLite transaction as completion,
so errors roll back both. The adapter implements R4's claim protocol, not
its standalone ReplayStore class. Receipts are synthetic local summaries,
not signed settlement proofs. history() exposes digest, request ID, units,
state and evidence receipt; no actual transfer or provider credit occurs.
All results are non-authoritative.

## Limitations

One synthetic budget pool, no real wallet, chain, token, payee settlement,
quote verification, cryptographic operator approval or agent identity.
No key provisioning, distributed replay, protection from a compromised
local database/process, or remote caller authorization. Never wire this
harness directly into an agent tool or real signer. The existing Agentora
actions API is deliberately not reused because it can lead to execution.
No production security or MPay interoperability claim.

CI pins the ANC R4 source and runs cross-repo tests on Python 3.12 and 3.13.
Tests include no-approval denial, consent/denial/cancel, overspend and
substitution, rail rejection, tampering/risk rollback, expiry, concurrent
reservations and restart. Next: independent review and a separately
authenticated operator surface before any test-chain dispatch.
