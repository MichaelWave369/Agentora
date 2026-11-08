"""R10: exact GitHub trace → R9 mission evidence → separate QA worker."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r10_mission_evidence as e10
import fleet_r10_r9_r5_bridge as dispatch
import fleet_r9_mission_control as r9
import fleet_r5_guarded_dispatch as r5
import fleet_r04_leases as leases
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 8, 18, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
SHA = "a" * 40
RUN = 99887766


def observations():
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": 54,
        "observed_at": (NOW - timedelta(minutes=1)).isoformat(),
        "public_repo_count": 1,
        "repositories": [{"github_id": r5.pilot.REPOSITORY_ID,
            "full_name": r5.pilot.REPOSITORY, "archived": False,
            "source_only": True, "verified_complete": False}],
        "recent_events": [], "source_only": True,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def intake():
    return {"schema": leases.INTAKE_SCHEMA,
        "state": "HELD_FOR_OPERATOR_REVIEW", "owner": leases.OWNER,
        "repository": r5.pilot.REPOSITORY,
        "repository_id": r5.pilot.REPOSITORY_ID, "default_branch": "main",
        "source_sha": SHA, "request_sha256": "b" * 64,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN", "evidence_receipt": None}]}


class FakeGitHub:
    def __call__(self, path, token):
        if path == r5.WORKFLOW_ENDPOINT:
            return {"id": 123, "path": r5.WORKFLOW_PATH, "state": "active"}
        if path == "/repos/MichaelWave369/PhiMadaPrime":
            return {"id": r5.pilot.REPOSITORY_ID,
                    "full_name": r5.pilot.REPOSITORY,
                    "owner": {"login": "MichaelWave369"},
                    "private": False, "archived": False, "default_branch": "main"}
        if path == "/repos/MichaelWave369/PhiMadaPrime/branches/main":
            return {"name": "main", "commit": {"sha": SHA}}
        raise AssertionError("wrong fixed GET endpoint: " + path)


class EvidenceBridgeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.registry = StewardRegistry(root / "stewards.db")
        self.ledger = leases.LeaseLedger(root / "leases.db")
        self.registry.ingest(observations(), now=NOW)
        self.control = r9.MissionControl(self.registry, self.ledger)
        self.source = intake()
        self.mission = "phimada-fixed-trace"
        self.control.enqueue(self.mission, r9.KIND_TEST, self.source,
                             confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        self.path = root / "private" / "worker.lease"
        self.control.claim_next(self.source, "worker1", self.path,
                                ttl=1800, now=NOW, now_ms=MS)
        self.cap = leases.load_capability(self.path)
        self.request_id = dispatch._request_id(self.mission)
        self.posts = []

    def dispatch(self, post_status=204):
        def submit(token, sha):
            self.posts.append((token, sha))
            return post_status
        return dispatch.submit(self.control, self.mission,
            self.source, self.cap, execute=True, confirmation=dispatch.CONFIRM,
            token="scoped-actions-token", get=FakeGitHub(), post=submit,
            now=NOW, clock_ms=lambda: MS)

    def receipt(self, **changes):
        return {
            "state": "SANDBOXED_CHECKS_CORRELATED_WITH_LOCAL_LEASE",
            "dispatch_request_id": self.request_id,
            "dispatch_trace_present": True,
            "dispatch_origin_authenticated": False,
            "workflow_run_id": RUN,
            "repository_id": r5.pilot.REPOSITORY_ID,
            "source_sha": SHA, "lease_generation": self.cap["generation"],
            "lease_worker": "worker1",
            "lease_attested_by_github_runner": False,
            "product_verified": False, "verified_complete": False,
            "merge_authorized": False,
            "github_artifact_sha256": "c" * 64,
            "github_artifact_id": 2468,
            **changes,
        }

    def correlate(self, proof=None, **kwargs):
        with patch.object(e10.r4, "correlate", return_value=(
                self.receipt() if proof is None else proof)) as verifier:
            out = e10.correlate(self.control, self.mission,
                self.source, self.cap, RUN, b"downloaded-github-zip",
                confirmation=kwargs.pop("confirmation", e10.CORRELATE_CONFIRM),
                now=NOW + timedelta(minutes=2), clock_ms=MS+120000,
                **kwargs)
        return out, verifier

    def test_correlated_run_is_durable_but_not_qa_or_product_success(self):
        self.dispatch()
        out, verifier = self.correlate()
        self.assertEqual(out["state"], e10.RECORDED)
        self.assertEqual(out["workflow_run_id"], RUN)
        self.assertEqual(out["request_id"], self.request_id)
        self.assertTrue(out["github_artifact_correlated"])
        self.assertFalse(out["independent_qa_complete"])
        self.assertFalse(out["merge_authorized"])
        self.assertFalse(out["product_verified"])
        self.assertEqual(verifier.call_count, 1)
        with self.ledger._connection() as db:
            link = dict(db.execute("SELECT * FROM r10_evidence_links").fetchone())
            mission = db.execute("SELECT state FROM r9_missions "
                                 "WHERE mission_id=?", (self.mission,)).fetchone()
        self.assertEqual(link["request_id"], self.request_id)
        self.assertEqual(link["workflow_run_id"], RUN)
        self.assertEqual(link["github_artifact_sha256"], "c" * 64)
        self.assertEqual(link["state"], e10.RECORDED)
        self.assertEqual(mission["state"], "ASSIGNED_IMPLEMENT")
        for secret in ("scoped-actions-token", self.cap["token"]):
            self.assertNotIn(secret, json.dumps(out))
            self.assertNotIn(secret, json.dumps(link))

    def test_requires_r10_and_r5_accepted_journals_before_github_reads(self):
        with patch.object(e10.r4, "correlate") as verifier:
            with self.assertRaisesRegex(e10.EvidenceHeld, "JOURNALS"):
                e10.correlate(self.control, self.mission,
                    self.source, self.cap, RUN, b"archive",
                    confirmation=e10.CORRELATE_CONFIRM,
                    now=NOW, clock_ms=MS)
            verifier.assert_not_called()
        self.dispatch(post_status=403)
        with self.assertRaisesRegex(e10.EvidenceHeld, "NOT_ACCEPTED"):
            self.correlate()
        with self.ledger._connection() as db:
            tables = db.execute("SELECT name FROM sqlite_master "
                "WHERE name='r10_evidence_links'").fetchall()
        self.assertFalse(tables)

    def test_run_marker_must_match_exact_local_request_and_source(self):
        self.dispatch()
        bad = [
            {"dispatch_request_id": "other-mission"},
            {"dispatch_request_id": None, "dispatch_trace_present": False},
            {"dispatch_origin_authenticated": True},
            {"workflow_run_id": RUN+1},
            {"source_sha": "f"*40},
            {"github_artifact_id": 0},
            {"github_artifact_sha256": "bad"},
            {"merge_authorized": True},
            {"product_verified": True},
        ]
        for changed in bad:
            with self.subTest(change=changed):
                with self.assertRaises(e10.EvidenceHeld):
                    self.correlate(self.receipt(**changed))
        with self.ledger._connection() as db:
            self.assertFalse(db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE name='r10_evidence_links'").fetchall())

    def test_exact_run_cannot_be_linked_twice(self):
        self.dispatch()
        self.correlate()
        with self.assertRaisesRegex(e10.EvidenceHeld, "ALREADY_CORRELATED"):
            self.correlate()
        with self.ledger._connection() as db:
            count = db.execute("SELECT COUNT(*) FROM r10_evidence_links").fetchone()[0]
        self.assertEqual(count, 1)

    def test_qa_handoff_queues_distinct_worker_and_never_approves(self):
        self.dispatch()
        self.correlate()
        with self.assertRaisesRegex(e10.EvidenceHeld, "OPERATOR_QA_HANDOFF"):
            e10.handoff(self.control, self.mission, self.cap,
                         confirmation="yes", now_ms=MS+180000)
        out = e10.handoff(self.control, self.mission, self.cap,
                          confirmation=e10.HANDOFF_CONFIRM, now_ms=MS+180000)
        self.assertEqual(out["state"], "QA_QUEUED_FOR_DIFFERENT_WORKER")
        self.assertFalse(out["independent_qa_complete"])
        self.assertFalse(out["review_approved"])
        self.assertFalse(out["verified_complete"])
        with self.ledger._connection() as db:
            mission = db.execute("SELECT state,evidence_sha256 FROM r9_missions "
                                 "WHERE mission_id=?", (self.mission,)).fetchone()
            link = db.execute("SELECT state FROM r10_evidence_links").fetchone()
        self.assertEqual(mission["state"], "QA_QUEUED")
        self.assertEqual(mission["evidence_sha256"], "c" * 64)
        self.assertEqual(link["state"], "QA_QUEUED")
        with self.assertRaisesRegex(r9.MissionHeld, "QA_MUST_BE_SEPARATE_WORKER"):
            self.control.claim_next(self.source, "worker1",
                self.path.parent / "bad.lease", phase="qa",
                now=NOW, now_ms=MS+200000)
        candidate = self.control.claim_next(self.source, "reviewer2",
            self.path.parent / "qa.lease", phase="qa",
            now=NOW, now_ms=MS+200000)
        self.assertEqual(candidate["state"], "ASSIGNED_QA")
        self.assertFalse(candidate["merge_authorized"])

    def test_crash_between_r9_qa_handoff_and_link_update_can_reconcile(self):
        self.dispatch()
        self.correlate()
        e10.handoff(self.control, self.mission, self.cap,
                    confirmation=e10.HANDOFF_CONFIRM, now_ms=MS+150000)
        with self.ledger._transaction() as db:
            db.execute("UPDATE r10_evidence_links SET state=?",
                       (e10.RECORDED,))
        recovered = e10.handoff(self.control, self.mission, self.cap,
                         confirmation=e10.HANDOFF_CONFIRM, now_ms=MS+151000)
        self.assertEqual(recovered["state"], "QA_QUEUED_FOR_DIFFERENT_WORKER")
        with self.ledger._connection() as db:
            self.assertEqual(db.execute("SELECT state FROM r10_evidence_links"
                ).fetchone()["state"], "QA_QUEUED")

    def test_no_evidence_or_stale_worker_cannot_handoff(self):
        with self.assertRaisesRegex(e10.EvidenceHeld, "NO_CORRELATED_EVIDENCE"):
            e10.handoff(self.control, self.mission, self.cap,
                         confirmation=e10.HANDOFF_CONFIRM, now_ms=MS)
        self.dispatch()
        self.correlate()
        forged = {**self.cap, "token": "fake"}
        with self.assertRaisesRegex(e10.EvidenceHeld, "QA_IMPLEMENTER_LEASE"):
            e10.handoff(self.control, self.mission, forged,
                         confirmation=e10.HANDOFF_CONFIRM, now_ms=MS+150000)
        with self.ledger._connection() as db:
            mission = db.execute("SELECT state FROM r9_missions").fetchone()
        self.assertEqual(mission["state"], "ASSIGNED_IMPLEMENT")

    def test_missing_operator_correlation_consent_and_expired_lease_hold(self):
        self.dispatch()
        with self.assertRaisesRegex(e10.EvidenceHeld, "EXPLICIT_EVIDENCE_REVIEW"):
            self.correlate(confirmation="yes")
        with patch.object(e10.r4, "correlate") as verifier:
            with self.assertRaisesRegex(dispatch.BridgeHeld, "LEASE_EXPIRED"):
                e10.correlate(self.control, self.mission,
                    self.source, self.cap, RUN, b"archive",
                    confirmation=e10.CORRELATE_CONFIRM,
                    now=NOW+timedelta(hours=1), clock_ms=MS+3600000)
            verifier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
