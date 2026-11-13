# Φ Pit Crew R1: one-repo CI status, no new queue

This is the first small removal of MikeyAPI manual routing, **not** the
completed autonomous fleet development loop. It implements a safe signal path
on the existing [Agentora fleet mission #124](https://github.com/MichaelWave369/Agentora/issues/124).

## What happens automatically

The GitHub-hosted `Φ Pit Crew R1 - One-Repo CI Watch` workflow runs at
minute 17 every two hours, when the owner clicks **Run workflow**, or after a
**successful push-triggered Agentora main-branch CI** completes. The last
trigger reads *only* trusted default-branch controller code, never workflow
artifacts or PR-head source. GitHub scheduled runs may be late or skipped.

1. Verify that the fixed public repository `MichaelWave369/PhiMadaPrime`
   still has the known immutable GitHub repository ID, is not private/archived,
   and still uses `main`.
2. Read the **live main SHA** and the corresponding `ci.yml` push run.
   An older commit's green check must never turn this head green. A new
   attempt for the same run is eligible; a newer run takes precedence
   over a rerun of an older run.
3. Record one of **CI_SUCCESS_EXACT_HEAD**, **CI_FAILURE_EXACT_HEAD**,
   **CI_PENDING_EXACT_HEAD**, **CI_INCONCLUSIVE_EXACT_HEAD**, or
   **NO_EXACT_HEAD_CI**. Failure-job names are advisory only.
4. Maintain at most one bot-authored, marker-scoped comment on the existing
   owner-authored Agentora Issue #124, rather than opening a new ticket.
   Identical observations cause no write; a change updates the existing
   comment. A renamed/closed mission or incomplete comment history causes a
   HOLD, not a fallback to some other Issue.
5. For a verified **CI_FAILURE_EXACT_HEAD**, add an **inert structured
   failure-review-candidate.json** artifact. It binds the existing issue,
   target repository ID, SHA, exact CI run ID/attempt, sanitized failed job
   hints, and a deterministic sha256 replay identity. These records are
   *not authenticated release receipts* and must be independently rechecked
   at any later effect-time gate. No candidate is produced for success,
   pending, unknown, or inconclusive results.
6. Store the observation, optional candidate, or explicit HOLD as a seven-day
   GitHub Actions artifact and summarize it on the workflow run.

The public hosted watcher needs **no local install**, SQLite, personal GitHub
token, or manually copied report. Its GitHub-issued workflow token has
`contents:read`, `actions:read`, and `issues:write` on Agentora. The
code's sole possible write is a status comment on Issue #124; it does not
edit the Issue body or labels.

## First live qualification

After normal PR review and merge:

1. Open [the watcher workflow](https://github.com/MichaelWave369/Agentora/actions/workflows/fleet-pitcrew-ci-watch-r1.yml)
   and choose **Run workflow** on `main`. No inputs are needed.
2. Confirm the run's Summary and retained `pitcrew-r1/observation.json`
   (or `hold.json`) match **the current PhiMadaPrime main SHA** and the
   linked GitHub CI run.
3. Open [mission #124](https://github.com/MichaelWave369/Agentora/issues/124).
   Verify exactly one `github-actions[bot]` comment with the R1 marker.
4. Re-run with unchanged upstream evidence; it must print **UNCHANGED**.
   On a genuinely different upstream run, it may **UPDATE**, not duplicate.
5. Inspect the first scheduled run separately; passing PR CI does not prove
   that a scheduled run, cross-repo read, or Issue write actually worked.

The current proposal is **not** inserted into the local Agentora R9
SQLite queue automatically; doing so from a GitHub-hosted runner would
require a real authenticated event-to-queue bridge. Do not treat its
`dedupe_key` as a real queue lock or an owner authorization.

Test locally or in Agentora CI:

```bash
PYTHONPATH=.:server python -m pytest -q server/tests/test_fleet_pitcrew_ci_watch_r1.py
```

## What it explicitly does NOT do

- Not a new scheduler, mission database, agent control plane, or queue.
- No code repair, model call, target code checkout, workflow dispatch, code
  branch, PR publication, merge, deployment, auto-approval, or false claims
  of independent QA.
- No cross-repository private data; only public PhiMadaPrime CI metadata.
- CI success is only automated build/test evidence for one SHA. It is **not**
  a product acceptance, live browser, VR, or hardware qualification.
- If the current SHA has no observed main push CI run, the outcome remains
  `NO_EXACT_HEAD_CI` rather than borrowing a green check from older code.
- Only the first five server-filtered, exact-SHA CI runs and first 99 Issue comments
  are examined; incomplete comment history deliberately holds.

## Next step toward the real closed loop

Feed these exact-run observations through the **existing** Agentora R9
mission and guarded Autonomous R1 handoff, with a replay-safe run+SHA key.
Then qualify one bounded authorized task all the way through real PR CI,
independent evidence, and an owner-controlled merge gate. Keep PhiMadaPrime
a read-only viewer, and do not expand from one repository until that chain
has passed a real hosted field trial.

**Ledger Above Ego. More Bounce, Less Copy-Paste.**

## R1.3 first hosted-run repair (bounded API response)

The first live `workflow_run` trigger succeeded after Agentora main CI,
but [run 43381078494](https://github.com/MichaelWave369/Agentora/actions/runs/43381078494)
held with `API_RESPONSE_OVERSIZED`. The original request fetched up to 30
workflow-run objects; GitHub's verbose JSON exceeded the deliberate 300 kB
response limit. The watcher correctly refused to claim success or comment
on the Issue.

R1.3 asks GitHub to filter by the **observed target SHA** on the server
(`head_sha`) and limits the query to five matching push CI runs. Keep the
existing response-size cap rather than allowing arbitrarily large payloads.
GitHub's documented workflow-run endpoint supports the `head_sha` filter.
If no exact current-head run is returned, report `NO_EXACT_HEAD_CI`, not
success. Verify the next hosted run and the canonical Issue comment before
calling the pit crew live-qualified.
