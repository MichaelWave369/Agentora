# Agentora Fleet R4: steward reservation ↔ independent sandbox evidence

This rung joins existing mechanisms instead of introducing another execution
engine or reducing protections.

- R1/R2: PhiRepoNerve-observed public repository identity and durable logical steward
- R3: Active same-host SQLite lease with worker, source SHA and fencing generation
- R0.5: Re-observe live GitHub repository ID and current HEAD before and after review
- R0.6: Manually triggered fixed PhiMadaPrime tests + Vite build inside network-disabled Docker
- R0.7: Re-fetch GitHub workflow metadata and SHA-256-correlated artifact ZIP before accepting evidence

R4 checks those identity, source and temporal boundaries and writes a new,
strictly **observation-only** receipt. This records one manual pilot whose
sandboxed checks were successful, under a same-host local reservation.

## Operator workflow (one fixed repo, no general dispatch)

1. Complete RepoNerve local scan and R1 public export; ingest into R2 steward DB.
2. Generate a held R0.3 intake receipt for the **public** PhiMadaPrime main SHA.
3. Make a local R3 claim using a TTL that covers the full verification run
   (maximum R0.4 lease duration 30 minutes; renew if necessary).
4. In Agentora GitHub Actions, manually trigger
   '.github/workflows/fleet-r06-phimada-pilot.yml' with exact source SHA and
   the fixed confirmation string 'RUN_PHI_MADA_TESTS'.
5. Download the corresponding 'fleet-r06-phimada-<run_id>' ZIP artifact.
6. While lease is current, correlate using:

    python scripts/fleet_r4_steward_evidence.py \
      --steward-db ~/.agentora/fleet-stewards.sqlite3 \
      --lease-db ~/.agentora/fleet-leases.sqlite3 \
      --intake ./verification-intake.json \
      --lease-file ~/.agentora/private/worker1.lease \
      --run-id 123456789 \
      --artifact-zip ./pilot-artifact.zip \
      --confirm REVIEW_PHI_MADA_EVIDENCE \
      --output ./r4-correlation.json

The CLI makes bounded read-only GitHub requests and checks the existing
local lease. It never initiates the GitHub workflow or executes source code.
The R0.6 GitHub-hosted workflow is the only execution source in this chain.

## Critical distinctions

- **Correlation is not remote attestation.** GitHub's workflow runner cannot
  check the local SQLite lease, so the R4 receipt reports
  'lease_attested_by_github_runner=false'. R4 ensures timestamps fall within
  the reservation window, and validates a live lease at review time. It does
  not prove the remote workflow enforced the lease during execution.
- **Artifact integrity is not product completeness.** The R0.7 receipt checks
  the artifact digest and fixed automated steps. No browser/device acceptance,
  release verification, production deployment or independent reproduction is
  asserted by R4.
- **No automatic dispatch or merge.** All receipts set dispatch and merge
  authority to false; this rung introduces no scheduling daemon, token
  exposure, GitHub writes, or public publish action.
- **Known limitations:** The R0.4 SQLite lease works only on one shared local
  filesystem, and the R1 export exposes public repo identity only. Private
  inventory needs a separately authenticated private operator channel.
  Source HEAD may move after the final check. All status is point-in-time.
- **Next rung:** Bind per-worker attestations to a trusted execution controller
  with enforced fencing at action time, then allow narrowly policy-approved
  automatic test dispatch for candidate source revisions. Keep independent
  verification and release policies separate from the implementing agent.
