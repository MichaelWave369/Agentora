"""R3 local-only steward-qualified worker reservation.

Combines the R2 logical steward registry with R0.4 local lease fencing.
Never launches an agent, dispatches, builds, merges, deploys, or checks HEAD.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))
from app.services.fleet_stewards import StewardRegistry, StewardHeld
import fleet_r04_leases as leases

CLAIM_SCHEMA = "agentora.fleet.steward-claim.v0.3"
STATUS_SCHEMA = "agentora.fleet.steward-lease-observation.v0.3"


class HandoffHeld(ValueError):
    """The candidate claim did not meet the verified local shape."""


def require(ok, reason):
    if not ok:
        raise HandoffHeld(reason)


def eligible(registry, intake, *, now=None):
    """Current RepoNerve public steward must match the R0.3 held intake."""
    info = leases.validate_intake(intake)
    now = now or datetime.now(timezone.utc)
    with registry._tx() as conn:
        source = registry._source(conn)
        require(source is not None, "NO_STEWARD_SOURCE")
        try:
            stamp = datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise HandoffHeld("SOURCE_TIME_INVALID") from None
        require(stamp.tzinfo is not None and
                -300 <= (now - stamp).total_seconds() <= 36 * 3600,
                "SOURCE_STALE")
        row = conn.execute("SELECT * FROM stewards WHERE github_id=?",
                           (info["repository_id"],)).fetchone()
        require(row is not None and row["present"] == 1, "STEWARD_NOT_VISIBLE")
        require(row["archived"] == 0, "STEWARD_ARCHIVED")
        require(row["full_name"] == info["repository"], "STEWARD_IDENTITY_CHANGED")
        return {"source_scan_id": source["scan_id"],
                "github_id": row["github_id"],
                "repository": row["full_name"],
                "steward_key": row["steward_key"]}


def claim(registry, ledger, intake, worker, lease_file, *,
          ttl=300, now=None, now_ms=None):
    """Issue an R0.4 reservation, then privately persist its bearer token.

    Cross-DB TOCTOU is mitigated with a second steward identity read, but this
    does not create a distributed lock or execution authority.
    """
    require(type(worker) is str and leases.WORKER.fullmatch(worker) is not None,
            "WORKER_INVALID")
    now = now or datetime.now(timezone.utc)
    prior = eligible(registry, intake, now=now)
    path = Path(lease_file).expanduser()
    require(not path.exists() and not path.is_symlink(), "LEASE_FILE_EXISTS")
    cap = ledger.reserve(intake, worker, ttl_seconds=ttl, now_ms=now_ms)
    try:
        require(eligible(registry, intake, now=now) == prior,
                "SOURCE_CHANGED_DURING_CLAIM")
        leases.save_capability(path, cap, exclusive=True)
    except BaseException:
        try:
            ledger.release(cap, now_ms=now_ms)
        except leases.LeaseHeld:
            pass
        raise
    return {
        "schema": CLAIM_SCHEMA, "state": "LOCAL_RESERVED_FOR_REVIEW",
        "source_scan_id": prior["source_scan_id"],
        "github_id": prior["github_id"], "repository": prior["repository"],
        "steward_key": prior["steward_key"], "worker": worker,
        "source_sha": cap["source_sha"], "generation": cap["generation"],
        "expires_ms": cap["expires_ms"],
        "execution_authorized": False, "dispatch_authorized": False,
        "merge_authorized": False, "verified_complete": False,
    }


def public_status(registry, ledger, *, now=None, now_ms=None):
    """Public-only local view. No tokens, private identities or retired names."""
    now = now or datetime.now(timezone.utc)
    with registry._tx() as conn:
        source = registry._source(conn)
        require(source is not None, "NO_STEWARD_SOURCE")
        try:
            stamp = datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise HandoffHeld("SOURCE_TIME_INVALID") from None
        require(stamp.tzinfo is not None and
                -300 <= (now - stamp).total_seconds() <= 36 * 3600,
                "SOURCE_STALE")
        eligible_repos = {row["github_id"]: row["full_name"] for row in conn.execute(
            "SELECT github_id,full_name FROM stewards WHERE present=1 AND archived=0")}
        scan_id = source["scan_id"]
        observed_at = source["observed_at"]
    source_status = ledger.status(now_ms=now_ms)
    items = []
    for row in source_status["reservations"]:
        current = eligible_repos.get(row["repository_id"])
        if current is None or current != row["repository"]:
            continue
        items.append({
            "github_id": row["repository_id"],
            "repository": current,
            "state": row["state"],
            "generation": row["generation"],
            "expires_ms": row["expires_ms"],
        })
    return {
        "schema": STATUS_SCHEMA, "owner": leases.OWNER,
        "scope": "public_only", "source_scan_id": scan_id,
        "observed_at": observed_at,
        "status": "LOCAL_RESERVATIONS_NOT_RUNNING_AGENTS",
        "reservations": items,
        "active_reservations": sum(x["state"] == "RESERVED" for x in items),
        "actual_jobs_dispatched": 0,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--steward-db", type=Path, default=Path("~/.agentora/fleet-stewards.sqlite3"))
    p.add_argument("--lease-db", type=Path, default=Path("~/.agentora/fleet-leases.sqlite3"))
    subs = p.add_subparsers(dest="action", required=True)
    claim_cmd = subs.add_parser("claim")
    claim_cmd.add_argument("--intake", required=True, type=Path)
    claim_cmd.add_argument("--worker", required=True)
    claim_cmd.add_argument("--lease-file", required=True, type=Path)
    claim_cmd.add_argument("--ttl", type=int, default=300)
    for action in ("renew", "release"):
        cmd = subs.add_parser(action)
        cmd.add_argument("--lease-file", required=True, type=Path)
        if action == "renew":
            cmd.add_argument("--ttl", type=int, default=300)
    subs.add_parser("status")
    a = p.parse_args(argv)
    try:
        registry = StewardRegistry(a.steward_db)
        ledger = leases.LeaseLedger(a.lease_db)
        if a.action == "claim":
            intake = leases.load_intake(a.intake.expanduser())
            result = claim(registry, ledger, intake, a.worker, a.lease_file, ttl=a.ttl)
        elif a.action == "status":
            result = public_status(registry, ledger)
        else:
            path = a.lease_file.expanduser()
            cap = leases.load_capability(path)
            # Confirm the owner has not been archived, renamed or hidden.
            shape = {"schema": leases.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
                     "owner": leases.OWNER, "repository": cap.get("repository"),
                     "repository_id": cap.get("repository_id"),
                     "source_sha": cap.get("source_sha"),
                     "request_sha256": cap.get("request_sha256"),
                     "verified_complete": False, "operator_approved": False,
                     "dispatch_authorized": False, "merge_authorized": False,
                     "head_revalidated_by_agentora": False,
                     "digest_is_authentication": False, "independent_checks_run": 0,
                     "checks": [{"verification_state": "NOT_RUN", "evidence_receipt": None}]}
            eligible(registry, shape)
            if a.action == "renew":
                refreshed = ledger.renew(cap, ttl_seconds=a.ttl)
                leases.save_capability(path, refreshed)
                result = {"state": "LOCAL_RESERVATION_RENEWED",
                          "generation": refreshed["generation"],
                          "expires_ms": refreshed["expires_ms"]}
            else:
                result = ledger.release(cap)
                path.unlink()
        # No bearer capability or arbitrary source data in CLI output.
        print(json.dumps(result, indent=2))
        return 0
    except (HandoffHeld, leases.LeaseHeld, StewardHeld, OSError) as exc:
        print("HELD: " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
