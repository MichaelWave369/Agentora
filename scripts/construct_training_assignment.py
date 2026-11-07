"""ΦConstruct R2: operator-confirmed training binding to an EXISTING R3 lease.

Reads an R1 RepoNerve handoff and an R0.3 Agentora source intake.
A valid training handoff is not evidence of identity, pack provenance,
worker execution, GitHub HEAD freshness, or authorization to dispatch.
This module never reserves a lease, runs code, calls GitHub, or changes state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "server"))
import construct_training_intake as training
import fleet_r04_leases as leases
import fleet_r3_steward_claim as steward
from app.services.fleet_stewards import StewardRegistry, StewardHeld

SCHEMA = "agentora.construct.training-assignment.v0.2"
CONFIRM = "BIND_TRAINING_TO_EXISTING_LEASE"
MIN_LEASE_REMAINING_MS = 60_000


class AssignmentHeld(ValueError):
    """No assignment or authority may be inferred from the supplied records."""


def require(condition, code):
    if not condition:
        raise AssignmentHeld(code)


def _safe_preflight(request, source_intake, registry, *, now):
    """Check two untrusted inputs against local steward observations."""
    try:
        intake = training.consume(request)
        metadata = leases.validate_intake(source_intake)
        visible = steward.eligible(registry, source_intake, now=now)
    except (training.TrainingHeld, leases.LeaseHeld,
            steward.HandoffHeld, StewardHeld) as exc:
        raise AssignmentHeld("SOURCE_OR_TRAINING_NOT_ELIGIBLE_" + str(exc)) from None
    require(intake["state"] == "HELD_FOR_OPERATOR_REVIEW_NO_EXECUTION",
            "TRAINING_NOT_HELD")
    require(visible["github_id"] == metadata["repository_id"]
            and visible["repository"] == metadata["repository"],
            "SOURCE_IDENTITY_NOT_CURRENT")
    return metadata, visible


def review_binding(request, source_intake, registry, ledger=None, capability=None, *,
                   confirm=None, now=None, now_ms=None):
    """Preview or confirm association, never grant execution or dispatch.

    With explicit confirmation, recheck an existing R3 lease's bearer
    capability under its local ledger lock. Do not return the capability.
    No binding receipt survives expiry/fencing as an execution credential.
    """
    require(confirm in (None, CONFIRM), "UNRECOGNIZED_OPERATOR_CONFIRMATION")
    if now is None:
        now = datetime.now(timezone.utc)
    require(isinstance(now, datetime) and now.tzinfo is not None,
            "CLOCK_MUST_BE_TIMEZONE_AWARE")
    try:
        moment = leases.epoch_ms(now_ms)
    except leases.LeaseHeld as exc:
        raise AssignmentHeld("CLOCK_INVALID") from exc
    metadata, visible = _safe_preflight(request, source_intake, registry, now=now)

    confirmed = confirm == CONFIRM
    generation = None
    expires_ms = None
    worker = None
    if confirmed:
        require(ledger is not None and capability is not None,
                "EXISTING_R3_LEASE_REQUIRED")
        require(type(capability) is dict, "CAPABILITY_SHAPE_INVALID")
        require(capability.get("worker") == request["agent_label"],
                "WORKER_LABEL_MISMATCH")
        try:
            with ledger._connection() as db:
                lease = dict(ledger._check_owned(db, capability, moment))
                require(lease["repository_id"] == metadata["repository_id"]
                        and lease["repository"] == metadata["repository"]
                        and lease["source_sha"] == metadata["source_sha"]
                        and lease["request_sha256"] == metadata["request_sha256"],
                        "LEASE_INTAKE_MISMATCH")
                require(lease["expires_ms"] - moment >= MIN_LEASE_REMAINING_MS,
                        "LEASE_RENEWAL_REQUIRED")
                require(lease["worker"] == request["agent_label"],
                        "WORKER_LABEL_MISMATCH")
                generation = lease["generation"]
                expires_ms = lease["expires_ms"]
                worker = lease["worker"]
            # Cross-check local steward state after validating the bearer.
            again = steward.eligible(registry, source_intake, now=now)
            require(visible == again, "STEWARD_CHANGED_DURING_BINDING")
            with ledger._connection() as db:
                still_owned = ledger._check_owned(db, capability, moment)
                require(still_owned["generation"] == generation
                        and still_owned["expires_ms"] == expires_ms,
                        "LEASE_CHANGED_DURING_BINDING")
        except (leases.LeaseHeld, steward.HandoffHeld, StewardHeld) as exc:
            raise AssignmentHeld("LEASE_OR_STEWARD_NOT_CURRENT_" + str(exc)) from None

    return {
        "schema": SCHEMA,
        "state": (
            "LOCAL_TRAINING_BINDING_REVIEWED_NO_EXECUTION"
            if confirmed else "HELD_TRAINING_BINDING_PREVIEW"
        ),
        "operator_confirmation_recorded": confirmed,
        "request_id": request["request_id"],
        "handoff_digest": request["handoff_digest"],
        "agent_label": request["agent_label"],
        "training_mode": request["mode"],
        "task": dict(request["task"]),
        "reviewed_pack_claim": dict(request["approved_pack"]),
        "welcome_charter_version": training.CHARTER["version"],
        "knowledge_is_reference_data": True,
        "repository": metadata["repository"],
        "github_id": metadata["repository_id"],
        "source_sha": metadata["source_sha"],
        "source_scan_id": visible["source_scan_id"],
        "steward_key": visible["steward_key"],
        "lease_worker": worker,
        "lease_generation": generation,
        "lease_expires_ms": expires_ms,
        "existing_lease_checked_at_review": confirmed,
        "lease_issued_by_this_command": False,
        "source_claim": "HELD_R0_3_INTAKE_AND_LOCAL_R2_STEWARD",
        "pack_approval_independently_verified": False,
        "agent_identity_authenticated": False,
        "current_github_head_independently_verified": False,
        "remote_worker_lease_attested": False,
        "training_executed": False,
        "training_result_verified": False,
        "worker_started": False,
        "execution_authorized": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "general_competence_verified": False,
        "next_step": (
            "A future execution controller must verify current GitHub HEAD "
            "and the same R3 lease again at effect time, authenticate the "
            "worker and independently corroborate sandbox evidence. This "
            "receipt is not a transferable capability or permission."
        ),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--handoff", required=True, type=Path,
                   help="PhiRepoNerve v0.1 training request JSON")
    p.add_argument("--intake", required=True, type=Path,
                   help="Existing Agentora R0.3 held source intake JSON")
    p.add_argument("--steward-db", type=Path,
                   default=Path("~/.agentora/fleet-stewards.sqlite3"))
    p.add_argument("--lease-db", type=Path,
                   default=Path("~/.agentora/fleet-leases.sqlite3"))
    p.add_argument("--lease-file", type=Path, default=None,
                   help="Existing private R3 capability; never copied to output")
    p.add_argument("--confirm", default=None,
                   help="Explicit local binding review, not execution approval")
    a = p.parse_args(argv)
    try:
        request = training.read_local_json(a.handoff)
        source = leases.load_intake(a.intake.expanduser())
        registry = StewardRegistry(a.steward_db.expanduser())
        if a.confirm is not None:
            require(a.lease_file is not None, "LEASE_FILE_REQUIRED_FOR_CONFIRMATION")
            ledger = leases.LeaseLedger(a.lease_db.expanduser())
            cap = leases.load_capability(a.lease_file.expanduser())
        else:
            require(a.lease_file is None, "LEASE_FILE_REQUIRES_CONFIRMATION")
            ledger, cap = None, None
        result = review_binding(
            request, source, registry, ledger, cap, confirm=a.confirm
        )
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (AssignmentHeld, training.TrainingHeld,
            leases.LeaseHeld, StewardHeld, OSError) as exc:
        print("HELD: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
