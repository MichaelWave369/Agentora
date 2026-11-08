"""R10: owner-triggered R9 mission → existing R5 fixed test workflow dispatch.

No new GitHub write primitive. This adapter binds an already ASSIGNED_IMPLEMENT
R9 fixed PhiMada test mission and current fenced R0.4 lease, then delegates all
GitHub identity/HEAD/workflow rechecks and one-shot POST journaling to R5.

Dry-run is the default. A real POST requires explicit operator confirmation
and an Actions:write token scoped to Agentora. A workflow dispatch 204 means
request accepted, NOT a discovered run, passing test, PR merge, or release.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))
from app.services.fleet_stewards import StewardRegistry, StewardHeld

import fleet_r04_leases as leases
import fleet_r05_source_observe as source
import fleet_r3_steward_claim as steward
import fleet_r5_guarded_dispatch as r5
import fleet_r9_mission_control as r9

SCHEMA = "agentora.fleet.r9-r5-fixed-dispatch-bridge.v1"
CONFIRM = "DISPATCH_R10_R9_FIXED_PHI_MADA_TEST"
UNKNOWN = "POST_OUTCOME_UNKNOWN"


class BridgeHeld(ValueError):
    """An invalid or uncertain request cannot trigger a second GitHub POST."""


def need(ok, reason):
    if not ok:
        raise BridgeHeld(reason)


def _traced_post(sender, request_id):
    """Supply a fixed R10 identifier to the existing workflow POST sender."""
    need(callable(sender), "INVALID_DISPATCH_SENDER")
    _request = request_id
    need(type(_request) is str and r5.REQUEST.fullmatch(_request),
         "INVALID_DISPATCH_TRACE_ID")
    return lambda credential, sha: sender(credential, sha, request_id=_request)


def _request_id(mission_id):
    need(type(mission_id) is str and r9.IDENT.fullmatch(mission_id) is not None,
         "MISSION_ID_INVALID")
    return "r10r5-" + hashlib.sha256(mission_id.encode("ascii")).hexdigest()[:40]


def _candidate(control, mission_id, intake, capability, now_ms):
    info = leases.validate_intake(intake)
    need(info["repository"] == r5.pilot.REPOSITORY and
         info["repository_id"] == r5.pilot.REPOSITORY_ID and
         intake.get("default_branch") == r5.pilot.BRANCH,
         "ONLY_EXISTING_R5_PHI_MADA_TEST_ALLOWED")
    need(type(capability) is dict, "CAPABILITY_INVALID")
    with control.leases._connection() as db:
        row = db.execute("SELECT * FROM r9_missions WHERE mission_id=?",
                         (mission_id,)).fetchone()
        need(row is not None and
             row["state"] == "ASSIGNED_IMPLEMENT" and
             row["kind"] == r9.KIND_TEST and
             row["policy"] == r9.PUBLIC_ALLOWED,
             "R9_FIXED_TEST_MISSION_NOT_ASSIGNED")
        need(row["github_id"] == info["repository_id"] and
             row["repository"] == info["repository"] and
             row["source_sha"] == info["source_sha"] and
             row["intake_digest"] == info["request_sha256"],
             "R9_MISSION_INTAKE_MISMATCH")
        try:
            owned = control.leases._check_owned(db, capability, now_ms)
        except leases.LeaseHeld:
            raise BridgeHeld("R9_LEASE_EXPIRED_OR_FENCED") from None
        need(owned["repository_id"] == row["github_id"] and
             owned["repository"] == row["repository"] and
             owned["source_sha"] == row["source_sha"] and
             owned["request_sha256"] == row["intake_digest"] and
             owned["worker"] == row["worker"] and
             owned["generation"] == row["generation"],
             "R9_LEASE_OR_WORKER_CHANGED")
        return {"repository": row["repository"], "source_sha": row["source_sha"],
                "repository_id": row["github_id"],
                "intake_digest": row["intake_digest"],
                "worker": row["worker"], "generation": row["generation"]}


def _record_intent(control, mission_id, request_id, candidate, now_ms):
    """Persist a conservative one-shot link BEFORE delegating to R5 POST."""
    with control.leases._transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS r10_r5_dispatch_links (
            mission_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
            github_id INTEGER NOT NULL, source_sha TEXT NOT NULL,
            intake_digest TEXT NOT NULL, lease_generation INTEGER NOT NULL,
            state TEXT NOT NULL, attempted_ms INTEGER NOT NULL,
            updated_ms INTEGER NOT NULL
        )""")
        existing = db.execute(
            "SELECT mission_id FROM r10_r5_dispatch_links WHERE mission_id=? OR request_id=?",
            (mission_id, request_id)).fetchone()
        need(existing is None, "R10_DISPATCH_ALREADY_ATTEMPTED_NO_RETRY")
        # Revalidate the mission *inside* the same SQLite transaction used
        # for its lease and both R9/R5 intent ledgers.
        row = db.execute("SELECT * FROM r9_missions WHERE mission_id=?",
                         (mission_id,)).fetchone()
        need(row is not None and row["state"] == "ASSIGNED_IMPLEMENT" and
             row["kind"] == r9.KIND_TEST and
             row["repository"] == candidate["repository"] and
             row["github_id"] == candidate["repository_id"] and
             row["source_sha"] == candidate["source_sha"] and
             row["intake_digest"] == candidate["intake_digest"] and
             row["worker"] == candidate["worker"] and
             row["generation"] == candidate["generation"],
             "R9_MISSION_CHANGED_BEFORE_INTENT")
        db.execute("""INSERT INTO r10_r5_dispatch_links (
            mission_id,request_id,github_id,source_sha,intake_digest,
            lease_generation,state,attempted_ms,updated_ms)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (mission_id, request_id, candidate["repository_id"],
             candidate["source_sha"], candidate["intake_digest"],
             candidate["generation"], UNKNOWN, now_ms, now_ms))


def submit(control, mission_id, intake, capability, *, execute=False,
           confirmation=None, token=None, get=source.github_get,
           post=r5.github_dispatch, now=None, clock_ms=leases.epoch_ms):
    """One fixed R5 submission from one already claimed R9 mission.

    A failed/uncertain request is never silently retried. Local SQLite
    records are not authenticated evidence of a remote GitHub run.
    """
    request_id = _request_id(mission_id)
    need(type(execute) is bool, "EXECUTE_FLAG_INVALID")
    if execute:
        need(confirmation == CONFIRM, "R10_OWNER_EXECUTION_CONFIRMATION_REQUIRED")
        need(type(token) is str and bool(token.strip()), "ACTIONS_WRITE_TOKEN_REQUIRED")
    else:
        need(confirmation is None, "DRY_RUN_MUST_NOT_ASSERT_AUTHORIZATION")
    now = now or datetime.now(timezone.utc)
    need(isinstance(now, datetime) and now.tzinfo is not None,
         "CLOCK_INVALID")
    candidate = _candidate(control, mission_id, intake, capability, clock_ms())
    with control.leases._connection() as db:
        prior = db.execute("""SELECT name FROM sqlite_master
            WHERE type='table' AND name='r10_r5_dispatch_links'""").fetchone()
        if prior:
            existing = db.execute("""SELECT mission_id FROM r10_r5_dispatch_links
                WHERE mission_id=? OR request_id=?""",
                (mission_id, request_id)).fetchone()
            need(existing is None, "R10_DISPATCH_ALREADY_ATTEMPTED_NO_RETRY")

    # Delegate exact HEAD, steward, workflow path and live lease verification
    # to R5 even in dry-run. Neither this nor R9 approves source execution.
    preview = r5.dispatch(control.registry, control.leases, intake, capability,
        request_id=request_id, execute=False, token=None,
        get=get, post=post, now=now, clock_ms=clock_ms)
    need(preview["state"] == "DRY_RUN_READY_NO_DISPATCH",
         "R5_PREFLIGHT_DID_NOT_PASS")
    if not execute:
        return {"schema": SCHEMA, "state": "DRY_RUN_READY_NO_DISPATCH",
                "mission_id": mission_id, "request_id": request_id,
                "repository": candidate["repository"],
                "source_sha": candidate["source_sha"],
                "workflow": r5.WORKFLOW_PATH,
                "run_id": None, "actual_jobs_dispatched": 0,
                "dispatch_authorized": False, "merge_authorized": False,
                "verified_complete": False}

    # Re-observe local ownership, and record the one-shot R10 intent before
    # R5's own preflight and journal. A crash or timeout leaves an unknown
    # outcome which must be reconciled, never retried automatically.
    second = _candidate(control, mission_id, intake, capability, clock_ms())
    need(candidate == second, "R9_ASSIGNMENT_CHANGED_DURING_PREFLIGHT")
    _record_intent(control, mission_id, request_id, candidate, clock_ms())
    # R5 remains the sole POST/HEAD/rules gate. Only the trusted built-in
    # sender attaches the deterministic mission trace to its fixed workflow.
    # Injected test senders retain the historical two-argument shape.
    traced_post = _traced_post(post, request_id) if post is r5.github_dispatch else post
    result = r5.dispatch(control.registry, control.leases, intake, capability,
        request_id=request_id, execute=True, confirmation=r5.CONFIRM,
        token=token, get=get, post=traced_post, now=now, clock_ms=clock_ms)
    with control.leases._transaction() as db:
        db.execute("""UPDATE r10_r5_dispatch_links SET state=?,updated_ms=?
            WHERE mission_id=? AND request_id=? AND state=?""",
            (result["state"], clock_ms(), mission_id, request_id, UNKNOWN))
    return {"schema": SCHEMA, "state": result["state"],
            "mission_id": mission_id, "request_id": request_id,
            "repository": candidate["repository"],
            "source_sha": candidate["source_sha"],
            "workflow": r5.WORKFLOW_PATH, "github_request_accepted":
                result["github_request_accepted"],
            "run_id": None,
            "actual_jobs_dispatched": "UNKNOWN_UNTIL_GITHUB_RUN_DISCOVERED",
            "dispatch_authorized": False, "merge_authorized": False,
            "verified_complete": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steward-db", type=Path, required=True)
    parser.add_argument("--lease-db", type=Path, required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--lease-file", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    args = parser.parse_args(argv)
    try:
        control = r9.MissionControl(
            StewardRegistry(args.steward_db.expanduser()),
            leases.LeaseLedger(args.lease_db.expanduser()))
        result = submit(control, args.mission_id,
            leases.load_intake(args.intake.expanduser()),
            leases.load_capability(args.lease_file.expanduser()),
            execute=args.execute, confirmation=args.confirm,
            token=os.environ.get("GITHUB_TOKEN"))
        print(json.dumps(result, indent=2))
        return 0 if result["state"] in (
            "DRY_RUN_READY_NO_DISPATCH",
            "REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED") else 3
    except (BridgeHeld, r5.DispatchHeld, steward.HandoffHeld, leases.LeaseHeld,
            source.ObservationHeld, r9.MissionHeld, StewardHeld, sqlite3.Error,
            OSError, ValueError) as exc:
        # Never reveal a bearer token, private key, GitHub response body or
        # arbitrary exception text in the operator-facing output.
        safe = str(exc) if isinstance(exc, (BridgeHeld, r5.DispatchHeld,
            steward.HandoffHeld, leases.LeaseHeld, source.ObservationHeld,
            r9.MissionHeld, StewardHeld)) else "LOCAL_INPUT_OR_LEDGER_UNAVAILABLE"
        print("FLEET_R10_HELD " + safe, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
