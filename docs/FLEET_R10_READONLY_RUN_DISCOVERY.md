# Fleet R10 · find GitHub pilot run candidates without false attribution

**Read-only, bounded observation. Not dispatch, run verification, independent QA,
merge approval, or product completion.**

An existing R9 → R5 fixed test workflow submission records two one-shot local
journal entries and returns HTTP 204 on acceptance, **without a GitHub run ID**.
PR #127 added an inert mission request marker inside the R0.6 artifact; PR #128
added exact artifact/run correlation and optional separate QA handoff.

This stage makes **discovering a possible run ID** less manual. It does not
skip the trusted artifact and lease checks required by R0.7, R4 and R10.

## Use

From a trusted local Agentora checkout whose private R9/lease SQLite database
already contains the **same accepted mission and dispatch request**:

\`\`\`bash
python scripts/fleet_r10_run_discovery.py \
  --lease-db ~/.agentora/fleet-leases.sqlite3 \
  --mission-id phimada-fixed-001 \
  --max-pages 2
\`\`\`

\`GITHUB_TOKEN\` is optional for public read-only API requests. If supplied,
it only needs read access. **Never supply your R0.4 bearer lease file or
GitHub Actions write credentials to this command.** No workflow dispatch or
repository mutation happens.

The CLI refuses work unless:
- R9 mission kind is exactly \`PHIMADA_FIXED_TEST\`, for the fixed public
  \`MichaelWave369/PhiMadaPrime\` numeric GitHub ID.
- Its immutable source SHA, intake digest, worker and lease generation match
  the two **already-accepted R10 and R5** one-shot dispatch journal entries.
- Both local journals are present and agree on the same deterministic
  request ID. Unknown or rejected submissions cannot be treated as accepted.
- The local dispatch intent falls within the existing R0.7's eight-day
  maximal review horizon (the hosted pilot ZIP normally expires after seven
  days). This discovery only requires a historical journal, not a currently
  active worker lease; R4/R10 correlation still requires a current lease.

GitHub reads are bounded to a maximum of three pages of 100
\`workflow_dispatch\` runs in **Agentora**, and to the fixed
\`fleet-r06-phimada-<run ID>\` artifact metadata of plausible
completed successful runs. The default is two pages, maximum twenty returned
candidates. It rejects unexpected repository identity, invalid IDs, malformed
timestamps, ambiguous matching artifacts, missing SHA-256 metadata and
out-of-budget inputs.

Each candidate displays its GitHub run ID, status, conclusion, source
**Agentora workflow commit SHA**, and (if present) the claimed archive
artifact ID, SHA-256 and size. **The Agentora workflow HEAD is *not* the
PhiMadaPrime source SHA.** No code infers that source SHA from GitHub run list
metadata.

## How to interpret the response

- \`CANDIDATE_NOT_CORRELATED_NEEDS_ZIP_AND_R07\`:
  GitHub reports a successful fixed workflow run with an appropriately named
  artifact and digest. The artifact bytes and mission marker have **not**
  been downloaded or independently verified, so there is no attribution.
- \`RUN_NOT_SUCCESSFULLY_COMPLETED\`:
  A queued, running, failed or otherwise incomplete fixed run. This is not
  test success.
- \`SUCCESSFUL_RUN_BUT_NO_PILOT_ARTIFACT\`:
  A green workflow with missing expected evidence. This is **not** a passed
  mission.
- \`NO_CANDIDATE_IN_SCANNED_WINDOW\`:
  No match within the checked pages/horizon. It is **not** proof a run
  never existed. Read \`truncated\`, \`searched_pages\`, and
  \`scanned_run_records\`.

Every response explicitly states \`run_artifact_bytes_verified: false\`,
\`dispatch_origin_authenticated: false\`, \`verified_complete: false\`,
and \`merge_authorized: false\`.

## Next step for one real candidate

1. Open the candidate's \`run_url\` and download its original
   \`fleet-r06-phimada-<run ID>\` ZIP from GitHub before expiry.
2. Confirm it includes \`dispatch.json\` from the new traced workflow.
   Historical pre-#127 runs (for example Agentora R0.6's successful
   November 3, 2026 run #41686772288) are **legacy untraced evidence**;
   never claim an old run proves a later R10 mission.
3. Call the existing \`fleet_r10_mission_evidence.py correlate\` with the
   **actual run ID**, artifact ZIP, held intake, current fenced lease
   and explicit operator confirmation as documented in
   [Fleet R10 Evidence to QA](FLEET_R10_EVIDENCE_TO_QA.md).
4. R0.7 independently checks GitHub metadata and artifact SHA-256 plus
   the marker's exact run ID/source. R4 revalidates source, lease and
   execution window. Only that separate step can persist
   \`CORRELATED_PENDING_QA\`, after which a distinct operator
   \`handoff\` may release the implementer and queue another QA worker.

**No filename, timestamp, identical source SHA, or green Actions status
by itself links a run to a mission.** Even a validated public request ID
is not cryptographic proof of who dispatched it.

## Tests

\`\`\`bash
PYTHONPATH=server python -m pytest -q \
  server/tests/test_fleet_r10_run_discovery.py
\`\`\`

Tests demonstrate a correct bounded candidate from accepted R9/R10/R5
journals, missing/rejected intents held before GitHub reads, old/unrelated
runs filtered, multiple plausible runs left ambiguous, queued/failed runs
not accepted, forged metadata rejected, strict limits, stale dispatch
holds, and no need for an expired lease merely to discover past runs.

This is a **candidate discovery rung**. The field loop remains unqualified
until a new real R10-originated run, exact-traced GitHub artifact, and
separate QA handoff are observed.

Ledger Above Ego. People Above Profit.
