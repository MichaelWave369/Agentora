"""ΦConstruct R3: independently observe current source HEAD and fenced local lease.

Reuses Agentora R0.5's trusted GitHub GET-only source observer and R2's
operator-confirmed assignment. This is **not** training-result attestation:
a candidate PASS in RepoNerve's JSON remains merely a claim.

No worker execution, Docker operation, lease issuance, token export, dispatch,
merge, deployment, or general competence certification is performed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server"))

import construct_training_assignment as assignment
import construct_training_intake as training
import fleet_r04_leases as leases
import fleet_r05_source_observe as source
from app.services.fleet_stewards import StewardRegistry, StewardHeld

SCHEMA = "agentora.construct.training-source-evidence.v0.3"
CONFIRM = "CORRELATE_CONSTRUCT_SOURCE_AND_LEASE"


class CorrelationHeld(ValueError):
    """Source, lease, or submitted training input could not be correlated."""


def require(ok, code):
    if not ok:
        raise CorrelationHeld(code)


def _observed(receipt, source_intake, existing):
    """Validate the independently fetched R0.5 receipt's exact scoped assertions."""
    info = leases.validate_intake(source_intake)
    require(type(receipt) is dict and receipt.get("schema") == source.SCHEMA
            and receipt.get("state") == "SOURCE_HEAD_MATCH_OBSERVED"
            and receipt.get("source_head_observed_match") is True
            and receipt.get("repository_identity_observed_match") is True
            and receipt.get("lease_fenced_at_observation") is True
            and receipt.get("repository") == info["repository"]
            and receipt.get("repository_id") == info["repository_id"]
            and receipt.get("request_sha256") == info["request_sha256"]
            and receipt.get("requested_sha") == info["source_sha"]
            and receipt.get("first_observed_sha") == info["source_sha"]
            and receipt.get("last_observed_sha") == info["source_sha"]
            and receipt.get("lease_generation") == existing["lease_generation"]
            and receipt.get("lease_worker") == existing["lease_worker"]
            and receipt.get("default_branch") == source_intake["default_branch"]
            and receipt.get("code_executed") is False
            and receipt.get("merge_authorized") is False,
            "INDEPENDENT_SOURCE_OBSERVATION_HELD")


