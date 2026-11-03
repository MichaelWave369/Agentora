# Agentora Fleet Mode R0.1: read-only ecosystem audit

**Status:** first-rung pilot implementation, not a completion engine. An audit does not approve jobs, merge PRs, deploy sites, or certify a release.

## Purpose

Inventory all accessible public repositories owned by MichaelWave369 (fully paginate). Perform a **deep evidence audit** for six pilot repositories by default, or all public owned repositories when explicitly selected. Return a machine-readable JSON audit and a human-readable Markdown report that can later drive reviewed roadmaps.

Pilot repositories: Agentora, PhiOS, PhiServe, FieldConstellation, BTM, SuperPhiVessel.

## Run

On GitHub: Agentora → Actions → **Fleet R0.1 Read-Only Audit** → Run workflow → choose *pilot* or *all*. The workflow has only contents:read permission, does not persist checkout credentials, never calls a GitHub write endpoint, and uploads the fleet-audit.json / fleet-audit.md artifact for seven days. A manually triggered run is not scheduled or ongoing monitoring.

Locally (public-only, token optional):

    python scripts/fleet_r01_audit.py --scope pilot
    python scripts/fleet_r01_audit.py --scope all --output-dir ./fleet-artifacts
    python -m unittest discover -s server/tests -p test_fleet_r01_audit.py -v

**Private repos are not scanned by the hosted workflow.** To audit privately on your own machine only, put a least-privilege GitHub token into GH_TOKEN and use --include-private with a local output path; do not upload that report or token to a public repository. The script rejects --include-private when GITHUB_ACTIONS=true. If the account or token cannot see private repositories, absence is not proof that none exist.

## What is actually observed

| Surface | Observation | Cannot conclude |
| --- | --- | --- |
| Catalog | GitHub-owned repository metadata | That all projects work |
| Default branch | Current commit SHA from branch endpoint | That it builds |
| CI | Recent Actions runs matching that exact head | That every required check passed, that a release works |
| Pages | Public HTML on exact owner github.io URL, without redirects | That React mounts, game runs, or UI passes testing |
| Release | Published GitHub release metadata | That binary installs or starts |
| Software type | Root package.json React dependency hint | That an app uses React successfully or that a nested app lacks React |
| Relationships | README links to other known owner repositories | That cross-repository integrations are executable |

Missing/inaccessible API evidence remains NOT_VERIFIED. CI failure is not automatically classified as a project failure. Published Pages HTML is not runtime acceptance. README links are editorial source references, not dependency proofs.

## Reports

- schema: agentora.fleet.audit.v0.1
- repository_count: enumerated owned repos in requested visibility scope
- deep_audited_count: repos that received deep reads
- completion: NOT_AUDITED or UNVERIFIED, **never COMPLETE** in R0.1
- roadmap: evidence gaps and proposed checks, not implementation claims
- merge_authorized / job_dispatch_authorized: **false**, always

**Visibility:** the public workflow only calls the GitHub public user repository endpoint. It publishes no private repository names, links or data. The local opt-in private mode should be stored outside any synced/public directory.

## Failure and trust policy

- GitHub repository enumeration must finish all pages; it fails rather than issuing an incomplete "all repos" claim.
- API requests are fixed to api.github.com, all GET. No PR, label, workflow dispatch, commit, merge, issue or release write operations.
- Page probes never send tokens, are restricted to the exact owner github.io hostname and repository path, and do not follow redirects. Custom domains are NOT_PROBED, not called broken.
- Individual observation failures produce explicit evidence-limit codes. The global inventory fails closed on incomplete pages or unexpected response shape.
- Bounded API responses, four deep scan workers, and optional all-repo scope prevent unlimited requests. GitHub API rate limits may still interrupt a very large audit.

## Next rung, not yet implemented

R0.2 should add per-project completion contracts (games, VR, website, desktop, library, research, OS), actual browser/installation smoke receipts, provenance-backed dependency edges and a prioritizable issue queue. Only after those gates: scoped worker dispatch, branch PRs, separate code review and exact-head CI merge policies with explicit operator authority.
