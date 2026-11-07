# Agentora Fleet R5: guarded single-workflow dispatch

R5 makes the first **real, locally authorized test-workflow submission**.
It uses the existing fixed-scope PhiMadaPrime R0.6 GitHub Actions workflow.
It is not yet an autonomous code-writing agent, a release mechanism, or a
general-purpose executor.

## How to use it locally

Prerequisites: run PhiRepoNerve R1, export public observations through
Agentora R1, ingest them into the R2 steward registry, prepare an R0.3 held
intake for the current exact public PhiMadaPrime main SHA, and obtain a
current R3 local lease for that same repo and source revision.

Preview, without requiring GitHub Actions write credentials:

    python scripts/fleet_r5_guarded_dispatch.py \
      --steward-db ~/.agentora/fleet-stewards.sqlite3 \
      --lease-db ~/.agentora/fleet-leases.sqlite3 \
      --intake ./verification-intake.json \
      --lease-file ~/.agentora/private/worker1.lease \
      --request-id pilot-001

To issue one real test-workflow submission, supply GITHUB_TOKEN through the
operator environment with Actions:write only for Agentora (no content-write
permission needed), then explicitly confirm the specific fixed workflow:

    python scripts/fleet_r5_guarded_dispatch.py \
      --steward-db ~/.agentora/fleet-stewards.sqlite3 \
      --lease-db ~/.agentora/fleet-leases.sqlite3 \
      --intake ./verification-intake.json \
      --lease-file ~/.agentora/private/worker1.lease \
      --request-id pilot-001 \
      --execute --confirm DISPATCH_FIXED_PHI_MADA_TESTS

The R5 code accepts NO arbitrary repository target, workflow path, branch,
shell command, or job payload. The configured target is the existing
fleet-r06-phimada-pilot.yml workflow in MichaelWave369/Agentora. That
workflow itself tests/builds one exact-SHA PhiMadaPrime source revision,
with GitHub checkout contents-read permissions, npm lifecycle scripts
disabled, and fixed test/build commands in network-disabled Docker.

## Conditions required before POST

1. Current RepoNerve-backed steward for immutable PhiMadaPrime repository ID,
   public and not archived.
2. Matching held source-intake fields and current same-host R0.4 fenced lease,
   with at least 60 seconds remaining at the time of submission.
3. Independent current HEAD re-observation using R0.5, twice around an
   active-workflow metadata check; the workflow identity/path is fixed.
4. Exact operator confirmation and a token supplied at runtime.
5. A unique one-shot dispatch intent created atomically in the same SQLite
   transaction domain as the existing lease.

If the POST is accepted with HTTP 204, R5 records only
REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED. The Actions API does not return
a run ID for this request in the 204 response. If a request times out, the
outcome is UNKNOWN and R5 will not automatically retry. A subsequent call
with the same request, or any other request for that same fenced lease
generation and source SHA, is refused to prevent accidental duplicates.

To assess *actual* completion, inspect the GitHub workflow run and use the
existing R0.7 artifact digest verification plus R4 local evidence correlation.
Neither an accepted submission nor even successful automated tests authorize
a GitHub PR merge, a release, or a claim of full product qualification.

## Known limitations

- R5 is explicitly operator invoked. It does not autonomously schedule new
  missions; future policy-governed scheduling must be independently designed.
- The GitHub Actions workflow uses its own runner: local SQLite leases cannot
  remotely stop or fence that runner. R5 checks local ownership at submission,
  but does NOT claim the remote runner attested lease ownership or remained
  within its TTL while testing.
- GitHub Actions concurrency may queue or delay work after the local lease
  expires. The existing workflow still validates exact GitHub HEAD before and
  after testing, but does not consult local SQLite.
- The dispatch request carries no bearer lease capability or private
  RepoNerve data; the only posted inputs are a public SHA and a fixed string.
- Agentora main-branch workflow changes are a separate trust boundary and
  should remain behind code review and branch protection.
- The local dispatch journal has no token. It cannot by itself prove which
  GitHub run belongs to an accepted request, so don't infer provenance solely
  from matching timestamps.

## Next engineering step

Admit bounded, independently authorized worker capabilities for controlled
branch-only development tasks, with effect-time policy checks, worktree
isolation, test evidence, and a separate release/merge authority. Expand beyond
the fixed pilot only after that path is verified.
