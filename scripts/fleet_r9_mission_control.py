"""Fleet R9 local mission control: fair bounded assignments and independent QA lanes.

This persists explicit, public-only mission requests against RepoNerve stewards.
Each claim issues a *real* R0.4 fenced local lease through the existing R3
mechanism; QA requires another worker after the implementer's release.

No code executes here. A mission, an evidence pointer, and a QA assignment
are not authorization to dispatch, publish a PR, merge or deploy.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))
from app.services.fleet_stewards import StewardRegistry, StewardHeld
import fleet_r04_leases as leases
import fleet_r3_steward_claim as stewardship
import fleet_r06_pilot as pilot

SCHEMA = "agentora.fleet.mission-control.v0.9"
KIND_AUDIT = "PUBLIC_STANDALONE_READINESS_AUDIT"
KIND_TEST = "PHIMADA_FIXED_TEST"
KIND_PROPOSAL = "PHIMADA_MODEL_PROPOSAL_REVIEW"
KINDS = {KIND_AUDIT, KIND_TEST, KIND_PROPOSAL}
CONFIRM = "ENQUEUE_PUBLIC_REVIEW_MISSION"
IDENT = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
ACTIVE = ("CLAIMING_IMPLEMENT", "ASSIGNED_IMPLEMENT", "HANDOFF_IN_PROGRESS",
          "QA_QUEUED", "CLAIMING_QA", "ASSIGNED_QA", "QA_HELD")
SLOTS = ("CLAIMING_IMPLEMENT", "ASSIGNED_IMPLEMENT",
         "HANDOFF_IN_PROGRESS", "CLAIMING_QA", "ASSIGNED_QA")
PUBLIC_ALLOWED = "PUBLIC_REVIEW_ONLY_NEVER_EXECUTE"


class MissionHeld(ValueError):
    """An operator, source, lease, or policy condition blocked transition."""


def need(ok, why):
    if not ok:
        raise MissionHeld(why)


def _now(now=None):
    now = now or datetime.now(timezone.utc)
    need(isinstance(now, datetime) and now.tzinfo is not None, "CLOCK_INVALID")
    return now.astimezone(timezone.utc)


def _policy(kind, info):
    need(type(kind) is str and kind in KINDS, "MISSION_KIND_NOT_ALLOWLISTED")
    if kind != KIND_AUDIT:
        need(info["repository"] == pilot.REPOSITORY
             and info["repository_id"] == pilot.REPOSITORY_ID,
             "SPECIAL_MISSION_FIXED_PUBLIC_REPO_ONLY")
    return PUBLIC_ALLOWED


def _present(registry, now):
    with registry._tx() as db:
        source = registry._source(db)
        need(source is not None, "NO_REPONERVE_SOURCE")
        ts = datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00"))
        need(-300 <= (now - ts).total_seconds() <= 36 * 3600,
             "REPONERVE_SOURCE_STALE")
        visible = {int(r["github_id"]): r["full_name"] for r in db.execute(
            "SELECT github_id,full_name FROM stewards WHERE present=1 AND archived=0")}
        return visible, source["scan_id"]


class MissionControl:
    def __init__(self, registry, lease_ledger, *, capacity=2):
        need(type(capacity) is int and 1 <= capacity <= 6,
             "CAPACITY_UNSAFE")
        self.registry, self.leases, self.capacity = registry, lease_ledger, capacity
        with self.leases._transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS r9_missions (
                mission_id TEXT PRIMARY KEY,
                github_id INTEGER NOT NULL, repository TEXT NOT NULL,
                source_sha TEXT NOT NULL, intake_digest TEXT NOT NULL,
                kind TEXT NOT NULL, policy TEXT NOT NULL, state TEXT NOT NULL,
                created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
                worker TEXT, generation INTEGER, reviewer TEXT,
                qa_generation INTEGER, evidence_sha256 TEXT,
                issue TEXT
            )""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS
                r9_one_active_mission_per_repo ON r9_missions(github_id)
                WHERE state IN (
                    'QUEUED','CLAIMING_IMPLEMENT','ASSIGNED_IMPLEMENT',
                    'HANDOFF_IN_PROGRESS','QA_QUEUED','CLAIMING_QA',
                    'ASSIGNED_QA','QA_HELD','HELD_RECONCILE'
                )""")

    def enqueue(self, mission_id, kind, intake, *, confirmation, now=None,
                now_ms=None):
        need(type(mission_id) is str and IDENT.fullmatch(mission_id) is not None,
             "MISSION_ID_INVALID")
        need(confirmation == CONFIRM, "OPERATOR_ENQUEUE_CONFIRMATION_REQUIRED")
        info = leases.validate_intake(intake)
        policy = _policy(kind, info)
        now = _now(now)
        identity = stewardship.eligible(self.registry, intake, now=now)
        need(identity["github_id"] == info["repository_id"], "STEWARD_MISMATCH")
        moment = leases.epoch_ms(now_ms)
        with self.leases._transaction() as db:
            old = db.execute("SELECT mission_id FROM r9_missions WHERE mission_id=?",
                             (mission_id,)).fetchone()
            need(old is None, "MISSION_ID_ALREADY_USED_NO_REPLAY")
            prior = db.execute("SELECT mission_id FROM r9_missions WHERE github_id=? "
                "AND state IN ('QUEUED','CLAIMING_IMPLEMENT','ASSIGNED_IMPLEMENT',"
                "'HANDOFF_IN_PROGRESS','QA_QUEUED','CLAIMING_QA',"
                "'ASSIGNED_QA','QA_HELD','HELD_RECONCILE')",
                (info["repository_id"],)).fetchone()
            need(prior is None, "REPOSITORY_HAS_UNRESOLVED_MISSION")
            db.execute("""INSERT INTO r9_missions (
                mission_id,github_id,repository,source_sha,intake_digest,
                kind,policy,state,created_ms,updated_ms
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                mission_id, info["repository_id"], info["repository"],
                info["source_sha"], info["request_sha256"], kind, policy,
                "QUEUED", moment, moment))
        return {"schema": SCHEMA, "state": "QUEUED_LOCAL_ONLY",
                "mission_id": mission_id, "steward_key": identity["steward_key"],
                "source_scan_id": identity["source_scan_id"],
                "mission_kind": kind, "execution_authorized": False,
                "dispatch_authorized": False, "merge_authorized": False}

    def _eligible(self, now, phase, *, db):
        visible, scan_id = _present(self.registry, now)
        state = "QUEUED" if phase == "implement" else "QA_QUEUED"
        rows = db.execute(
            "SELECT * FROM r9_missions WHERE state=? ORDER BY created_ms,mission_id",
            (state,)).fetchall()
        # Across repositories, prefer least recently worked / fewest starts.
        # Counts are only planning history, never evidence of completed work.
        history = {r["github_id"]: (r["starts"],r["latest"]) for r in db.execute(
            """SELECT github_id,
               SUM(CASE WHEN worker IS NOT NULL THEN 1 ELSE 0 END) AS starts,
               MAX(CASE WHEN worker IS NOT NULL THEN updated_ms ELSE 0 END) AS latest
               FROM r9_missions GROUP BY github_id""")}
        available = [r for r in rows if visible.get(r["github_id"]) == r["repository"]]
        available.sort(key=lambda row: (
            history.get(row["github_id"], (0,0))[0],
            history.get(row["github_id"], (0,0))[1],
            row["created_ms"],row["mission_id"]))
        return available, scan_id

    def plan(self, *, phase="implement", now=None):
        need(phase in ("implement","qa"), "PHASE_INVALID")
        now = _now(now)
        with self.leases._connection() as db:
            available, scan = self._eligible(now, phase, db=db)
            busy = db.execute(
                "SELECT COUNT(*) FROM r9_missions WHERE state IN (" +
                ",".join("?" for _ in SLOTS) + ")", SLOTS).fetchone()[0]
        permitted = max(0, self.capacity - busy)
        rows = available[:permitted]
        return {"schema": SCHEMA, "state": "ADVISORY_ONLY",
                "phase": phase, "capacity": self.capacity,
                "occupied_slots": busy, "slots_remaining": permitted,
                "source_scan_id": scan,
                "missions": [{"mission_id": r["mission_id"],
                              "steward_key": "steward-gh-" + str(r["github_id"]),
                              "kind": r["kind"], "source_sha": r["source_sha"]}
                             for r in rows],
                "dispatch_authorized": False, "merge_authorized": False,
                "verified_complete": False}

    def claim_next(self, intake, worker, lease_file, *, phase="implement",
                   ttl=300, now=None, now_ms=None):
        need(phase in ("implement", "qa"), "PHASE_INVALID")
        need(type(worker) is str and leases.WORKER.fullmatch(worker) is not None,
             "WORKER_INVALID")
        info = leases.validate_intake(intake)
        now, moment = _now(now), leases.epoch_ms(now_ms)
        # Both same-host state and source identity are checked again by R3.
        with self.leases._transaction() as db:
            available, scan_id = self._eligible(now, phase, db=db)
            busy = db.execute(
                "SELECT COUNT(*) FROM r9_missions WHERE state IN (" +
                ",".join("?" for _ in SLOTS) + ")", SLOTS).fetchone()[0]
            need(busy < self.capacity, "WORKER_SLOT_CAPACITY_REACHED")
            need(bool(available), "NO_ELIGIBLE_MISSIONS")
            row = available[0]
            need(row["github_id"] == info["repository_id"]
                 and row["repository"] == info["repository"]
                 and row["source_sha"] == info["source_sha"]
                 and row["intake_digest"] == info["request_sha256"],
                 "NEXT_FAIR_MISSION_INTAKE_MISMATCH")
            if phase == "qa":
                need(row["worker"] is not None and row["worker"] != worker,
                     "QA_MUST_BE_SEPARATE_WORKER")
            prior = "QUEUED" if phase == "implement" else "QA_QUEUED"
            claiming = "CLAIMING_IMPLEMENT" if phase == "implement" else "CLAIMING_QA"
            db.execute("""UPDATE r9_missions SET state=?,updated_ms=?
                WHERE mission_id=? AND state=?""",
                (claiming,moment,row["mission_id"],prior))
        # Claim creates an actual fenced R0.4 lease with owner-only secret file.
        # The mission remains CLAIMING if process crashes between operations.
        # Such a mission requires reconciliation, never automatic retry.
        try:
            receipt = stewardship.claim(self.registry, self.leases, intake,
                                        worker, lease_file, ttl=ttl,
                                        now=now, now_ms=moment)
            assigned = ("ASSIGNED_IMPLEMENT" if phase == "implement" else
                        "ASSIGNED_QA")
            with self.leases._transaction() as db:
                field = "worker" if phase == "implement" else "reviewer"
                generation = "generation" if phase == "implement" else "qa_generation"
                db.execute(
                    f"UPDATE r9_missions SET state=?,updated_ms=?,{field}=?,{generation}=? "
                    "WHERE mission_id=? AND state=?",
                    (assigned,moment,worker,receipt["generation"],
                     row["mission_id"],claiming))
            return {"schema": SCHEMA, "mission_id": row["mission_id"],
                    "phase": phase, "state": assigned,
                    "steward_key": receipt["steward_key"],
                    "source_scan_id": scan_id,
                    "worker": worker, "lease_generation": receipt["generation"],
                    "execution_authorized": False,
                    "dispatch_authorized": False, "merge_authorized": False}
        except BaseException:
            with self.leases._transaction() as db:
                db.execute("""UPDATE r9_missions
                    SET state='HELD_RECONCILE',updated_ms=? WHERE mission_id=?
                    AND state=?""",(moment,row["mission_id"],claiming))
            raise

    def handoff_to_qa(self, mission_id, capability, evidence_sha256, *,
                      now_ms=None):
        need(type(mission_id) is str and IDENT.fullmatch(mission_id) is not None,
             "MISSION_ID_INVALID")
        need(type(evidence_sha256) is str and
             DIGEST.fullmatch(evidence_sha256) is not None,
             "EVIDENCE_DIGEST_INVALID")
        moment = leases.epoch_ms(now_ms)
        with self.leases._transaction() as db:
            row = db.execute("SELECT * FROM r9_missions WHERE mission_id=?",
                             (mission_id,)).fetchone()
            need(row is not None and row["state"] == "ASSIGNED_IMPLEMENT",
                 "IMPLEMENTATION_NOT_ASSIGNED")
            active = self.leases._check_owned(db, capability, moment)
            need(active["repository_id"] == row["github_id"]
                 and active["source_sha"] == row["source_sha"]
                 and active["request_sha256"] == row["intake_digest"]
                 and active["generation"] == row["generation"]
                 and active["worker"] == row["worker"],
                 "IMPLEMENTER_LEASE_MISMATCH")
            db.execute("""UPDATE r9_missions SET state='HANDOFF_IN_PROGRESS',
                evidence_sha256=?,updated_ms=? WHERE mission_id=?""",
                (evidence_sha256,moment,mission_id))
        try:
            self.leases.release(capability, now_ms=moment)
        except BaseException:
            # Leave a held record to prevent unsupervised QA claim if the
            # worker was fenced between check and release.
            with self.leases._transaction() as db:
                db.execute("""UPDATE r9_missions SET state='HELD_RECONCILE'
                    WHERE mission_id=? AND state='HANDOFF_IN_PROGRESS'""",
                    (mission_id,))
            raise
        with self.leases._transaction() as db:
            db.execute("""UPDATE r9_missions SET state='QA_QUEUED',updated_ms=?
                WHERE mission_id=? AND state='HANDOFF_IN_PROGRESS'""",
                (moment,mission_id))
        return {"schema": SCHEMA, "mission_id": mission_id,
                "state": "QA_QUEUED", "evidence_sha256": evidence_sha256,
                "evidence_authenticated": False,
                "independent_checks_performed": False,
                "dispatch_authorized": False, "merge_authorized": False}

    def qa_hold(self, mission_id, capability, *, now_ms=None):
        moment = leases.epoch_ms(now_ms)
        with self.leases._transaction() as db:
            row = db.execute("SELECT * FROM r9_missions WHERE mission_id=?",
                             (mission_id,)).fetchone()
            need(row is not None and row["state"] == "ASSIGNED_QA",
                 "QA_NOT_ASSIGNED")
            active = self.leases._check_owned(db, capability, moment)
            need(active["repository_id"] == row["github_id"]
                 and active["generation"] == row["qa_generation"]
                 and active["worker"] == row["reviewer"]
                 and active["worker"] != row["worker"],
                 "QA_LEASE_IDENTITY_MISMATCH")
            db.execute("""UPDATE r9_missions SET state='QA_HELD',updated_ms=?
                WHERE mission_id=?""",(moment,mission_id))
        self.leases.release(capability, now_ms=moment)
        return {"schema": SCHEMA, "mission_id": mission_id,
                "state": "QA_HELD_MANUAL_EVIDENCE_REVIEW_REQUIRED",
                "review_approved": False, "merge_authorized": False,
                "verified_complete": False}

    def status(self, *, now=None):
        visible, scan = _present(self.registry, _now(now))
        with self.leases._connection() as db:
            rows = db.execute("""SELECT mission_id,github_id,repository,
                kind,state,worker,reviewer,source_sha FROM r9_missions
                ORDER BY created_ms,mission_id""").fetchall()
        redacted = [
            {"mission_id": r["mission_id"], "github_id": r["github_id"],
             "repository": r["repository"], "kind": r["kind"],
             "state": r["state"], "worker": r["worker"],
             "reviewer": r["reviewer"], "source_sha": r["source_sha"]}
            for r in rows if visible.get(r["github_id"]) == r["repository"]
        ]
        return {"schema": SCHEMA, "scope": "public_only",
                "source_scan_id": scan, "missions": redacted,
                "actual_jobs_dispatched": 0, "merge_authorized": False,
                "verified_complete": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--steward-db",type=Path,
                   default=Path("~/.agentora/fleet-stewards.sqlite3"))
    p.add_argument("--lease-db",type=Path,
                   default=Path("~/.agentora/fleet-leases.sqlite3"))
    p.add_argument("--capacity",type=int,default=2)
    sub = p.add_subparsers(dest="action",required=True)
    enqueue = sub.add_parser("enqueue")
    enqueue.add_argument("--mission-id",required=True)
    enqueue.add_argument("--kind",required=True,choices=sorted(KINDS))
    enqueue.add_argument("--intake",type=Path,required=True)
    enqueue.add_argument("--confirm",required=True)
    for action in ("plan","qa-plan","status"):
        sub.add_parser(action)
    for action in ("claim","qa-claim"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--intake",type=Path,required=True)
        cmd.add_argument("--worker",required=True)
        cmd.add_argument("--lease-file",type=Path,required=True)
        cmd.add_argument("--ttl",type=int,default=300)
    handoff = sub.add_parser("handoff")
    handoff.add_argument("--mission-id",required=True)
    handoff.add_argument("--lease-file",type=Path,required=True)
    handoff.add_argument("--evidence-sha256",required=True)
    qa = sub.add_parser("qa-hold")
    qa.add_argument("--mission-id",required=True)
    qa.add_argument("--lease-file",type=Path,required=True)
    a=p.parse_args(argv)
    try:
        control=MissionControl(StewardRegistry(a.steward_db.expanduser()),
                               leases.LeaseLedger(a.lease_db.expanduser()),
                               capacity=a.capacity)
        if a.action=="enqueue":
            result=control.enqueue(a.mission_id,a.kind,
                leases.load_intake(a.intake.expanduser()),confirmation=a.confirm)
        elif a.action in ("plan","qa-plan"):
            result=control.plan(phase="qa" if a.action=="qa-plan" else "implement")
        elif a.action in ("claim","qa-claim"):
            result=control.claim_next(
                leases.load_intake(a.intake.expanduser()),a.worker,a.lease_file,
                ttl=a.ttl, phase="qa" if a.action=="qa-claim" else "implement")
        elif a.action=="handoff":
            result=control.handoff_to_qa(a.mission_id,
                leases.load_capability(a.lease_file.expanduser()),
                a.evidence_sha256)
        elif a.action=="qa-hold":
            result=control.qa_hold(a.mission_id,
                leases.load_capability(a.lease_file.expanduser()))
        else:
            result=control.status()
        print(json.dumps(result,indent=2))
        return 0
    except (MissionHeld,leases.LeaseHeld,stewardship.HandoffHeld,
            StewardHeld,sqlite3.IntegrityError,OSError,ValueError) as exc:
        print("FLEET_R9_HELD " + str(exc),file=sys.stderr)
        return 3


if __name__=="__main__":
    raise SystemExit(main())
