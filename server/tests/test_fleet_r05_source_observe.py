"""Fleet R0.5: exact-revision source observation and lease fencing tests."""
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r04_leases as leases
import fleet_r05_source_observe as mod

NOW = 1793700000000
HEAD = "a" * 40
OTHER = "b" * 40


def intake(name="BTM", repo_id=42, head=HEAD, branch="main"):
    return {
        "schema": leases.INTAKE_SCHEMA,
        "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER,
        "repository": leases.OWNER + "/" + name,
        "repository_id": repo_id,
        "source_sha": head,
        "request_sha256": "c" * 64,
        "default_branch": branch,
        "verified_complete": False,
        "operator_approved": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False,
        "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests", "verification_state": "NOT_RUN",
                    "evidence_receipt": None}],
    }


class FakeGitHub:
    def __init__(self, *, heads=(HEAD, HEAD), repo_id=42, private=False,
                 archived=False, default_branch="main", name="BTM",
                 branch_name="main"):
        self.heads = iter(heads)
        self.repo_id = repo_id
        self.private = private
        self.archived = archived
        self.default_branch = default_branch
        self.name = name
        self.branch_name = branch_name
        self.paths = []

    def __call__(self, path, token):
        self.paths.append((path, token))
        if "/branches/" in path:
            return {"name": self.branch_name,
                    "commit": {"sha": next(self.heads)}}
        return {"id": self.repo_id, "full_name": leases.OWNER + "/" + self.name,
                "owner": {"login": leases.OWNER}, "private": self.private,
                "archived": self.archived, "default_branch": self.default_branch}


class SourceObservationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.ledger = leases.LeaseLedger(self.root / "lease.db")
        self.input = intake()
        self.cap = self.ledger.reserve(self.input, "worker-1",
                                       ttl_seconds=300, now_ms=NOW)

    def observe(self, fake, **kw):
        return mod.observe(self.input, self.cap, self.ledger, get=fake,
                           clock=lambda: NOW, **kw)

    def test_exact_source_matches_twice_without_test_execution(self):
        get = FakeGitHub()
        result = self.observe(get, token="secret-should-not-leak")
        self.assertEqual(result["state"], "SOURCE_HEAD_MATCH_OBSERVED")
        self.assertTrue(result["source_head_observed_match"])
        self.assertTrue(result["lease_fenced_at_observation"])
        self.assertEqual(result["git_api_reads"], 3)
        self.assertEqual(result["requested_sha"], HEAD)
        self.assertEqual(result["lease_generation"], self.cap["generation"])
        self.assertEqual(result["request_sha256"], self.input["request_sha256"])
        for field in ("code_executed", "product_verified", "operator_approved",
                      "job_dispatch_authorized", "merge_authorized",
                      "future_head_stability_guaranteed"):
            self.assertIs(result[field], False)
        self.assertEqual(result["automated_tests_run"], 0)
        self.assertEqual(result["independent_check_results"], "NOT_RUN")
        self.assertEqual(len(get.paths), 3)
        self.assertEqual(get.paths[0][0], "/repos/MichaelWave369/BTM")
        self.assertEqual(get.paths[1][0], "/repos/MichaelWave369/BTM/branches/main")
        self.assertNotIn("secret-should-not-leak", json.dumps(result))
        self.assertNotIn(self.cap["token"], json.dumps(result))

    def test_revision_moved_is_held_not_an_acceptance_pass(self):
        result = self.observe(FakeGitHub(heads=(OTHER, OTHER)))
        self.assertEqual(result["state"], "HELD_SOURCE_REVISION_MOVED")
        self.assertFalse(result["source_head_observed_match"])
        self.assertEqual(result["last_observed_sha"], OTHER)
        self.assertFalse(result["merge_authorized"])

    def test_head_changed_mid_observation_is_held(self):
        result = self.observe(FakeGitHub(heads=(HEAD, OTHER)))
        self.assertEqual(result["state"], "HELD_HEAD_CHANGED_DURING_READS")
        self.assertFalse(result["source_head_observed_match"])

    def test_wrong_identity_private_archived_or_default_branch_is_held(self):
        for kwargs in ({"repo_id": 43}, {"private": True}, {"archived": True},
                       {"name": "Other"}, {"default_branch": "develop"}):
            with self.subTest(kwargs=kwargs):
                get = FakeGitHub(**kwargs)
                result = self.observe(get)
                self.assertEqual(result["state"], "HELD_REPOSITORY_IDENTITY_CHANGED")
                self.assertFalse(result["repository_identity_observed_match"])
                self.assertEqual(result["git_api_reads"], 1)
                self.assertEqual(len(get.paths), 1)

    def test_malformed_branch_response_fails_closed(self):
        for kwargs in ({"heads": ("not-a-commit", OTHER)},
                       {"branch_name": "other"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(mod.ObservationHeld,
                                            "GITHUB_BRANCH_RESPONSE_INVALID"):
                    self.observe(FakeGitHub(**kwargs))

    def test_unsafe_branch_rejected_without_network_access(self):
        for branch in ("../secret", "x//y", "/main", "main/", "a/../b",
                       "refs/main?token=123", "a%2Fb"):
            with self.subTest(branch=branch):
                self.input["default_branch"] = branch
                fake = FakeGitHub()
                with self.assertRaisesRegex(mod.ObservationHeld, "BRANCH_UNSAFE"):
                    self.observe(fake)
                self.assertEqual(fake.paths, [])
        self.input["default_branch"] = "main"

    def test_nested_branch_is_percent_encoded_with_fixed_owner_and_repo(self):
        self.input["default_branch"] = "release/v1"
        fake = FakeGitHub(default_branch="release/v1", branch_name="release/v1")
        result = self.observe(fake)
        self.assertEqual(result["state"], "SOURCE_HEAD_MATCH_OBSERVED")
        self.assertEqual(fake.paths[1][0],
                         "/repos/MichaelWave369/BTM/branches/release%2Fv1")

    def test_old_fenced_token_rejected_before_any_api_read(self):
        self.ledger.release(self.cap, now_ms=NOW + 100)
        fake = FakeGitHub()
        with self.assertRaisesRegex(mod.ObservationHeld, "LEASE_NOT_CURRENT"):
            self.observe(fake)
        self.assertEqual(fake.paths, [])

    def test_source_result_discarded_if_lease_expires_during_reads(self):
        clock = iter((NOW, NOW + 300001))
        fake = FakeGitHub()
        with self.assertRaisesRegex(mod.ObservationHeld, "LEASE_NOT_CURRENT"):
            mod.observe(self.input, self.cap, self.ledger, get=fake,
                        clock=lambda: next(clock))
        self.assertEqual(len(fake.paths), 3)

    def test_cannot_cross_use_different_intake_or_capability(self):
        wrong_input = intake(name="PhiOS", repo_id=77)
        fake = FakeGitHub()
        with self.assertRaisesRegex(mod.ObservationHeld, "LEASE_INTAKE_MISMATCH"):
            mod.observe(wrong_input, self.cap, self.ledger,
                        get=fake, clock=lambda: NOW)
        self.assertEqual(fake.paths, [])
        with self.assertRaisesRegex(mod.ObservationHeld, "LEASE_NOT_CURRENT"):
            mod.observe(self.input, {**self.cap, "token": "fake"},
                        self.ledger, get=fake, clock=lambda: NOW)

    def test_receipt_written_once_without_capability_secrets(self):
        output = self.root / "observations" / "source.json"
        result = self.observe(FakeGitHub())
        mod.write_new_receipt(output, result)
        stored = json.loads(output.read_text())
        self.assertTrue(stored["source_head_observed_match"])
        self.assertNotIn("token", stored)
        self.assertNotIn(self.cap["token"], output.read_text())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o600)
        with self.assertRaisesRegex(mod.ObservationHeld, "RECEIPT_EXISTS"):
            mod.write_new_receipt(output, result)

    def test_symlink_output_refused(self):
        target = self.root / "existing.json"
        target.write_text("original")
        link = self.root / "link.json"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Symlinks unavailable on this filesystem")
        with self.assertRaisesRegex(mod.ObservationHeld, "RECEIPT_EXISTS"):
            mod.write_new_receipt(link, self.observe(FakeGitHub()))
        self.assertEqual(target.read_text(), "original")

    def test_invalid_github_payload_and_api_paths_rejected(self):
        with self.assertRaisesRegex(mod.ObservationHeld, "GITHUB_REPOSITORY_RESPONSE_INVALID"):
            self.observe(lambda path, token: [])
        for path in ("https://evil.example/api", "/user/repos",
                     "/repos/Other/BTM"):
            with self.assertRaisesRegex(mod.ObservationHeld, "GITHUB_PATH_INVALID"):
                mod.github_get(path)
        self.assertIsNone(mod.NoRedirect().redirect_request(None, None, 302,
                        "Moved", {}, "https://elsewhere.test"))

    def test_authority_claim_in_import_is_rejected_before_fetch(self):
        evil = {**self.input, "dispatch_authorized": True}
        fake = FakeGitHub()
        with self.assertRaises(leases.LeaseHeld):
            mod.observe(evil, self.cap, self.ledger,
                        get=fake, clock=lambda: NOW)
        self.assertEqual(fake.paths, [])


if __name__ == "__main__":
    unittest.main()
