# Fleet R0.4: atomic local reservation leases

This is Agentora's first local concurrency primitive for fleet work: a SQLite reservation ledger with transactional claims, heartbeat renewals, expiry takeover and fencing generations. It is NOT a dispatcher, runner, authenticated approval service, distributed lock, GitHub authorization mechanism or auto-merge service.

R0.4 accepts the **held** verification-intake.json format specified in Fleet R0.3. It accepts only HELD_FOR_OPERATOR_REVIEW, NOT_RUN checks, and false approval, completion, source-revalidation and merge flags. Contents are still untrusted local claims: no authenticated identity or independently verified HEAD is established. Agentora PR #77 proposes the matching R0.3 intake CLI. R0.4 has no import-time dependency on that unmerged script.

## Local operator walkthrough

Use Python 3.12+ and a single shared local filesystem. Generate an R0.3 verification-intake file, then run these commands from the Agentora checkout.

    python scripts/fleet_r04_leases.py --db local-fleet/leases.db reserve --intake local-fleet-intake/verification-intake.json --worker desk-01 --ttl 300 --lease-file local-fleet/private/desk-01.json
    python scripts/fleet_r04_leases.py --db local-fleet/leases.db status
    python scripts/fleet_r04_leases.py --db local-fleet/leases.db renew --ttl 300 --lease-file local-fleet/private/desk-01.json
    python scripts/fleet_r04_leases.py --db local-fleet/leases.db release --lease-file local-fleet/private/desk-01.json

- Reserve takes an exclusive SQLite writer transaction. At most one unexpired reservation can exist for a repository name. Different repositories can be reserved independently; a single global fleet lease is never required.
- Renew extends only a current capability with the matching repository, ID, worker, generation, SHA, request digest and bearer token. Release requires the same and records RELEASED_NOT_COMPLETED, never software completion.
- An expired lease can be reclaimed with a new fencing generation and token. A stale previous holder cannot renew or release the new lease.
- Status shows safe metadata, not bearer secrets. Internal events record claims, renewals and releases. Database rows store only hashes of bearer tokens. The token resides in a local private file, written mode 0600 on POSIX and replaced atomically on renewal.
- Lease duration is bounded to 30–1800 seconds. Crashed processes eventually lose reservations, but nothing automatically retries, executes or marks work done.

## Critical limits

1. **One shared host/filesystem.** SQLite locking cannot coordinate independent GitHub Actions runners. A later authenticated remote service or atomic shared database is required for true distributed leases.
2. **Reservation is not authorization.** R0.4 never launches subprocesses, worker jobs, builds, PRs, deployments or merges. The R0.3 request digest correlates metadata but is not a signature. No operator approval or HEAD revalidation happens here.
3. **Fencing requires cooperation.** Future executing workers must validate the current fencing generation and exact source SHA immediately before actions, verify independent evidence and receive explicit scoped approval. The lease alone cannot stop another process from using GitHub directly.
4. **Protect local secrets.** Never commit, log or publish the private capability files or sync SQLite DB/WAL sidecars. The repo ignores local-fleet/ and local-fleet-intake/ as an extra safeguard, not a complete secrets policy.
5. **Source movement is not detected.** A reservation freezes the claimed SHA but never checks remote HEAD. New workflow code must independently revalidate that source.
6. **Never treat a released or expired lease as a successful product.** Completion verification and merge authorization are separate future gates.

## Verification

    python -m unittest discover -s server/tests -p test_fleet_r04_leases.py -v
    PYTHONPATH=server pytest -q server/tests/test_fleet_r04_leases.py

Tests cover eight competing workers for the same repository, independent projects, lease expiry and token fencing, heartbeat/release, forged authority claims, corrupt file handling, secret-file permissions and a complete CLI roundtrip. Agentora's normal CI suite automatically discovers the test file.

## Next rung

After R0.3 and R0.4 are merged, add a separate authenticated, scope-limited, isolated verification runner that independently fetches repo identity and exact HEAD. Its outputs must be independent evidence receipts. No automatic PR merge until additional branch-protection, review and change-authority gates are met.
