"""R9 mission-control integration: fair bounded leases and separate QA roles."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r9_mission_control as r9
import fleet_r04_leases as leases
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
PILOT_ID = r9.pilot.REPOSITORY_ID
AUDIT_ID = 21
OTHER_ID = 22


def observations(names=None, *, scan=1):
    names = [(AUDIT_ID, "BTM", False), (OTHER_ID, "PhiOS", False),
             (PILOT_ID, "PhiMadaPrime", False)] if names is None else names
    rows = [
        {"github_id": rid, "full_name": "MichaelWave369/" + name,
         "archived": archived, "source_only": True, "verified_complete": False}
        for rid,name,archived in names
    ]
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": scan,
        "observed_at": (NOW - timedelta(minutes=2)).isoformat(),
        "public_repo_count": len(rows), "repositories": rows,
        "recent_events": [], "source_only": True,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def intake(repo="BTM", repo_id=AUDIT_ID, sha="a"*40):
    return {
        "schema": leases.INTAKE_SCHEMA,
        "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER, "repository": "MichaelWave369/" + repo,
        "repository_id": repo_id, "source_sha": sha,
        "request_sha256": "b"*64,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False,
        "independent_checks_run": 0,
        "checks": [{"check_id":"automated_tests",
                    "verification_state":"NOT_RUN","evidence_receipt":None}],
    }


class R9Tests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.registry = StewardRegistry(self.root / "stewards.sqlite3")
        self.registry.ingest(observations(), now=NOW)
        self.lease = leases.LeaseLedger(self.root / "leases.sqlite3")
        self.control = r9.MissionControl(self.registry, self.lease, capacity=2)
        self.btm = intake()
        self.phios = intake("PhiOS", OTHER_ID, "c"*40)
        self.phimada = intake("PhiMadaPrime", PILOT_ID, "d"*40)

    def enqueue(self, mid="mission1", kind=r9.KIND_AUDIT, info=None):
        return self.control.enqueue(mid, kind, info or self.btm,
                                    confirmation=r9.CONFIRM, now=NOW, now_ms=MS)

    def claim(self, info=None, worker="implementer1", name="implementer1.lease",
              phase="implement", now_ms=MS):
        return self.control.claim_next(
            info or self.btm,worker,self.root / "private" / name,
            now=NOW, now_ms=now_ms, phase=phase, ttl=300)

    def capability(self, name="implementer1.lease"):
        return leases.load_capability(self.root / "private" / name)

    def test_enqueued_steward_is_stable_and_zero_authority(self):
        item = self.enqueue()
        self.assertEqual(item["state"],"QUEUED_LOCAL_ONLY")
        self.assertEqual(item["steward_key"],"steward-gh-21")
        self.assertFalse(item["execution_authorized"])
        self.assertFalse(item["dispatch_authorized"])
        self.assertFalse(item["merge_authorized"])
        result = self.control.plan(now=NOW)
        self.assertEqual([i["mission_id"] for i in result["missions"]],["mission1"])
        self.assertEqual(result["slots_remaining"],2)
        self.assertEqual(self.lease.status(now_ms=MS)["active_reservations"],0)

    def test_live_lease_issuance_and_no_secrets_in_receipt_or_public_status(self):
        self.enqueue()
        result = self.claim()
        self.assertEqual(result["state"],"ASSIGNED_IMPLEMENT")
        self.assertEqual(result["lease_generation"],1)
        self.assertFalse(result["execution_authorized"])
        self.assertIn("token",self.capability())
        self.assertNotIn("token",json.dumps(result))
        self.assertEqual(self.lease.status(now_ms=MS)["active_reservations"],1)
        status=self.control.status(now=NOW)
        self.assertEqual(status["missions"][0]["state"],"ASSIGNED_IMPLEMENT")
        self.assertEqual(status["actual_jobs_dispatched"],0)
        self.assertNotIn(self.capability()["token"],json.dumps(status))
        self.assertNotIn("request_sha256",json.dumps(status))

    def test_capacity_and_fair_next_mission_selected(self):
        self.enqueue("btm",info=self.btm)
        self.enqueue("phios",info=self.phios)
        self.control.enqueue("phimada",r9.KIND_TEST,self.phimada,
                             confirmation=r9.CONFIRM,now=NOW,now_ms=MS)
        plan=self.control.plan(now=NOW)
        self.assertEqual([x["mission_id"] for x in plan["missions"]],
                         ["btm","phios"])
        with self.assertRaisesRegex(r9.MissionHeld,"NEXT_FAIR_MISSION"):
            self.claim(self.phimada,worker="worker3",name="three.lease")
        self.claim(self.btm,worker="worker1",name="one.lease")
        self.claim(self.phios,worker="worker2",name="two.lease")
        plan=self.control.plan(now=NOW)
        self.assertEqual(plan["missions"],[])
        self.assertEqual(plan["occupied_slots"],2)
        with self.assertRaisesRegex(r9.MissionHeld,"CAPACITY"):
            self.claim(self.phimada,worker="worker3",name="three.lease")

    def test_duplicate_id_or_second_repo_mission_is_held(self):
        self.enqueue()
        with self.assertRaisesRegex(r9.MissionHeld,"MISSION_ID_ALREADY"):
            self.enqueue()
        with self.assertRaisesRegex(r9.MissionHeld,"REPOSITORY_HAS_UNRESOLVED"):
            self.enqueue(mid="mission2")
        with self.lease._connection() as db:
            count=db.execute("SELECT COUNT(*) FROM r9_missions").fetchone()[0]
        self.assertEqual(count,1)

    def test_special_actions_are_fixed_to_public_phimada(self):
        for kind in (r9.KIND_TEST,r9.KIND_PROPOSAL):
            with self.subTest(kind=kind), self.assertRaisesRegex(
                    r9.MissionHeld,"SPECIAL_MISSION_FIXED"):
                self.enqueue(kind=kind)
        self.control.enqueue("pilot",r9.KIND_PROPOSAL,self.phimada,
                             confirmation=r9.CONFIRM,now=NOW,now_ms=MS)
        with self.assertRaisesRegex(r9.MissionHeld,"MISSION_KIND"):
            self.enqueue(mid="invalid",kind="DEPLOY_TO_PRODUCTION")
        with self.assertRaisesRegex(r9.MissionHeld,"OPERATOR_ENQUEUE"):
            self.control.enqueue("another",r9.KIND_AUDIT,self.btm,
                                 confirmation="yes",now=NOW,now_ms=MS)

    def test_handoff_releases_implementation_and_requires_different_qa_worker(self):
        self.enqueue()
        self.claim()
        evidence="e"*64
        handoff=self.control.handoff_to_qa(
            "mission1",self.capability(),evidence,now_ms=MS+100)
        self.assertEqual(handoff["state"],"QA_QUEUED")
        self.assertFalse(handoff["evidence_authenticated"])
        self.assertFalse(handoff["independent_checks_performed"])
        self.assertEqual(self.lease.status(now_ms=MS+101)["active_reservations"],0)
        qa_plan=self.control.plan(phase="qa",now=NOW)
        self.assertEqual(qa_plan["missions"][0]["mission_id"],"mission1")
        with self.assertRaisesRegex(r9.MissionHeld,"QA_MUST_BE_SEPARATE"):
            self.claim(worker="implementer1",name="qa-bad.lease",phase="qa")
        assigned=self.claim(worker="independentQA",name="qa.lease",phase="qa")
        self.assertEqual(assigned["state"],"ASSIGNED_QA")
        self.assertEqual(assigned["lease_generation"],2)
        self.assertEqual(self.lease.status(now_ms=MS+101)["active_reservations"],1)
        held=self.control.qa_hold("mission1",self.capability("qa.lease"),
                                  now_ms=MS+200)
        self.assertEqual(held["state"],"QA_HELD_MANUAL_EVIDENCE_REVIEW_REQUIRED")
        self.assertFalse(held["review_approved"])
        self.assertFalse(held["merge_authorized"])
        self.assertEqual(self.lease.status(now_ms=MS+201)["active_reservations"],0)

    def test_qa_claim_without_released_implementation_never_happens(self):
        self.enqueue()
        self.claim()
        with self.assertRaisesRegex(r9.MissionHeld,"NO_ELIGIBLE_MISSIONS"):
            self.claim(worker="independentQA",name="qa.lease",phase="qa")
        with self.assertRaisesRegex(r9.MissionHeld,"EVIDENCE_DIGEST"):
            self.control.handoff_to_qa("mission1",self.capability(),"bad",
                                       now_ms=MS+50)
        self.assertEqual(self.lease.status(now_ms=MS+50)["active_reservations"],1)

    def test_forged_or_stale_capability_cannot_handoff(self):
        self.enqueue()
        self.claim()
        forged={**self.capability(),"token":"wrong"}
        with self.assertRaisesRegex(leases.LeaseHeld,"LEASE_EXPIRED_OR_FENCED"):
            self.control.handoff_to_qa("mission1",forged,"e"*64,now_ms=MS+10)
        with self.lease._connection() as db:
            current=db.execute("SELECT state FROM r9_missions").fetchone()["state"]
        self.assertEqual(current,"ASSIGNED_IMPLEMENT")
        with self.assertRaisesRegex(leases.LeaseHeld,"LEASE_EXPIRED_OR_FENCED"):
            self.control.handoff_to_qa("mission1",self.capability(),"e"*64,
                                       now_ms=MS+400000)

    def test_qa_role_rejects_wrong_lease_or_wrong_worker(self):
        self.enqueue()
        self.claim()
        self.control.handoff_to_qa("mission1",self.capability(),"e"*64,
                                   now_ms=MS+50)
        self.claim(worker="independentQA",name="qa.lease",phase="qa")
        with self.assertRaises(leases.LeaseHeld):
            self.control.qa_hold("mission1",self.capability(),now_ms=MS+60)
        with self.lease._connection() as db:
            state=db.execute("SELECT state FROM r9_missions").fetchone()["state"]
        self.assertEqual(state,"ASSIGNED_QA")

    def test_archived_or_missing_visibility_never_releases_private_history(self):
        self.enqueue()
        self.registry.ingest(observations([
            (AUDIT_ID,"BTM",True),(OTHER_ID,"PhiOS",False),
            (PILOT_ID,"PhiMadaPrime",False)],scan=2),now=NOW)
        self.assertEqual(self.control.plan(now=NOW)["missions"],[])
        self.assertEqual(self.control.status(now=NOW)["missions"],[])
        with self.assertRaisesRegex(r9.MissionHeld,"NO_ELIGIBLE_MISSIONS"):
            self.claim()
        self.registry.ingest(observations([
            (OTHER_ID,"PhiOS",False),(PILOT_ID,"PhiMadaPrime",False)
        ],scan=3),now=NOW)
        self.assertNotIn("BTM",json.dumps(self.control.status(now=NOW)))

    def test_identity_rename_held(self):
        self.enqueue()
        self.registry.ingest(observations([
            (AUDIT_ID,"ChangedName",False),(OTHER_ID,"PhiOS",False),
            (PILOT_ID,"PhiMadaPrime",False)],scan=2),now=NOW)
        self.assertEqual(self.control.plan(now=NOW)["missions"],[])
        self.assertEqual(self.control.status(now=NOW)["missions"],[])

    def test_stale_source_fails_closed(self):
        self.enqueue()
        with self.assertRaisesRegex(r9.MissionHeld,"SOURCE_STALE"):
            self.control.plan(now=NOW+timedelta(days=3))

    def test_crash_like_reservation_file_write_failure_marks_manual_reconcile(self):
        self.enqueue()
        destination=self.root / "private" / "worker.lease"
        destination.parent.mkdir(mode=0o700)
        destination.write_text("old secret",encoding="utf-8")
        with self.assertRaisesRegex(r9.stewardship.HandoffHeld,"LEASE_FILE_EXISTS"):
            self.control.claim_next(self.btm,"worker1",destination,
                                    now=NOW,now_ms=MS)
        state=self.control.status(now=NOW)["missions"][0]["state"]
        self.assertEqual(state,"HELD_RECONCILE")
        self.assertEqual(self.lease.status(now_ms=MS)["active_reservations"],0)
        self.assertEqual(destination.read_text(),"old secret")

    def test_external_lease_contention_is_not_silently_retried(self):
        self.enqueue()
        external=self.lease.reserve(self.btm,"externalWorker",ttl_seconds=300,
                                    now_ms=MS)
        with self.assertRaisesRegex(leases.LeaseHeld,"REPO_ALREADY_RESERVED"):
            self.claim()
        self.assertEqual(self.control.status(now=NOW)["missions"][0]["state"],
                         "HELD_RECONCILE")
        self.assertEqual(self.lease.status(now_ms=MS)["active_reservations"],1)
        self.lease.release(external,now_ms=MS+1)

    def test_archive_held_requires_operator_and_no_active_lease(self):
        self.enqueue()
        external=self.lease.reserve(self.btm,"externalWorker",ttl_seconds=300,
                                    now_ms=MS)
        with self.assertRaises(leases.LeaseHeld):
            self.claim()
        with self.assertRaisesRegex(r9.MissionHeld,"ACTIVE_LEASE"):
            self.control.archive_held("mission1",confirmation=r9.ARCHIVE_CONFIRM,
                                      now_ms=MS+1)
        with self.assertRaisesRegex(r9.MissionHeld,"OPERATOR_ARCHIVE"):
            self.control.archive_held("mission1",confirmation="yes",
                                      now_ms=MS+1)
        self.lease.release(external,now_ms=MS+2)
        result=self.control.archive_held("mission1",
                                         confirmation=r9.ARCHIVE_CONFIRM,
                                         now_ms=MS+3)
        self.assertEqual(result["state"],"ARCHIVED_NOT_APPROVED")
        self.assertFalse(result["merge_authorized"])
        # A new, independently authorized mission may now be queued.
        later=self.enqueue("mission2")
        self.assertEqual(later["state"],"QUEUED_LOCAL_ONLY")

    def test_enqueue_and_plans_are_persistent_across_process_restarts(self):
        self.enqueue()
        later=r9.MissionControl(StewardRegistry(self.registry.path),
                                leases.LeaseLedger(self.lease.path),capacity=2)
        self.assertEqual(later.plan(now=NOW)["missions"][0]["mission_id"],
                         "mission1")
        later.claim_next(self.btm,"worker1",self.root/"private"/"worker1",
                         now=NOW,now_ms=MS)
        self.assertEqual(self.control.status(now=NOW)["missions"][0]["state"],
                         "ASSIGNED_IMPLEMENT")

    def observed(self, event_id=501, event_type="push_activity_observed",
                 scan=2, repo="BTM", repo_id=AUDIT_ID):
        data = observations(scan=scan)
        data["recent_events"] = [{
            "id": event_id, "github_id": repo_id,
            "full_name": "MichaelWave369/" + repo,
            "event_type": event_type,
            "observed_at": (NOW - timedelta(minutes=1)).isoformat()}]
        return data

    def test_r10_ingested_reponerve_event_enters_original_r9_queue_once(self):
        source = self.observed()
        self.registry.ingest(source, now=NOW)
        queued = self.control.enqueue_observed(
            source, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        self.assertEqual(queued["state"], "QUEUED_LOCAL_ONLY")
        self.assertEqual(queued["source_event_id"], 501)
        self.assertEqual(queued["source_scan_id"], 2)
        self.assertEqual(queued["mission_id"], "r10-e501-gh21")
        self.assertFalse(queued["dispatch_authorized"])
        self.assertFalse(queued["merge_authorized"])
        self.assertFalse(queued["head_revalidated"])
        self.assertEqual(
            self.control.plan(now=NOW)["missions"][0]["mission_id"],
            "r10-e501-gh21")
        later = r9.MissionControl(self.registry, leases.LeaseLedger(self.lease.path))
        replay = later.enqueue_observed(
            source, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS+1)
        self.assertEqual(replay["state"], "EVENT_ALREADY_QUEUED_NO_NEW_MISSION")
        with self.lease._connection() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM r9_missions").fetchone()[0], 1)
            link = db.execute("SELECT * FROM r10_event_links").fetchone()
            self.assertEqual(link["source_event_id"], 501)
            self.assertEqual(link["source_scan_id"], 2)
            self.assertEqual(link["event_type"], "push_activity_observed")

    def test_r10_refuses_uningested_or_tampered_observation_and_wrong_intake(self):
        source = self.observed()
        with self.assertRaisesRegex(r9.MissionHeld, "NOT_CURRENT_INGESTED"):
            self.control.enqueue_observed(
                source, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        self.registry.ingest(source, now=NOW)
        tampered = {**source, "observed_at": NOW.isoformat()}
        with self.assertRaisesRegex(r9.MissionHeld, "NOT_CURRENT_INGESTED"):
            self.control.enqueue_observed(
                tampered, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        with self.assertRaisesRegex(r9.MissionHeld, "IDENTITY_MISMATCH"):
            self.control.enqueue_observed(
                source, 501, self.phios, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        with self.assertRaisesRegex(r9.MissionHeld, "SOURCE_EVENT_NOT_IN"):
            self.control.enqueue_observed(
                source, 502, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        with self.assertRaisesRegex(r9.MissionHeld, "OPERATOR_ENQUEUE"):
            self.control.enqueue_observed(
                source, 501, self.btm, confirmation="yes", now=NOW, now_ms=MS)
        with self.lease._connection() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM r9_missions").fetchone()[0], 0)

    def test_r10_replay_different_source_intake_holds_after_scan_advances(self):
        first = self.observed()
        self.registry.ingest(first, now=NOW)
        self.control.enqueue_observed(
            first, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        second = self.observed(scan=3)
        second["observed_at"] = NOW.isoformat()
        self.registry.ingest(second, now=NOW)
        with self.assertRaisesRegex(r9.MissionHeld, "NOT_CURRENT_INGESTED"):
            self.control.enqueue_observed(
                first, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS+1)
        altered_intake = {**self.btm, "source_sha": "c" * 40}
        with self.assertRaisesRegex(r9.MissionHeld, "EVENT_REPLAY_CONFLICT"):
            self.control.enqueue_observed(
                second, 501, altered_intake,
                confirmation=r9.CONFIRM, now=NOW, now_ms=MS+1)
        with self.lease._connection() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM r9_missions").fetchone()[0], 1)

    def test_r10_rejects_non_candidate_events_and_authority_forgeries(self):
        rename = self.observed(event_type="renamed")
        self.registry.ingest(rename, now=NOW)
        with self.assertRaisesRegex(r9.MissionHeld, "NOT_REVIEW_CANDIDATE"):
            self.control.enqueue_observed(
                rename, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        forged = {**rename, "dispatch_authorized": True}
        with self.assertRaisesRegex(Exception, "AUTHORITY_FORGERY"):
            self.control.enqueue_observed(
                forged, 501, self.btm, confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        with self.lease._connection() as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM r9_missions").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
