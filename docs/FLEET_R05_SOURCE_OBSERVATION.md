# Fleet R0.5: independent, lease-fenced source observation

R0.5 performs **actual read-only GitHub API observations** against the public owner repository and default branch claimed by a PhiMada verification request. It is our first independently observed source-revision receipt. It is **not** independent build/test execution and is **not** product verification.

This rung builds on the already-merged R0.3 offline PhiMada intake and R0.4 local SQLite reservations. It consumes the R0.3 receipt and a current R0.4 lease capability for that *same* immutable repository ID, source commit and request digest.

## Operator workflow

Generate the R0.3 file and reserve the repo with the R0.4 CLI:

    python scripts/fleet_r03_acceptance_intake.py --input /path/to/phimada-verification-request-BTM.json --output-dir local-fleet-intake

    python scripts/fleet_r04_leases.py --db local-fleet/leases.db reserve --intake local-fleet-intake/verification-intake.json --worker desk-01 --ttl 300 --lease-file local-fleet/private/desk-01.json

Then run R0.5 from the **same host / shared filesystem** before the lease expires:

    python scripts/fleet_r05_source_observe.py --db local-fleet/leases.db --lease-file local-fleet/private/desk-01.json --intake local-fleet-intake/verification-intake.json --output local-fleet/observations/BTM-head.json

Supply a read-only \`GITHUB_TOKEN\` in the environment if GitHub rate limits require authentication. Only GET requests to the fixed \`https://api.github.com/repos/MichaelWave369/{repo}\` endpoints are made, with a bounded response, 15-second network timeout and redirects disabled. **Never pass secrets through any imported JSON.**

Output is exclusive-create JSON under your local directory. Successful invocation exit 0 means \`SOURCE_HEAD_MATCH_OBSERVED\`; exit 2 means a receipt was written with a source/identity mismatch hold; exit 1 means an invalid input, stale lease or network failure prevented the observation. Repeat with a new output filename; existing receipts are never overwritten.

Release the lease only when done inspecting:

    python scripts/fleet_r04_leases.py --db local-fleet/leases.db release --lease-file local-fleet/private/desk-01.json

## Source-identity verification

- Validate the intake and exact request/lease bindings. Verify the token, worker, lease generation and lease expiry *before* any remote API request.
- Fetch the public repository's immutable numeric ID, full owner/name, public visibility, non-archived state and default branch from GitHub. Reject transfer/rename/privatization/branch change.
- Fetch the exact named branch HEAD **twice** and compare both observations with the requested 40-character commit SHA. A mismatch or intervening push yields a held receipt, not a pass.
- Re-check the same local fencing capability *after* the final remote read. If it expired or was superseded during the read, refuse to write a source-match receipt.
- Report the identity observation, requested and first/last observed SHAs, request digest, lease generation, UTC observation time and explicit no-execution/no-merge flags. The secret lease capability is omitted.

The GitHub API observations establish identity and HEAD **at observation time**, not eternal stability. No cryptographic attestation by GitHub, immutable signed artifact, verified CI result, operator approval or autonomous merge capability is created.

## Safety and limitations

1. This cannot run tests, build packages, verify VR on hardware, certify product completion or dispatch workers. \`automated_tests_run=0\`, \`product_verified=false\`, \`merge_authorized=false\`.
2. The R0.4 SQLite lease protects participating processes on a **single shared filesystem** only. It is not a cross-runner distributed lock.
3. A successful source observation cannot authorize later code execution. Future workers must independently verify HEAD *again immediately before an approved action* and validate fresh fencing, scoped permissions and branch protection.
4. Local JSON input is not authenticated. Digest equality binds files together, but does not prove the operator's identity or intent.
5. This code never executes or checks out the observed repository, and never issues mutating GitHub API requests.
6. Raw observations and lease capabilities remain within ignored \`local-fleet/\` and \`local-fleet-intake/\` directories. Do not publish bearer lease files or embed tokens in receipts.

## CI

    python -m unittest discover -s server/tests -p test_fleet_r05_source_observe.py -v
    PYTHONPATH=server pytest -q server/tests/test_fleet_r05_source_observe.py

The 14 tests use a synthetic, injected GitHub GET client. They cover double-HEAD matching, intervening changes, wrong identity, private/archived repos, nested branch URL escaping, malicious branch input, stale or stolen leases, mid-flight expiry, non-clobbering receipt writes and zero execution authority.

## Next implementation milestone

R0.6: isolated, opt-in, bounded verification jobs that consume fresh source observations, re-fetch exact HEAD and present independent SHA-bound build/test receipts; manual/device checks remain explicitly unverified until separately performed. Only a later governed merge gate can use those receipts for PR decisions.
