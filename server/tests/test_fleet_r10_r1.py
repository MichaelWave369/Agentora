"""Regression tests for the existing R9 ledger and R1 handoff boundaries."""
from datetime import timedelta
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_autonomous_turn_r1 import (
    NOW, SOURCE, MERGE, SyntheticGitHub, task, value_for, isolated,
)
from test_fleet_r9_mission_control import observations
import autonomous_turn_github as gh
import autonomous_turn_contract as contract
import fleet_r10_r1 as bridge
import fleet_r9_mission_control as r9
from fleet_r04_leases import LeaseLedger


class TurnAPI(SyntheticGitHub):
    def __init__(self, spec):
        super().__init__(spec)
        self.read = []
        self.run.update(status="waiting")
        self.jobs = [self.job("plan", 1), self.job("owner-authorization", 2, "waiting")]
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, "w") as archive:
            archive.writestr("task.json", contract.canonical(spec))
        self.archive = memory.getvalue()

    @staticmethod
    def job(name, number, status="completed"):
        return {"name": name, "id": number, "run_id": 11, "run_attempt": 1,
                "head_sha": SOURCE, "status": status, "completed_at": NOW.isoformat(),
                "conclusion": "success" if status == "completed" else None}

    def __call__(self, path, payload=None, method=None):
        self.read.append(path)
        if path == bridge.RUNS + "/11/jobs?per_page=20":
            return {"total_count": len(self.jobs), "jobs": self.jobs}
        if path == bridge.RUNS + "/11/artifacts?per_page=20":
            return {"total_count": 1, "artifacts": [{"id": 42, "expired": False,
                "name": "autonomous-task-11", "size_in_bytes": len(self.archive),
                "digest": "sha256:" + contract.digest(self.archive)}]}
        return super().__call__(path, payload, method)


class TurnBridgeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.spec, self.now = task(), NOW
        self.api = TurnAPI(self.spec)
        self.control = r9.MissionControl(r9.StewardRegistry(root/"stewards.db"),
                                         LeaseLedger(root/"leases.db"))
        self.lane = bridge.TurnLane(self.control, self.api, clock=lambda: self.now)
        self.obs = observations([(contract.REPO_ID, "Agentora", False)])
        self.obs["observed_at"] = self.now.isoformat()
        self.obs["recent_events"] = [
            {"id": 42, "github_id": contract.REPO_ID, "full_name": contract.REPO,
             "event_type": "first_observed", "observed_at": self.now.isoformat()}]
        self.control.registry.ingest(self.obs, now=self.now)
        self.mid = f"r10-e42-gh{contract.REPO_ID}"

    def enqueue(self):
        return self.lane.enqueue(self.spec, self.obs, 42, bridge.CONFIRM)

    def row(self):
        return self.lane.row(self.mid)

    def dispatch(self):
        self.api.run["event"] = "workflow_dispatch"
        self.lane.dispatch(self.row(), lambda: self.api.owner, lambda payload: {
            "workflow_run_id": 11, "html_url": f"{bridge.REPO_URL}/actions/runs/11"})

    def test_real_r9_database_deduplicates_event_and_preserves_public_scope(self):
        self.assertTrue(self.enqueue()["head_revalidated"])
        self.assertEqual(self.enqueue()["state"], "EVENT_ALREADY_QUEUED_NO_NEW_MISSION")
        self.lane = bridge.TurnLane(self.control, self.api, clock=lambda: self.now)
        snapshot = self.lane.snapshot()
        self.assertEqual(len(snapshot["turns"]), 1)
        self.assertEqual(snapshot["turns"][0]["task_sha256"], contract.task_digest(self.spec))
        self.assertNotIn(self.spec["human_scope"], json.dumps(snapshot))
        with self.assertRaisesRegex(r9.MissionHeld, "R1_MISSION_REQUIRES_R1"):
            self.control.claim_next(bridge.held_intake(self.spec), "local", Path("not-created"),
                                    now=self.now)

    def test_source_drift_and_code_are_refused_before_dispatch(self):
        self.api.main = "e" * 40
        with self.assertRaisesRegex(contract.Held, "SOURCE_DRIFT"):
            self.enqueue()
        self.api.main = SOURCE
        with self.assertRaisesRegex(r9.MissionHeld, "R1_TASK_OUT_OF_SCOPE"):
            self.lane.enqueue(task("code"), self.obs, 42, bridge.CONFIRM)
        self.assertEqual(self.lane.snapshot()["turns"], [])

    def test_unknown_write_is_fenced_and_cannot_be_retried(self):
        self.enqueue()
        submitted = []
        def submit(payload):
            submitted.append(payload)
            self.assertEqual(self.row()["state"], "SUBMISSION_UNCERTAIN")
            raise contract.Held("GITHUB_DISPATCH_RESPONSE_UNAVAILABLE")
        stale = self.row()
        self.lane.dispatch(stale, lambda: self.api.owner, submit)
        self.assertEqual(self.row()["state"], "SUBMISSION_UNCERTAIN")
        with self.assertRaises(contract.Held):
            self.lane.dispatch(stale, lambda: self.api.owner, submit)
        with self.assertRaisesRegex(contract.Held, "UNSUBMITTED"):
            self.lane.retry_preflight(self.row())
        self.assertEqual(len(submitted), 1)

    def test_attach_requires_original_digest_and_approval_is_a_distinct_state(self):
        self.enqueue()
        self.lane.reserve(self.row(), "issues")
        with self.assertRaisesRegex(contract.Held, "ARTIFACT_DIGEST"):
            self.lane.attach(self.row(), 11, lambda _id: b"x" * len(self.api.archive))
        self.lane.attach(self.row(), 11, lambda _id: self.api.archive)
        self.lane.reconcile(self.row())
        self.assertEqual(self.row()["state"], "OWNER_REVIEW")
        self.api.jobs[-1] = self.api.job("owner-authorization", 2)
        self.api.jobs.append(self.api.job("attempt-0 / worker", 3, "in_progress"))
        self.lane.reconcile(self.row())
        self.assertEqual(self.row()["state"], "RUNNING")
        self.assertEqual(self.row()["active_job"], "attempt-0 / worker")

    def test_reconciles_published_ci_and_independent_merge_without_writes(self):
        self.enqueue()
        self.dispatch()
        self.api.jobs = [self.api.job(name, i + 1) for i, name in
                         enumerate(sorted(bridge.JOB_NAMES - {"merge-gate"}))]
        value = value_for(self.spec)
        sandbox = isolated(self.spec, value)
        publication = gh.publish(self.api, self.spec, value, sandbox, 11, SOURCE)
        self.api.pr["user"].update(id=bridge.PUBLISHER_ID, type="Bot")
        self.api.check_mutation = lambda checks: checks[:3]
        self.lane.reconcile(self.row())
        self.assertEqual(self.row()["state"], "CI_PENDING")
        self.api.check_mutation = lambda checks: checks
        self.lane.reconcile(self.row())
        self.assertEqual((self.row()["state"], self.row()["ci_status"]), ("CI_PASSED", "PASSED"))
        receipt = gh.finish(self.api, self.spec, publication, value, sandbox, 11, SOURCE)
        self.assertEqual(receipt["merge_commit_sha"], MERGE)
        self.api.pr["merged_by"] = {"id": 41898282}
        self.api.jobs.append(self.api.job("merge-gate", 6))
        self.api.run.update(status="completed", conclusion="success")
        self.api.calls.clear()
        self.lane.reconcile(self.row())
        self.assertEqual(self.row()["state"], "MERGED")
        self.assertEqual(self.row()["merge_sha"], MERGE)
        self.assertEqual(json.loads(self.row()["ci_runs"]), [100, 110])
        self.assertTrue(all(payload is None for _, payload, _ in self.api.calls))

    def test_missing_capability_holds_without_write_and_can_retry_preflight(self):
        self.enqueue()
        self.lane.dispatch(self.row(), lambda: {"id": 1, "type": "User"},
                           lambda _: self.fail("must not dispatch"))
        self.assertEqual(self.row()["state"], "HELD")
        self.assertIsNone(self.row()["origin"])
        self.lane.retry_preflight(self.row())
        self.assertEqual(self.row()["state"], "REQUESTED")
        self.now = NOW + timedelta(hours=5)
        self.lane.dispatch(self.row(), lambda: self.api.owner,
                           lambda _: self.fail("must not dispatch expired task"))
        self.assertEqual(self.row()["reason"], "AUTHORIZATION_EXPIRED_OR_CLOCK")
