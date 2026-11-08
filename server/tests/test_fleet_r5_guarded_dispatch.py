"""R5: real guarded one-shot workflow submission, without merge authority."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r5_guarded_dispatch as r5
import fleet_r04_leases as leases
import fleet_r3_steward_claim as steward
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
SHA = "a" * 40
OTHER = "b" * 40


def observations(archived=False):
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": 11,
        "observed_at": (NOW - timedelta(minutes=2)).isoformat(),
        "public_repo_count": 1,
        "repositories": [{"github_id": r5.pilot.REPOSITORY_ID,
            "full_name": r5.pilot.REPOSITORY, "archived": archived,
            "source_only": True, "verified_complete": False}],
        "recent_events": [], "source_only": True,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def intake():
    return {
        "schema": leases.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER, "repository": r5.pilot.REPOSITORY,
        "repository_id": r5.pilot.REPOSITORY_ID,
        "default_branch": "main", "source_sha": SHA,
        "request_sha256": "b"*64,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN", "evidence_receipt": None}],
    }


class FakeGitHub:
    def __init__(self, sha=SHA, *, workflow="active", drift_after=None):
        self.sha, self.workflow, self.drift_after = sha, workflow, drift_after
        self.branch_reads = 0
        self.paths = []

    def __call__(self, path, token):
        self.paths.append(path)
        if path == r5.WORKFLOW_ENDPOINT:
            return {"id": 456, "path": r5.WORKFLOW_PATH, "state": self.workflow}
        if path == "/repos/MichaelWave369/PhiMadaPrime":
            return {"id": r5.pilot.REPOSITORY_ID,
                    "full_name": r5.pilot.REPOSITORY,
                    "owner": {"login": "MichaelWave369"},
                    "private": False, "archived": False, "default_branch": "main"}
        if path == "/repos/MichaelWave369/PhiMadaPrime/branches/main":
            self.branch_reads += 1
            value = (OTHER if self.drift_after is not None
                     and self.branch_reads >= self.drift_after else self.sha)
            return {"name": "main", "commit": {"sha": value}}
        raise AssertionError("unexpected URL " + path)


class R5TraceTests(unittest.TestCase):
    def test_optional_request_trace_is_fixed_bounded_post_input(self):
        calls = []
        class Response:
            status = 204
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False
        class Opener:
            def open(self, request, timeout):
                calls.append((request, timeout))
                return Response()
        request_id = "r10r5-" + "d" * 40
        with patch.object(r5, "build_opener", return_value=Opener()):
            result = r5.github_dispatch("operator-token", SHA, request_id)
            self.assertEqual(result, 204)
            payload = json.loads(calls[0][0].data)
            self.assertEqual(payload["ref"], "main")
            self.assertEqual(payload["inputs"], {
                "source_sha": SHA, "confirmation": r5.pilot.CONFIRMATION,
                "request_id": request_id})
            self.assertNotIn("operator-token", json.dumps(payload))
            self.assertEqual(
                r5.github_dispatch("operator-token", SHA), 204)
            legacy = json.loads(calls[1][0].data)
            self.assertNotIn("request_id", legacy["inputs"])
        with self.assertRaisesRegex(r5.DispatchHeld, "DISPATCH_TRACE_ID_INVALID"):
            r5.github_dispatch("operator-token", SHA, "evil/workflow")
        self.assertEqual(len(calls), 2)


class R5Tests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.registry = StewardRegistry(root / "stewards.db")
        self.ledger = leases.LeaseLedger(root / "leases.db")
        self.registry.ingest(observations(), now=NOW)
        self.intake = intake()
        self.lease_file = root / "private" / "worker.json"
        steward.claim(self.registry, self.ledger, self.intake, "worker1",
                      self.lease_file, now=NOW, now_ms=MS, ttl=300)
        self.capability = leases.load_capability(self.lease_file)

    def run_dispatch(self, *, execute=True, request_id="pilot1", confirmation=r5.CONFIRM,
                     get=None, post=None, **override):
        self.sent = []
        def accepted(token, sha):
            self.sent.append((token, sha))
            return 204
        return r5.dispatch(
            self.registry, self.ledger,
            override.pop("intake", self.intake),
            override.pop("capability", self.capability),
            request_id=request_id, execute=execute,
            confirmation=confirmation if execute else None,
            token=override.pop("token", "hidden-token" if execute else None),
            get=get or FakeGitHub(), post=post or accepted,
            now=override.pop("now", NOW), clock_ms=override.pop("clock_ms", lambda: MS),
            **override,
        )

    def test_acceptance_is_not_completed_work_or_approval(self):
        out = self.run_dispatch()
        self.assertEqual(out["state"], "REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED")
        self.assertTrue(out["github_request_accepted"])
        self.assertEqual(out["source_sha"], SHA)
        self.assertIsNone(out["run_id"])
        self.assertFalse(out["merge_authorized"])
        self.assertFalse(out["product_verified"])
        self.assertEqual(self.sent, [("hidden-token", SHA)])
        self.assertNotIn(self.capability["token"], json.dumps(out))
        with self.ledger._connection() as db:
            record = dict(db.execute("SELECT * FROM r5_fixed_dispatches").fetchone())
        self.assertEqual(record["state"], out["state"])
        self.assertNotIn("hidden-token", json.dumps(record))
        self.assertNotIn(self.capability["token"], json.dumps(record))

    def test_dry_run_does_not_write_intent_or_submit(self):
        result = self.run_dispatch(execute=False, request_id="same")
        self.assertEqual(result["state"], "DRY_RUN_READY_NO_DISPATCH")
        self.assertEqual(result["actual_jobs_dispatched"], 0)
        out = self.run_dispatch(request_id="same")
        self.assertTrue(out["github_request_accepted"])

    def test_one_shot_intent_refuses_same_or_different_request_id(self):
        self.run_dispatch()
        for request_id in ("pilot1", "pilot2"):
            with self.subTest(request_id=request_id), self.assertRaisesRegex(
                r5.DispatchHeld, "ALREADY_ATTEMPTED"
            ):
                self.run_dispatch(request_id=request_id)

    def test_network_uncertainty_stays_unknown_and_never_retries(self):
        submitted = []
        def timeout(token, sha):
            submitted.append(1)
            raise TimeoutError("unknown")
        out = self.run_dispatch(post=timeout)
        self.assertEqual(out["state"], "POST_OUTCOME_UNKNOWN")
        self.assertFalse(out["github_request_accepted"])
        with self.assertRaisesRegex(r5.DispatchHeld, "ALREADY_ATTEMPTED"):
            self.run_dispatch(post=timeout)
        self.assertEqual(len(submitted), 1)

    def test_github_reject_does_not_imply_running(self):
        out = self.run_dispatch(post=lambda _token, _sha: 403)
        self.assertEqual(out["state"], "GITHUB_REJECTED_REQUEST")
        self.assertFalse(out["github_request_accepted"])
        with self.assertRaisesRegex(r5.DispatchHeld, "ALREADY_ATTEMPTED"):
            self.run_dispatch()

    def test_explicit_operator_confirmation_and_token_required(self):
        for options in ({"confirmation": "sure"}, {"confirmation": None},
                        {"request_id": "bad/request"}, {"token": ""}):
            with self.subTest(options=options), self.assertRaises(r5.DispatchHeld):
                self.run_dispatch(**options)
        with self.ledger._connection() as db:
            rows = db.execute("SELECT name FROM sqlite_master WHERE name='r5_fixed_dispatches'").fetchall()
        self.assertEqual(rows, [])

    def test_head_drift_or_wrong_sha_prevents_post(self):
        for fake in (FakeGitHub(OTHER), FakeGitHub(drift_after=3)):
            with self.subTest(fake=fake), self.assertRaises(r5.DispatchHeld):
                self.run_dispatch(get=fake)

    def test_disabled_or_swapped_workflow_is_refused(self):
        with self.assertRaisesRegex(r5.DispatchHeld, "WORKFLOW_NOT_ACTIVE"):
            self.run_dispatch(get=FakeGitHub(workflow="disabled_manually"))
        def swapped(path, token):
            value = FakeGitHub()(path, token)
            if path == r5.WORKFLOW_ENDPOINT:
                value["path"] = ".github/workflows/other.yml"
            return value
        with self.assertRaisesRegex(r5.DispatchHeld, "WORKFLOW_NOT_ACTIVE"):
            self.run_dispatch(get=swapped)

    def test_expired_forged_or_nearly_expired_lease_fails(self):
        with self.assertRaisesRegex(r5.DispatchHeld, "LEASE_EXPIRED"):
            self.run_dispatch(clock_ms=lambda: MS + 350000)
        with self.assertRaisesRegex(r5.DispatchHeld, "LEASE_RENEWAL"):
            self.run_dispatch(clock_ms=lambda: MS + 250000)
        forged = {**self.capability, "token": "wrong"}
        with self.assertRaisesRegex(r5.DispatchHeld, "LEASE_EXPIRED"):
            self.run_dispatch(capability=forged)

    def test_archived_steward_cannot_dispatch(self):
        state = observations(archived=True)
        state["source_scan_id"] = 12
        self.registry.ingest(state, now=NOW)
        with self.assertRaises(steward.HandoffHeld):
            self.run_dispatch()

    def test_fixed_repository_and_branch_only(self):
        wrong = intake()
        wrong["repository_id"] = 22
        with self.assertRaisesRegex(r5.DispatchHeld, "ONLY_FIXED"):
            self.run_dispatch(intake=wrong)
        other = intake()
        other["default_branch"] = "feature"
        with self.assertRaisesRegex(r5.DispatchHeld, "ONLY_FIXED"):
            self.run_dispatch(intake=other)


if __name__ == "__main__":
    unittest.main()