def correlate(request, source_intake, registry, ledger, capability, *,
              confirm, report=None, source_get=source.github_get,
              token=None, now=None, clock=leases.epoch_ms):
    """Correlate source HEAD plus same-host lease, never test outcome.

    Source GETs occur outside DB transactions. Preflight and postflight
    repeat the live HEAD read and local fence check. This narrows but does
    not eliminate time-of-check/time-of-use races for a later executor.
    """
    require(confirm == CONFIRM, "EXPLICIT_REVIEW_CONFIRMATION_REQUIRED")
    require(callable(source_get) and callable(clock), "OBSERVER_REQUIRED")
    now = now or datetime.now(timezone.utc)
    require(type(now) is datetime and now.tzinfo is not None, "TIMEZONE_CLOCK_REQUIRED")

    try:
        training.validate_handoff(request)
        if report is not None:
            training.validate_report(report, request)
        source.validate_branch(source_intake.get("default_branch"))
        first_binding = assignment.review_binding(
            request, source_intake, registry, ledger, capability,
            confirm=assignment.CONFIRM, now=now, now_ms=clock(),
        )
        require(first_binding["state"] ==
                "LOCAL_TRAINING_BINDING_REVIEWED_NO_EXECUTION"
                and first_binding["existing_lease_checked_at_review"] is True,
                "EXISTING_BINDING_NOT_ELIGIBLE")

        def observe():
            result = source.observe(
                source_intake, capability, ledger,
                get=source_get, token=token, clock=clock,
            )
            _observed(result, source_intake, first_binding)
            return result

        before = observe()
        after = observe()
        last_binding = assignment.review_binding(
            request, source_intake, registry, ledger, capability,
            confirm=assignment.CONFIRM, now=now, now_ms=clock(),
        )
        # Renewing the lease mid-review may be legitimate, but the operator
        # must explicitly repeat the correlation for the new expiry snapshot.
        require(
            first_binding["lease_generation"] == last_binding["lease_generation"]
            and first_binding["lease_expires_ms"] == last_binding["lease_expires_ms"]
            and first_binding["source_scan_id"] == last_binding["source_scan_id"]
            and first_binding["steward_key"] == last_binding["steward_key"]
            and first_binding["source_sha"] == last_binding["source_sha"],
            "STEWARD_OR_LEASE_CHANGED_DURING_REVIEW",
        )
    except (training.TrainingHeld, assignment.AssignmentHeld,
            leases.LeaseHeld, source.ObservationHeld, StewardHeld) as exc:
        raise CorrelationHeld("TRUST_BOUNDARY_HELD_" + str(exc)) from None

    return {
        "schema": SCHEMA,
        "state": "SOURCE_HEAD_AND_LOCAL_LEASE_CORRELATED_TRAINING_UNATTESTED",
        "training_request_id": request["request_id"],
        "handoff_digest": request["handoff_digest"],
        "agent_label_claim": request["agent_label"],
        "training_mode": request["mode"],
        "task": dict(request["task"]),
        "pack_digest_claim": request["approved_pack"]["digest"],
        "welcome_charter_version": training.CHARTER["version"],
        "candidate_training_result_claim": (
            report["candidate_claim"] if report is not None else None
        ),
        "candidate_report_digest_claim": (
            report["report_digest"] if report is not None else None
        ),
        "repository": first_binding["repository"],
        "github_id": first_binding["github_id"],
        "default_branch": source_intake["default_branch"],
        "source_sha": first_binding["source_sha"],
        "source_scan_id": first_binding["source_scan_id"],
        "steward_key": first_binding["steward_key"],
        "lease_worker": first_binding["lease_worker"],
        "lease_generation": first_binding["lease_generation"],
        "lease_expires_ms": first_binding["lease_expires_ms"],
        "source_observations": [
            {
                "observed_utc": result["observed_utc"],
                "first_observed_sha": result["first_observed_sha"],
                "last_observed_sha": result["last_observed_sha"],
                "git_api_reads": result["git_api_reads"],
            }
            for result in (before, after)
        ],
        "source_head_independently_observed": True,
        "repository_identity_independently_observed": True,
        "local_lease_valid_at_review": True,
        "remote_runner_attested_local_lease": False,
        "pack_approval_independently_verified": False,
        "training_result_independently_verified": False,
        "training_executor_authenticated": False,
        "agent_identity_authenticated": False,
        "training_executed_by_this_command": False,
        "capability_verified": False,
        "execution_authorized": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "future_head_stability_guaranteed": False,
        "notes": (
            "Read-only GitHub source HEAD and a same-host fenced lease were "
            "independently checked at review time. Training output remains "
            "unattested, and the lease cannot authenticate any remote runner."
        ),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--handoff", type=Path, required=True)
    p.add_argument("--intake", type=Path, required=True)
    p.add_argument("--report", type=Path, default=None,
                   help="Optional untrusted RepoNerve inspection JSON")
    p.add_argument("--steward-db", type=Path, required=True)
    p.add_argument("--lease-db", type=Path, required=True)
    p.add_argument("--lease-file", type=Path, required=True)
    p.add_argument("--confirm", required=True)
    a = p.parse_args(argv)
    try:
        require(a.confirm == CONFIRM, "EXPLICIT_REVIEW_CONFIRMATION_REQUIRED")
        for path in (a.steward_db, a.lease_db):
            target = path.expanduser()
            require(target.is_file() and not target.is_symlink(),
                    "EXISTING_PRIVATE_LEDGER_REQUIRED")
        request = training.read_local_json(a.handoff)
        intake = leases.load_intake(a.intake.expanduser())
        report = training.read_local_json(a.report) if a.report else None
        registry = StewardRegistry(a.steward_db.expanduser())
        ledger = leases.LeaseLedger(a.lease_db.expanduser())
        capability = leases.load_capability(a.lease_file.expanduser())
        result = correlate(
            request, intake, registry, ledger, capability,
            confirm=a.confirm, report=report,
            token=os.environ.get("GITHUB_TOKEN"),
        )
        print(json.dumps(result, sort_keys=True, indent=2, ensure_ascii=False))
        return 0
    except (CorrelationHeld, training.TrainingHeld, leases.LeaseHeld,
            source.ObservationHeld, StewardHeld, OSError, ValueError) as exc:
        print("CONSTRUCT_R3_HELD " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
