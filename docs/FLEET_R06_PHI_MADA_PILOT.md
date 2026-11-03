# Agentora Fleet R0.6: manually authorized PhiMada verification pilot

This rung adds the first **real bounded test/build execution path** in Agentora. It is a manual GitHub Actions pilot for the **single fixed repository** MichaelWave369/PhiMadaPrime. It does not automatically dispatch work from PhiMada, Agentora's R0.2 plan, or R0.4's local leases. It does not merge PRs or certify project completion.

The previous rungs remain in place:

- **R0.3:** PhiMada's contract intake, review-held, no work run.
- **R0.4:** single-host SQLite leases with generation fencing, no execution.
- **R0.5:** exact-SHA public source observations under a local lease, no tests.
- **R0.6:** independently triggered hosted pilot, exact SHA, fixed tests/build, restricted containers, postflight source check, bounded evidence receipt.

R0.6 uses GitHub Actions' fixed-group concurrency lock rather than pretending R0.4's local SQLite lease is distributed across hosted runners.

## Operating the first pilot

1. Open **Agentora → Actions → Fleet R0.6 PhiMada Sandboxed Verification Pilot → Run workflow** once this PR is merged.
2. In the PhiMada Prime repo, identify the **current exact main HEAD** (40 lowercase hex characters). Do not paste a branch label or a PR number.
3. Paste that SHA into **source_sha**.
4. Type the exact confirmation **RUN_PHI_MADA_TESTS** into **confirmation**. This manually authorizes one bounded CI run of that fixed public repository. No actions are scheduled.
5. Review the run log. The workflow first checks the repository's immutable GitHub ID, full owner/name, public/non-archived state and default branch, then independently reads HEAD twice and refuses mismatches.
6. Only after preflight succeeds does it check out the **exact SHA** with no persisted checkout credentials. Dependency resolution runs on the ephemeral host with npm lifecycle scripts disabled. Source-defined **npm test** and **npm run build** execute inside separate constrained Docker containers.
7. The finalizer checks GitHub HEAD twice again and writes **pilot-control/final.json** containing exact revision, fixed check IDs, exit codes, observed HEAD state, and explicit lack of product/merge authority. The workflow marks failed/held checks red. The artifact is retained for seven days.

## Restricted execution details

- Manual \`workflow_dispatch\` only. No schedule, PR trigger, push trigger, browser button or Agentora dispatch endpoint.
- One hardcoded repository with independently checked numeric GitHub repo ID: 1443845098. No arbitrary repo URL, branch, checkout path or shell command input.
- The GitHub job has \`permissions: contents: read\`, \`persist-credentials: false\`, no secret-bearing source checkout, and a fixed concurrency group. The token is passed only to preflight/postflight API reads.
- \`npm install --ignore-scripts\` resolves dependencies on the ephemeral host without running source lifecycle scripts. For this initial pilot, dependencies are **not fully pinned by a committed lockfile**; the receipt does not claim reproducible dependency inputs.
- Tests and build run as non-root (UID 1000) in ephemeral Node 22 Debian Bookworm slim containers with \`--network none\`, read-only rootfs, no additional capabilities, no-new-privileges, bounded CPU/memory/PIDs and five-minute execution timeouts. The source is mounted **read-only**, copied into an in-container tmpfs, and **no Docker socket, auth token, workspace parent or secrets** are mounted.
- Container-produced logs are not the source of truth for check exit codes. The trusted host shell records process exit status in \`pilot-control/steps.json\` outside the container. Only the host-side finalizer writes the final receipt.
- Current source HEAD is observed before and after the work. A new commit pushed during the run results in a **HELD_POSTFLIGHT_SOURCE_CHANGED** result, even if the tests passed for the older immutable commit.
- The container image tag is not an OCI digest pin; the receipt **does not** claim bit-for-bit reproducibility or a cryptographically signed attestation. A future rung should record a resolved image digest and dependency lock hash.

## What the evidence proves and what it doesn't

\`AUTOMATED_CHECKS_PASSED_AT_OBSERVED_SHA\` means the fixed Node test and Vite build commands both returned exit code zero against the explicitly checked out SHA, the host saw the correct checkout SHA, and GitHub HEAD matched that SHA before and after those checks.

It does **not** mean the deployed React site works, the browser UI passed a smoke test, all required completion-contract checks passed, a release was validated, human/device acceptance happened, or a PR may merge. Every receipt keeps \`product_verified=false\`, \`verified_complete=false\`, \`merge_authorized=false\`, and \`manual_checks=NOT_RUN\`.

All steps are observed at particular instants. Neither the result nor GitHub branch HEAD is permanently frozen.

## Validation

    python -m unittest discover -s server/tests -p test_fleet_r06_pilot.py -v
    PYTHONPATH=server pytest -q server/tests/test_fleet_r06_pilot.py

The 14 tests inject fake GitHub responses and verify: explicit confirmation, exact SHA validation, public repo identity, in-flight and postflight head changes, failing tests/build/install, malformed step records, forged authority flags, receipt secrecy, non-clobber output and manual-only workflow guards.

CI verifies the Python implementation and static workflow constraints. It **does not run a real R0.6 pilot** on every PR. Only the operator's future workflow_dispatch launch actually exercises the Docker execution path.

## Next rung

R0.7 can add a verified, immutable evidence intake into PhiMada Prime or Agentora's governed operator dashboard, requiring explicit human acceptance of which project-specific checks are needed. Only then consider expanding this opt-in runner to another reviewed project. Keep merge authorization separate and fail-closed.
