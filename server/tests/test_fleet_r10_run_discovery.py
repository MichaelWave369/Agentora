"""R10: bounded read-only GitHub candidate discovery without attribution."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r10_run_discovery as discovery
import fleet_r10_r9_r5_bridge as r10
import fleet_r9_mission_control as r9
import fleet_r5_guarded_dispatch as r5
import fleet_r04_leases as leases
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 8, 20, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
SHA = "a" * 40
RUN = 72550001234


def observations():
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": 60,
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
    return {"schema": leases.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER, "repository": r5.pilot.REPOSITORY,
        "repository_id": r5.pilot.REPOSITORY_ID, "default_branch": "main",
        "source_sha": SHA, "request_sha256": "b" * 64,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN", "evidence_receipt": None}]}


def run(run_id=RUN, *, created=None, path=discovery.EXPECTED_PATH,
        event="workflow_dispatch", status="completed", conclusion="success",
        repository_id=discovery.r07.AGENTORA_ID):
    return {"id": run_id, "event": event, "path": path, "status": status,
        "conclusion": conclusion, "run_attempt": 1,
        "created_at": (created or (NOW + timedelta(minutes=2))).isoformat(),
        "head_sha": "c" * 40,
        "repository": {"id": repository_id, "full_name": discovery.OWNER},
        "head_repository": {"full_name": discovery.OWNER}}


def artifact(run_id=RUN, *, wrong=False):
    return {
        "id": run_id + 1000,
        "name": discovery.r07.ARTIFACT_PREFIX + str(run_id),
        "digest": "sha256:" + ("f" if wrong else "d") * 64,
        "expired": False, "size_in_bytes": 1900,
        "workflow_run": {"id": run_id}}


class FakeGitHub:
    def __init__(self, runs=None, artifacts=None, total_count=None):
        self.runs = [run()] if runs is None else runs
        self.artifacts = artifacts
        self.total_count = total_count
        self.paths = []

    def get_runs(self, path, token):
        self.paths.append(path)
        assert path.startswith("/repos/MichaelWave369/Agentora/actions/runs?")
        assert "event=workflow_dispatch" in path
        assert "per_page=100" in path
        assert "page=" in path
        page = int(path.rsplit("page=", 1)[-1])
        return {"total_count": len(self.runs) if self.total_count is None
                else self.total_count,
                "workflow_runs": self.runs[(page - 1)*100:page*100]}

    def get_artifacts(self, path, token):
        self.paths.append(path)
        run_id = int(path.split("/runs/")[1].split("/")[0])
        assert path.endswith("/artifacts?per_page=100")
        records = ([artifact(run_id)] if self.artifacts is None else
                   self.artifacts.get(run_id, []))
        return {"total_count": len(records), "artifacts": records}


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.registry = StewardRegistry(root / "stewards.db")
        self.ledger = leases.LeaseLedger(root / "leases.db")
        self.registry.ingest(observations(), now=NOW)
        self.control = r9.MissionControl(self.registry, self.ledger)
        self.source = intake()
        self.mission = "pilot-run-discovery"
        self.control.enqueue(self.mission, r9.KIND_TEST, self.source,
                             confirmation=r9.CONFIRM, now=NOW, now_ms=MS)
        self.lease_path = root / "private" / "worker.lease"
        self.control.claim_next(self.source, "worker1", self.lease_path,
                                ttl=1800, now=NOW, now_ms=MS)
        self.cap = leases.load_capability(self.lease_path)

    def dispatch(self, *, status=204):
        class GitHub:
            def __call__(self, path, token):
                if path == r5.WORKFLOW_ENDPOINT:
                    return {"id": 123, "path": r5.WORKFLOW_PATH, "state": "active"}
                if path == "/repos/MichaelWave369/PhiMadaPrime":
                    return {"id": r5.pilot.REPOSITORY_ID,
                            "full_name": r5.pilot.REPOSITORY,
                            "owner": {"login": "MichaelWave369"},
                            "private": False, "archived": False,
                            "default_branch": "main"}
                if path == "/repos/MichaelWave369/PhiMadaPrime/branches/main":
                    return {"name": "main", "commit": {"sha": SHA}}
                raise AssertionError("wrong endpoint: " + path)
        return r10.submit(
            self.control, self.mission, self.source, self.cap,
            execute=True, confirmation=r10.CONFIRM, token="hidden",
            get=GitHub(), post=lambda _token, _sha: status,
            now=NOW, clock_ms=lambda: MS)

    def discover(self, gh=None, **kw):
        gh = gh or FakeGitHub()
        result = discovery.discover(self.ledger, self.mission,
            run_get=gh.get_runs, artifact_get=gh.get_artifacts,
            now=kw.pop("now", NOW + timedelta(minutes=5)),
            max_pages=kw.pop("max_pages", 2), **kw)
        return result, gh

    def test_accepted_journal_yields_inert_unverified_candidate(self):
        self.dispatch()
        result, gh = self.discover()
        self.assertEqual(result["state"],
                         "CANDIDATES_ONLY_NO_MISSION_ATTRIBUTION")
        self.assertEqual(result["request_id"], r10._request_id(self.mission))
        self.assertEqual(result["pilot_source_sha_claim"], SHA)
        self.assertEqual(result["candidates"][0]["run_id"], RUN)
        self.assertEqual(result["candidates"][0]["artifact_id"], RUN + 1000)
        self.assertEqual(result["candidates"][0]["state"],
                         "CANDIDATE_NOT_CORRELATED_NEEDS_ZIP_AND_R07")
        for flag in ("run_artifact_bytes_verified", "verified_complete",
                     "merge_authorized", "dispatch_authorized",
                     "dispatch_origin_authenticated"):
            self.assertFalse(result[flag])
        self.assertEqual(len(gh.paths), 2)
        self.assertNotIn("hidden", json.dumps(result))
        self.assertNotIn(self.cap["token"], json.dumps(result))

    def test_candidate_discovery_does_not_need_a_still_live_worker_lease(self):
        self.dispatch()
        result, _ = self.discover(now=NOW + timedelta(hours=1))
        self.assertEqual(result["candidates"][0]["run_id"], RUN)
        self.assertFalse(result["run_artifact_bytes_verified"])

    def test_without_accepted_journals_does_not_query_github(self):
        gh = FakeGitHub()
        with self.assertRaisesRegex(discovery.DiscoveryHeld, "JOURNALS"):
            self.discover(gh)
        self.assertEqual(gh.paths, [])
        self.dispatch(status=403)
        with self.assertRaisesRegex(discovery.DiscoveryHeld, "NO_ACCEPTED"):
            self.discover(gh)
        self.assertEqual(gh.paths, [])

    def test_old_run_and_unrelated_workflows_are_not_assigned(self):
        self.dispatch()
        gh = FakeGitHub(runs=[
            run(created=NOW-timedelta(hours=1)),
            run(run_id=RUN+1, path=".github/workflows/ci.yml"),
            run(run_id=RUN+2, event="push"),
        ])
        result, gh = self.discover(gh)
        self.assertEqual(result["state"], "NO_CANDIDATE_IN_SCANNED_WINDOW")
        self.assertEqual(result["candidates"], [])
        self.assertEqual(len(gh.paths), 1)

    def test_two_same_sha_successful_runs_remain_ambiguous_candidates(self):
        self.dispatch()
        gh = FakeGitHub(runs=[run(run_id=RUN), run(run_id=RUN+1)])
        result, _ = self.discover(gh)
        self.assertEqual(len(result["candidates"]), 2)
        self.assertEqual({x["run_id"] for x in result["candidates"]},
                         {RUN, RUN+1})
        self.assertFalse(result["run_artifact_bytes_verified"])

    def test_incomplete_or_failed_run_never_claims_test_success(self):
        self.dispatch()
        gh = FakeGitHub(runs=[
            run(run_id=RUN, status="in_progress", conclusion=None),
            run(run_id=RUN+1, conclusion="failure"),
            run(run_id=RUN+2, status="completed", conclusion="success"),
        ], artifacts={RUN+2: []})
        result, _ = self.discover(gh)
        self.assertEqual(result["candidates"][0]["state"],
                         "RUN_NOT_SUCCESSFULLY_COMPLETED")
        self.assertEqual(result["candidates"][1]["state"],
                         "RUN_NOT_SUCCESSFULLY_COMPLETED")
        self.assertEqual(result["candidates"][2]["state"],
                         "SUCCESSFUL_RUN_BUT_NO_PILOT_ARTIFACT")

    def test_malformed_or_impostor_metadata_holds(self):
        self.dispatch()
        bad_runs = [
            run(repository_id=999),
            {**run(), "id": True},
            {**run(), "created_at": "bad-time"},
            {**run(), "head_repository": {"full_name": "attacker/fork"}},
            {**run(), "run_attempt": "1"},
        ]
        for bad in bad_runs:
            with self.subTest(bad=bad), self.assertRaises(
                    discovery.DiscoveryHeld):
                self.discover(FakeGitHub(runs=[bad]))
        wrong_artifact = artifact()
        wrong_artifact["workflow_run"] = {"id": RUN+1}
        for bad in ([wrong_artifact],
                    [artifact(), artifact()],
                    [{**artifact(), "digest": "sha256:INVALID"}],
                    [{**artifact(), "expired": True}]):
            with self.subTest(artifacts=bad), self.assertRaises(
                    discovery.DiscoveryHeld):
                self.discover(FakeGitHub(artifacts={RUN: bad}))

    def test_duplicate_runs_across_pages_and_budget_limit(self):
        self.dispatch()
        many = [run(run_id=RUN+i) for i in range(100)]
        gh = FakeGitHub(runs=many, total_count=101)
        out, gh = self.discover(gh, max_pages=1)
        self.assertTrue(out["truncated"])
        self.assertEqual(len(out["candidates"]), discovery.MAX_CANDIDATES)
        with self.assertRaisesRegex(discovery.DiscoveryHeld, "PAGE_BUDGET"):
            self.discover(max_pages=5)

    def test_stale_local_dispatch_refuses_to_promise_qualification(self):
        self.dispatch()
        with self.assertRaisesRegex(discovery.DiscoveryHeld, "TOO_OLD"):
            self.discover(now=NOW+timedelta(days=9))

    def test_wrong_mission_kind_refuses_candidate_discovery(self):
        self.dispatch()
        with self.ledger._transaction() as db:
            db.execute("UPDATE r9_missions SET kind=?", (r9.KIND_AUDIT,))
        with self.assertRaisesRegex(discovery.DiscoveryHeld,
                                    "MISSION_NOT_FIXED_ASSIGNED"):
            self.discover()


if __name__ == "__main__":
    unittest.main()
