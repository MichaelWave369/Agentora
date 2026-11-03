# Fleet R0.3: PhiMada verification request intake

Agentora can read an operator-downloaded, SHA-pinned verification request from a PhiMada Prime desk. It only validates the request and prepares a local review receipt. It does not execute, approve, merge or dispatch anything.

## Prepare in PhiMada Prime

1. Open a public repo desk and prepare a Rung 7 completion contract with the correct surfaces and acceptance checks.
2. Select **Check current CI and PRs** to request a fresh public GitHub HEAD observation.
3. When the observed HEAD matches the contract and is less than 15 minutes old, select **Download Agentora verification request**.
4. The browser downloads JSON locally. It does not upload anything. Operator notes and potentially sensitive details are omitted.
5. If source HEAD changes, rebind the contract, clearing local review ticks, and request a fresh observation.

## Validate locally in Agentora

Run Python 3.12+ in an Agentora checkout:

    python scripts/fleet_r03_acceptance_intake.py --input /path/to/phimada-verification-request-BTM.json --output-dir local-fleet-intake

Output: local-fleet-intake/verification-intake.json.

It will say HELD_FOR_OPERATOR_REVIEW with zero checks run and zero verified completion.

The validator rejects unexpected fields, notes, forged completion, authority claims, foreign repos, unpinned source refs, stale head observations, unsupported surfaces/checks, and payloads over 64KiB. The request SHA-256 is useful for correlating receipts, but does not authenticate who prepared it.

This offline CLI does NOT check remote HEAD independently. The source revision is an observed claim, not a verified current branch fact. Neither scanner nor importer can execute tests, create PRs, merge, dispatch or write to GitHub.

## Receipt classification

- AUTOMATION_CANDIDATE_ONLY: candidate for a future isolated and explicitly approved test runner.
- HUMAN_OR_DEVICE_REQUIRED: needs browser, hardware, manual inspection or expert acceptance.

Every check retains verification_state: NOT_RUN and evidence_receipt: null. Local review checkboxes are never treated as passing checks.

## Future governed execution

Before execution Agentora must independently re-fetch public repo identity and HEAD, compare immutable SHA, obtain scoped operator authorization, run isolated checks, collect exact-SHA evidence receipts and require a separate explicit merge decision.

## Tests

    python -m unittest discover -s server/tests -p test_fleet_r03_intake.py -v
