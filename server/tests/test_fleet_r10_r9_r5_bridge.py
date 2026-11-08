"""R10 bridge: only an assigned, fenced R9 fixed-test mission can use R5."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r10_r9_r5_bridge as bridge
import fleet_r9_mission_control as r9
import fleet_r5_guarded_dispatch as r5
import fleet_r04_leases as leases
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 8, 16, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
SHA = "a" * 40
OTHER = "b" * 40


def observations(archived=False):
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": 50,
        "observed_at": (NOW - timedelta(minutes=1)).isoformat(),
        "public_repo_count": 1,
        "repositories": [{"github_id": r5.pilot.REPOSITORY_ID,
            "full_name": r5.pilot.REPOSITORY, "archived": archived,
            "source_only": True, "verified_complete": False}],
        "recent_events": [], "source_only": True,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def intake():
    return {"schema": leases.INTAKE_SCHEMA,
        "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER, "repository": r5.pilot.REPOSITORY,
        "repository_id": r5.pilot.REPOSITORY_ID, "default_branch": "main",
        "source_sha": SHA, "request_sha256": "c" * 64,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN", "evidence_receipt": None}]}


class FakeGitHub:
    def __init__(self, *, sha=SHA, workflow="active"):
        self.sha = sha
        self.workflow = workflow
        self.calls = []

    def __call__(self, path, token):
        self.calls.append(path)
        if path == r5.WORKFLOW_ENDPOINT:
            return {"id": 123, "path": r5.WORKFLOW_PATH,
                    "state": self.workflow}
        if path == "/repos/MichaelWave369/PhiMadaPrime":
            return {"id": r5.pilot.REPOSITORY_ID,
                    "full_name": r5.pilot.REPOSITORY,
                    "owner": {"login": "MichaelWave369"},
                    "private": False, "archived": False,
                    "default_branch": "main"}
        if path == "/repos/MichaelWave369/PhiMadaPrime/branches/main":
            return {"name": "main", "commit": {"sha": self.sha}}
        raise AssertionError("Unexpected GitHub API path " + path)


class BridgeTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.registry = StewardRegistry(root / "stewards.sqlite3")
        self.leases = leases.LeaseLedger(root / "leases.sqlite3")
        self.registry.ingest(observations(), now=NOW)
        self.control = r9.MissionControl(self.registry, self.leases)
        self.intake = intake()
        self.control.enqueue("phimada-fixed-1", r9.KIND_TEST, self.intake,
                             confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        self.path = root / "private" / "worker.lease"
        claim = self.control.claim_next(self.intake, "worker1", self.path,
                           now=NOW, now_ms=MS, ttl=300)
        self.assertEqual(claim["state"], "ASSIGNED_IMPLEMENT")
        self.capability = leases.load_capability(self.path)
        self.sent = []
        self.gh = FakeGitHub()

    def post(self, token, sha):
        self.sent.append((token, sha))
        return 204

    def run_bridge(self, *, execute=False, confirmation=None,
                   token=None, get=None, post=None, **overrides):
        return bridge.submit(self.control, "phimada-fixed-1",
            overrides.pop("intake", self.intake),
            overrides.pop("capability", self.capability),
            execute=execute, confirmation=confirmation, token=token,
            get=get or self.gh, post=post or self.post,
            now=NOW, clock_ms=lambda: MS)

    def test_preview_does_not_write_intent_or_issue_post(self):
        result = self.run_bridge()
        self.assertEqual(result["state"], "DRY_RUN_READY_NO_DISPATCH")
        self.assertFalse(result["dispatch_authorized"])
        self.assertFalse(result["merge_authorized"])
        self.assertIsNone(result["run_id"])
        self.assertEqual(self.sent, [])
        with self.leases._connection() as db:
            tables = [x["name"] for x in db.execute(
                "SELECT name FROM sqlite_master WHERE name IN "
                "('r10_r5_dispatch_links','r5_fixed_dispatches')")]
        self.assertEqual(tables, [])

    def test_one_real_request_is_bound_to_existing_r9_and_r5_ledgers(self):
        self.run_bridge()  # preview first is harmless
        result = self.run_bridge(execute=True, confirmation=bridge.CONFIRM,
                                 token="private-github-token")
        self.assertEqual(result["state"],
                         "REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED")
        self.assertEqual(result["mission_id"], "phimada-fixed-1")
        self.assertTrue(result["github_request_accepted"])
        self.assertIsNone(result["run_id"])
        self.assertFalse(result["verified_complete"])
        self.assertFalse(result["merge_authorized"])
        self.assertEqual(self.sent, [("private-github-token", SHA)])
        with self.leases._connection() as db:
            link = dict(db.execute("SELECT * FROM r10_r5_dispatch_links").fetchone())
            r5_row = dict(db.execute("SELECT * FROM r5_fixed_dispatches").fetchone())
            mission = dict(db.execute("SELECT * FROM r9_missions").fetchone())
        self.assertEqual(link["mission_id"], mission["mission_id"])
        self.assertEqual(link["source_sha"], SHA)
        self.assertEqual(link["lease_generation"], self.capability["generation"])
        self.assertEqual(link["request_id"], r5_row["request_id"])
        self.assertEqual(link["state"], result["state"])
        for secret in ("private-github-token", self.capability["token"]):
            self.assertNotIn(secret, json.dumps(result))
            self.assertNotIn(secret, json.dumps(link))

    def test_replay_never_issues_second_post_even_if_first_was_accepted(self):
        self.run_bridge(execute=True, confirmation=bridge.CONFIRM,
                        token="private-github-token")
        with self.assertRaisesRegex(bridge.BridgeHeld, "ALREADY_ATTEMPTED"):
            self.run_bridge(execute=True, confirmation=bridge.CONFIRM,
                            token="private-github-token")
        with self.assertRaisesRegex(bridge.BridgeHeld, "ALREADY_ATTEMPTED"):
            self.run_bridge()
        self.assertEqual(len(self.sent), 1)

    def test_unknown_post_remains_held_for_reconciliation(self):
        def timeout(_token, _sha):
            self.sent.append(("called", SHA))
            raise TimeoutError()
        out = self.run_bridge(execute=True, confirmation=bridge.CONFIRM,
                              token="private-github-token", post=timeout)
        self.assertEqual(out["state"], "POST_OUTCOME_UNKNOWN")
        self.assertFalse(out["github_request_accepted"])
        with self.assertRaisesRegex(bridge.BridgeHeld, "ALREADY_ATTEMPTED"):
            self.run_bridge(execute=True, confirmation=bridge.CONFIRM,
                            token="private-github-token")
        self.assertEqual(len(self.sent), 1)
        with self.leases._connection() as db:
            link = db.execute("SELECT state FROM r10_r5_dispatch_links").fetchone()
        self.assertEqual(link["state"], "POST_OUTCOME_UNKNOWN")

    def test_wrong_mission_kind_state_and_intake_never_dispatch(self):
        with self.leases._transaction() as db:
            db.execute("UPDATE r9_missions SET kind=?", (r9.KIND_AUDIT,))
        with self.assertRaisesRegex(bridge.BridgeHeld, "NOT_ASSIGNED"):
            self.run_bridge(execute=True, confirmation=bridge.CONFIRM,
                            token="private-github-token")
        with self.leases._transaction() as db:
            db.execute("UPDATE r9_missions SET kind=?,state=?",
                       (r9.KIND_TEST, "QA_QUEUED"))
        with self.assertRaisesRegex(bridge.BridgeHeld, "NOT_ASSIGNED"):
            self.run_bridge()
        with self.leases._transaction() as db:
            db.execute("UPDATE r9_missions SET state=?", ("ASSIGNED_IMPLEMENT",))
        wrong = {**self.intake, "source_sha": OTHER}
        with self.assertRaisesRegex(bridge.BridgeHeld, "MISSION_INTAKE_MISMATCH"):
            self.run_bridge(intake=wrong)
        wrong_repo = {**self.intake, "repository_id": 123}
        with self.assertRaisesRegex(bridge.BridgeHeld, "ONLY_EXISTING"):
            self.run_bridge(intake=wrong_repo)
        self.assertEqual(self.sent, [])

    def test_forged_lease_wrong_worker_expired_and_source_drift_hold(self):
        fake = {**self.capability, "token": "fake"}
        with self.assertRaisesRegex(bridge.BridgeHeld, "LEASE_EXPIRED_OR_FENCED"):
            self.run_bridge(capability=fake)
        with self.leases._transaction() as db:
            db.execute("UPDATE r9_missions SET worker=?", ("stranger",))
        with self.assertRaisesRegex(bridge.BridgeHeld, "LEASE_OR_WORKER_CHANGED"):
            self.run_bridge()
        with self.leases._transaction() as db:
            db.execute("UPDATE r9_missions SET worker=?", ("worker1",))
        with self.assertRaises(r5.DispatchHeld):
            self.run_bridge(get=FakeGitHub(sha=OTHER))
        self.assertEqual(self.sent, [])

    def test_requires_operator_confirmation_and_token_to_post(self):
        for confirmation, token in ((None, "private"), ("sure", "private"),
                                     (bridge.CONFIRM, None),
                                     (bridge.CONFIRM, "")):
            with self.subTest(confirmation=confirmation, token=token):
                with self.assertRaises(bridge.BridgeHeld):
                    self.run_bridge(execute=True, confirmation=confirmation,
                                    token=token)
        with self.assertRaisesRegex(bridge.BridgeHeld, "DRY_RUN_MUST_NOT"):
            self.run_bridge(confirmation=bridge.CONFIRM)
        with self.leases._connection() as db:
            self.assertFalse(db.execute(
                "SELECT name FROM sqlite_master WHERE name='r10_r5_dispatch_links'"
            ).fetchall())
        self.assertEqual(self.sent, [])

    def test_disabled_workflow_never_posts_or_creates_link(self):
        with self.assertRaisesRegex(r5.DispatchHeld, "WORKFLOW_NOT_ACTIVE"):
            self.run_bridge(execute=True, confirmation=bridge.CONFIRM,
                            token="private", get=FakeGitHub(workflow="disabled_manually"))
        with self.leases._connection() as db:
            self.assertFalse(db.execute(
                "SELECT name FROM sqlite_master WHERE name='r10_r5_dispatch_links'"
            ).fetchall())
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
