# Fleet R0.7: GitHub Actions artifact evidence review

R0.7 gives Agentora an **evidence-review CLI** for the first R0.6 PhiMada Prime pilot. Its job is to distinguish an arbitrary local JSON file from a GitHub-hosted workflow artifact whose bytes have been independently correlated with GitHub's Actions API.

This is not a general CI agent, autonomous dispatcher, GitHub merge gate or product acceptance certificate. It is fixed to **MichaelWave369/Agentora** workflow \`.github/workflows/fleet-r06-phimada-pilot.yml\` and the **MichaelWave369/PhiMadaPrime** pilot repository.

## First, run an actual R0.6 pilot

A green PR is **not** a pilot run. The R0.6 workflow is manual-only. In Agentora → Actions → **Fleet R0.6 PhiMada Sandboxed Verification Pilot**, select **Run workflow** on the trusted main branch, provide the current 40-character PhiMada Prime main HEAD, and type \`RUN_PHI_MADA_TESTS\`.

The R0.6 workflow performs its own preflight identity/HEAD observations, checks out exactly that SHA, runs fixed Node tests and a Vite build inside bounded network-disabled Docker containers, re-reads GitHub HEAD, and publishes a GitHub Actions artifact named \`fleet-r06-phimada-<run_id>\` with preflight/steps/final JSON receipts.

A passing R0.6 CI job proves none of this has happened. Only the separate manual workflow execution creates a pilot receipt.

## Evidence review

1. Note the numeric **run ID** of a successfully completed R0.6 pilot. Download the matching artifact ZIP from that exact run's Artifacts section using the GitHub UI. Do not copy the ZIP from another run.
2. Place the ZIP in a local, untracked directory such as \`local-fleet/pilot-evidence.zip\`.
3. Run Python 3.12+:

    python scripts/fleet_r07_evidence_review.py --run-id 1234567 --artifact-zip local-fleet/pilot-evidence.zip --output local-fleet/reviews/phimada-r07.json

4. If GitHub API rate limits apply, supply a read-only \`GITHUB_TOKEN\` in the environment. All GitHub reads go to the fixed Actions run and artifacts endpoints; the script makes no GitHub API writes.
5. Inspect the output review JSON. Exit **0** means the complete GitHub run, artifact digest and fixed pilot receipt consistency checks passed. Exit **1** means **FLEET_R07_HELD**, and **no success review is written**.

The output is exclusive-created with mode 0600 on POSIX. It contains an Agentora run link, matching source SHA, separate observed automated check outcomes and explicit false execution/merge authority flags. The operator must still review what checks actually matter to the software.

## Validation boundaries

- **GitHub run identity:** Exact Agentora repository owner, numeric repository ID, successful completed \`workflow_dispatch\`, exact R0.6 workflow path, first run attempt, valid Agentora source SHA, and no older than eight days.
- **GitHub artifact metadata:** Exactly one matching, unexpired R0.6 artifact associated with that run. SHA-256 of the *entire downloaded ZIP byte stream* must match GitHub Actions' reported \`sha256:<digest>\`. A missing/invalid digest fails closed.
- **ZIP safety:** Only three expected JSON members (\`preflight.json\`, \`steps.json\`, \`final.json\`) at root or under \`pilot-control/\`. No duplicate, traversal, symlink, unexpected files or unbounded inflation. The ZIP is inspected in memory, never extracted.
- **Receipt linkage:** Correct PhiMada public repository and numeric ID, identical 40-character SHA at preflight, checkout, recorded fixed command exits, and postflight; identical R0.6 run ID in the final receipt.
- **Authority:** All merge, dispatch, product completion, browser/deployment verification and signed-attestation claims must be false. Manually required checks remain \`NOT_RUN\`.

**A matching artifact digest does not mean the workflow's entire execution environment has a signed attestation.** It provides an integrity correlation from the downloaded ZIP to GitHub's artifact metadata for that run. R0.7 still relies on GitHub's Actions service and the workflow code that was present at the reported Agentora SHA. It does not replay or independently reproduce the tests.

A successful review only records **AUTOMATED CHECKS REPORTED EXIT 0 AT HISTORICAL SOURCE SHA**. R0.7 does not recheck PhiMada's current HEAD, run its tests again, assert a deployed UI works, certify the project complete, or grant a merge. Later independent build/release acceptance and scoped operator decisions must remain separate.

## Limitations and future integration

- If GitHub omits the artifact \`digest\` field or has expired the artifact, this rung refuses to elevate the file to corroborated evidence. Never substitute an untrusted local digest or hardcoded fingerprint.
- R0.7 is currently an offline operator CLI. It does not publish raw receipts to public GitHub Pages, nor automatically update PhiMada's dashboard or local completion checkboxes.
- Run attempts beyond the first are held because reruns can publish distinct artifacts. Later support must explicitly bind artifact IDs and run attempt provenance before accepting them.
- The API reads do not establish that the pilot HEAD is **still** current today.
- This implementation is read-only and supports only the fixed PhiMada pilot. Extending to the fleet needs per-repo execution contracts, signed or independently tied check receipts, run authenticity checks, and operator approval.

## Tests

    python -m unittest discover -s server/tests -p test_fleet_r07_evidence_review.py -v
    PYTHONPATH=server pytest -q server/tests/test_fleet_r07_evidence_review.py

The 16 targeted tests use synthetic GitHub API results and a real in-memory ZIP. They challenge run origin, status, source SHA, workflow identity, digest mismatch, ZIP entry integrity, forged completion flags, partial automated checks and bad IDs. The full Agentora Python 3.12/3.13 CI matrix exercises these tests as part of the normal suite.
