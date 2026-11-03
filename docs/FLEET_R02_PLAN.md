# Agentora Fleet Mode R0.2: Completion Intelligence

R0.2 extends the merged R0.1 read-only audit into review-only, **non-dispatchable** work proposals. This is an incremental planning engine, **not** a worker, an autopilot, proof of integration or certification that an application works.

## Operator workflow

1. On Agentora Actions, run **Fleet R0.2 Completion Plan (Review Only)**, selecting pilot first.
2. Download artifact fleet-r02-pilot-<run ID> containing fleet-audit.json/md and fleet-plan.json/md.
3. Review classification signals, per-repository limitations, README-only relationship edges, and task proposals.
4. Promote specific proposals to reviewed work in a **future, separately authorized** execution rung.

Local-only public run:

    python scripts/fleet_r01_audit.py --scope pilot --output-dir fleet-artifacts
    python scripts/fleet_r02_plan.py --input fleet-artifacts/fleet-audit.json --output-dir fleet-artifacts
    python -m unittest discover -s server/tests -p test_fleet_r02_plan.py -v

The hosted workflow has only contents:read and is manual dispatch, never scheduled. No GitHub issues, code changes, PRs, releases, merges, or external jobs are created by these scripts. Public CI refuses private input and private scanning. To plan a locally held private audit, specify --allow-private-local on the computer where the private audit file lives. **Never publish private reports**.

## Typed surface candidate contracts

All classifications are **candidate-only**; many repositories have multiple surfaces, and root files/README can be wrong or incomplete.

| Candidate | Proposed acceptance contract |
|---|---|
| web_app | build, automated tests, rendered-browser smoke, deployment |
| webxr | build, tests, browser smoke, physical-headset acceptance |
| static_site | HTML/asset validation, navigation smoke, deployment |
| python_package | package build, tests, clean install/import |
| node_service | build, tests, functional HTTP/API smoke |
| android | APK build, tests, emulator/device install and smoke |
| desktop | native build, tests, install and launch |
| os_image | reproducible image, VM boot, recovery, hardware acceptance |
| research | methodology, reproduced results, limitations review |

Unsupported or ambiguous projects get **classification_review** first. Candidate contracts do not automatically apply to every repository. R0.2 cannot prove those checks ran; the proposed queue asks an operator to review the intended deliverables and provide appropriate independent verification.

## Relationship graph

README links to another owned repo are recorded as README_REFERENCE_NOT_DEPENDENCY, with verified_runtime_integration=false and blocks_execution=false. These references are useful for discovery, **not** proof of coupling or a real dependency graph. A later version should add manifest-based typed dependencies and executable integration receipts.

## Evidence / freshness boundary

- Input must be a valid Fleet R0.1 audit, fully cover its own declared inventory, and be at most 24 hours old.
- Private rows cannot be processed by the public workflow.
- Each candidate job binds its identity to the exact observed head SHA; absent head SHA is marked UNVERIFIED_HEAD and blocks future dispatch.
- Optional operator-supplied receipts array uses repository, check_id, head_sha, observed_utc and expires_utc. A matching receipt gets **SHA_AND_TIME_MATCH_UNTRUSTED_PROVENANCE**, *not* verified success. A mismatched/stale receipt gets INVALID_OR_STALE_EVIDENCE. Such receipts cannot authorize work, merges or completed status.
- green Actions, HTTP 200 HTML, and a GitHub release are **weak evidence**; no software is marked complete by R0.2.
- Scan failures remain visible limitations; no silent success/skip.
- Deterministic priority numbers are triage heuristics, not guaranteed optimal work order.

## Output and next rung

fleet-plan.json has schema agentora.fleet.plan.v0.2 and contains surface candidates/signals, raw-status projections, evidence review labels, typed reference edges, and priority-sorted tasks with explicit review-only state. fleet-plan.md is an operator-readable summary. Non-audited inventory rows count toward coverage but get no inferred tasks.

**R0.3 suggestion:** owner-approved per-repo completion manifests, true browser/device/build acceptance receipts, verified dependency edges, and controlled task dispatch. Explicit independent code review and merge policy remain separate later gates. No "autonomous merge all" privilege is conferred by this plan.
