"""Fleet R10: correlate one fixed GitHub pilot run and queue independent R9 QA.

Use the existing R0.7 + R4 GitHub run, artifact digest, exact head and active
local lease verification. No new GitHub write authority or runner dispatch.
A verified sandbox test never counts as product completion or QA approval.

The correlation record and QA handoff are separate explicit local actions.
Any uncertain state holds for human reconciliation, never silently retries.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
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
import fleet_r07_evidence_review as evidence
import fleet_r4_steward_evidence as r4
import fleet_r9_mission_control as r9
import fleet_r10_r9_r5_bridge as bridge
import fleet_r5_guarded_dispatch as r5

SCHEMA = "agentora.fleet.r10-evidence-to-qa.v1"
CORRELATE_CONFIRM = "CORRELATE_R10_FIXED_PILOT_RUN"
HANDOFF_CONFIRM = "QUEUE_R10_INDEPENDENT_QA"
ACCEPTED = "REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED"
RECORDED = "CORRELATED_PENDING_QA"


class EvidenceHeld(ValueError):
    """Reject incomplete source, run, lease, or mission evidence."""


def need(ok, reason):
    if not ok:
        raise EvidenceHeld(reason)


def _dispatch_link(control, mission_id, candidate, request_id, *, db):
    # The existing R10 and R5 local journals must agree. Journal entries
    # alone are not evidence of a run and cannot create authorization.
    exists = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('r10_r5_dispatch_links','r5_fixed_dispatches')")}
    need(exists == {"r10_r5_dispatch_links", "r5_fixed_dispatches"},
         "NO_MATCHING_R10_R5_DISPATCH_JOURNALS")
    a = db.execute("SELECT * FROM r10_r5_dispatch_links WHERE mission_id=?",
                   (mission_id,)).fetchone()
    b = db.execute("SELECT * FROM r5_fixed_dispatches WHERE request_id=?",
                   (request_id,)).fetchone()
    need(a is not None and b is not None and
         a["request_id"] == request_id and b["request_id"] == request_id and
         a["state"] == ACCEPTED and b["state"] == ACCEPTED and
         a["github_id"] == b["github_id"] == candidate["repository_id"] and
         a["source_sha"] == b["source_sha"] == candidate["source_sha"] and
         a["intake_digest"] == candidate["intake_digest"] and
         a["lease_generation"] == b["lease_generation"] == candidate["generation"] and
         b["worker"] == candidate["worker"],
         "DISPATCH_JOURNALS_NOT_ACCEPTED_OR_IDENTITY_DRIFT")
    return a, b


def _check(control, mission_id, intake, capability, now_ms):
    candidate = bridge._candidate(control, mission_id, intake, capability, now_ms)
    request_id = bridge._request_id(mission_id)
    with control.leases._connection() as db:
        _dispatch_link(control, mission_id, candidate, request_id, db=db)
        old_table = db.execute("""SELECT name FROM sqlite_master
            WHERE type='table' AND name='r10_evidence_links'""").fetchone()
        if old_table:
            row = db.execute("SELECT mission_id FROM r10_evidence_links "
                             "WHERE mission_id=?", (mission_id,)).fetchone()
            need(row is None, "EVIDENCE_ALREADY_CORRELATED_NO_REPLAY")
    return candidate, request_id


def correlate(control, mission_id, intake, capability, run_id, archive_bytes, *,
              confirmation, now=None, clock_ms=None,
              github_get=evidence.fixed_github_get,
              source_get=source.github_get, token=None):
    """Corroborate existing fixed run before recording a private mission link.

    Must not infer a run ID by timestamp or copy arbitrary user-provided
    'passed' flags into the ledger. R4 re-reads GitHub and artifact digest.
    """
    need(confirmation == CORRELATE_CONFIRM, "EXPLICIT_EVIDENCE_REVIEW_REQUIRED")
    need(type(run_id) is int and 0 < run_id < 10**20, "RUN_ID_INVALID")
    need(type(archive_bytes) is bytes and
         0 < len(archive_bytes) <= evidence.MAX_ARCHIVE_BYTES,
         "PILOT_ARCHIVE_INVALID")
    now = now or datetime.now(timezone.utc)
    need(isinstance(now, datetime) and now.tzinfo is not None,
         "CLOCK_INVALID")
    moment = int(now.timestamp() * 1000) if clock_ms is None else clock_ms
    moment = leases.epoch_ms(moment)
    candidate, request_id = _check(
        control, mission_id, intake, capability, moment)
    verified = r4.correlate(
        control.registry, control.leases, intake, capability, run_id,
        archive_bytes, confirmation=r4.CONFIRM, now=now, clock_ms=moment,
        github_get=github_get, source_get=source_get, token=token)
    need(verified.get("state") == "SANDBOXED_CHECKS_CORRELATED_WITH_LOCAL_LEASE"
         and verified.get("dispatch_request_id") == request_id
         and verified.get("dispatch_trace_present") is True
         and verified.get("dispatch_origin_authenticated") is False
         and verified.get("workflow_run_id") == run_id
         and verified.get("repository_id") == candidate["repository_id"]
         and verified.get("source_sha") == candidate["source_sha"]
         and verified.get("lease_generation") == candidate["generation"]
         and verified.get("lease_worker") == candidate["worker"]
         and verified.get("lease_attested_by_github_runner") is False
         and verified.get("product_verified") is False
         and verified.get("verified_complete") is False
         and verified.get("merge_authorized") is False,
         "GITHUB_RUN_NOT_CORRELATED_TO_EXACT_R10_MISSION")
    digest = verified.get("github_artifact_sha256")
    artifact_id = verified.get("github_artifact_id")
    need(type(digest) is str and r9.DIGEST.fullmatch(digest) is not None
         and type(artifact_id) is int and artifact_id > 0,
         "ARTIFACT_ID_OR_DIGEST_INVALID")
    with control.leases._transaction() as db:
        # Revalidate after the remote reads and before the single local write.
        m = db.execute("SELECT * FROM r9_missions WHERE mission_id=?",
                       (mission_id,)).fetchone()
        need(m is not None and m["state"] == "ASSIGNED_IMPLEMENT"
             and m["kind"] == r9.KIND_TEST and m["policy"] == r9.PUBLIC_ALLOWED
             and m["repository"] == candidate["repository"]
             and m["github_id"] == candidate["repository_id"]
             and m["source_sha"] == candidate["source_sha"]
             and m["intake_digest"] == candidate["intake_digest"]
             and m["worker"] == candidate["worker"]
             and m["generation"] == candidate["generation"],
             "MISSION_CHANGED_DURING_EVIDENCE_REVIEW")
        try:
            local = control.leases._check_owned(db, capability, moment)
        except leases.LeaseHeld:
            raise EvidenceHeld("LEASE_EXPIRED_DURING_EVIDENCE_REVIEW") from None
        need(local["repository_id"] == candidate["repository_id"]
             and local["source_sha"] == candidate["source_sha"]
             and local["request_sha256"] == candidate["intake_digest"]
             and local["worker"] == candidate["worker"]
             and local["generation"] == candidate["generation"],
             "LEASE_CHANGED_DURING_EVIDENCE_REVIEW")
        _dispatch_link(control, mission_id, candidate, request_id, db=db)
        db.execute("""CREATE TABLE IF NOT EXISTS r10_evidence_links (
            mission_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
            workflow_run_id INTEGER NOT NULL UNIQUE,
            github_artifact_id INTEGER NOT NULL,
            github_artifact_sha256 TEXT NOT NULL,
            source_sha TEXT NOT NULL, lease_generation INTEGER NOT NULL,
            state TEXT NOT NULL, correlated_ms INTEGER NOT NULL,
            updated_ms INTEGER NOT NULL
        )""")
        previous = db.execute("SELECT mission_id FROM r10_evidence_links "
                              "WHERE mission_id=? OR workflow_run_id=?",
                              (mission_id, run_id)).fetchone()
        need(previous is None, "MISSION_OR_RUN_EVIDENCE_ALREADY_LINKED")
        db.execute("""INSERT INTO r10_evidence_links (
            mission_id, request_id, workflow_run_id, github_artifact_id,
            github_artifact_sha256, source_sha, lease_generation, state,
            correlated_ms, updated_ms) VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (mission_id, request_id, run_id, artifact_id, digest,
             candidate["source_sha"], candidate["generation"],
             RECORDED, moment, moment))
    return {"schema": SCHEMA, "state": RECORDED,
            "mission_id": mission_id, "request_id": request_id,
            "workflow_run_id": run_id, "github_artifact_id": artifact_id,
            "github_artifact_sha256": digest,
            "github_artifact_correlated": True,
            "dispatch_origin_authenticated": False,
            "independent_qa_complete": False,
            "product_verified": False, "verified_complete": False,
            "dispatch_authorized": False, "merge_authorized": False}


def handoff(control, mission_id, capability, *, confirmation, now_ms=None):
    """Release the R9 implementer lease to queue a DIFFERENT QA worker.

    This is a local QA assignment only, not independent QA success.
    A crash between R9 handoff and link update is recognized safely on replay.
    """
    need(confirmation == HANDOFF_CONFIRM, "OPERATOR_QA_HANDOFF_REQUIRED")
    bridge._request_id(mission_id)  # validate input; no arbitrary SQL identifiers
    moment = leases.epoch_ms(now_ms)
    with control.leases._connection() as db:
        exists = db.execute("SELECT name FROM sqlite_master "
                            "WHERE type='table' AND name='r10_evidence_links'").fetchone()
        need(exists is not None, "NO_CORRELATED_EVIDENCE")
        link = db.execute("SELECT * FROM r10_evidence_links WHERE mission_id=?",
                          (mission_id,)).fetchone()
        mission = db.execute("SELECT * FROM r9_missions WHERE mission_id=?",
                             (mission_id,)).fetchone()
        need(link is not None and mission is not None and
             mission["kind"] == r9.KIND_TEST and
             link["source_sha"] == mission["source_sha"] and
             link["lease_generation"] == mission["generation"],
             "QA_EVIDENCE_MISSION_IDENTITY_CHANGED")
        if (mission["state"] == "QA_QUEUED" and
            mission["evidence_sha256"] == link["github_artifact_sha256"] and
            link["state"] in (RECORDED, "QA_QUEUED")):
            # Safe reconciliation after a process exits between the two commits.
            recovered = True
        else:
            need(mission["state"] == "ASSIGNED_IMPLEMENT" and
                 link["state"] == RECORDED,
                 "QA_HANDOFF_ALREADY_STARTED_OR_INVALID")
            try:
                owned = control.leases._check_owned(db, capability, moment)
            except leases.LeaseHeld:
                raise EvidenceHeld("QA_IMPLEMENTER_LEASE_NOT_CURRENT") from None
            need(owned["repository_id"] == mission["github_id"] and
                 owned["source_sha"] == mission["source_sha"] and
                 owned["worker"] == mission["worker"] and
                 owned["generation"] == mission["generation"],
                 "QA_IMPLEMENTER_IDENTITY_MISMATCH")
            recovered = False
    if not recovered:
        control.handoff_to_qa(mission_id, capability,
                              link["github_artifact_sha256"], now_ms=moment)
    with control.leases._transaction() as db:
        m = db.execute("SELECT state,evidence_sha256 FROM r9_missions "
                       "WHERE mission_id=?", (mission_id,)).fetchone()
        need(m is not None and m["state"] == "QA_QUEUED" and
             m["evidence_sha256"] == link["github_artifact_sha256"],
             "QA_HANDOFF_REMOTE_STATE_NOT_CONSISTENT")
        db.execute("""UPDATE r10_evidence_links
            SET state='QA_QUEUED', updated_ms=? WHERE mission_id=? AND
            state IN (?, 'QA_QUEUED')""",
            (moment, mission_id, RECORDED))
    return {"schema": SCHEMA, "state": "QA_QUEUED_FOR_DIFFERENT_WORKER",
            "mission_id": mission_id, "workflow_run_id": link["workflow_run_id"],
            "github_artifact_sha256": link["github_artifact_sha256"],
            "github_artifact_correlated": True,
            "independent_qa_complete": False, "review_approved": False,
            "product_verified": False, "verified_complete": False,
            "merge_authorized": False, "dispatch_authorized": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--steward-db", type=Path, required=True)
    p.add_argument("--lease-db", type=Path, required=True)
    p.add_argument("--mission-id", required=True)
    p.add_argument("--lease-file", type=Path, required=True)
    sub = p.add_subparsers(dest="action", required=True)
    c = sub.add_parser("correlate")
    c.add_argument("--intake", type=Path, required=True)
    c.add_argument("--run-id", type=int, required=True)
    c.add_argument("--artifact-zip", type=Path, required=True)
    c.add_argument("--confirm", required=True)
    h = sub.add_parser("handoff")
    h.add_argument("--confirm", required=True)
    args = p.parse_args(argv)
    try:
        control = r9.MissionControl(
            StewardRegistry(args.steward_db.expanduser()),
            leases.LeaseLedger(args.lease_db.expanduser()))
        capability = leases.load_capability(args.lease_file.expanduser())
        if args.action == "correlate":
            source_file = args.artifact_zip.expanduser()
            need(source_file.is_file() and not source_file.is_symlink() and
                 0 < source_file.stat().st_size <= evidence.MAX_ARCHIVE_BYTES,
                 "PILOT_ARCHIVE_FILE_UNSAFE")
            result = correlate(control, args.mission_id,
                leases.load_intake(args.intake.expanduser()), capability,
                args.run_id, source_file.read_bytes(), confirmation=args.confirm,
                token=os.environ.get("GITHUB_TOKEN"))
        else:
            result = handoff(control, args.mission_id, capability,
                             confirmation=args.confirm)
        print(json.dumps(result, indent=2))
        return 0
    except (EvidenceHeld, r4.CorrelationHeld, evidence.ReviewHeld,
            bridge.BridgeHeld, r9.MissionHeld, leases.LeaseHeld,
            source.ObservationHeld, StewardHeld,
            sqlite3.Error, OSError, ValueError) as exc:
        reason = ("LOCAL_INPUT_OR_LEDGER_UNAVAILABLE"
                  if isinstance(exc, (sqlite3.Error, OSError))
                  or (type(exc) is ValueError) else str(exc))
        print("FLEET_R10_EVIDENCE_HELD " + reason, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
