"""R0.8 PaperGhost fixed second-repository pilot safety and bounded receipt tests."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r08_paperghost_pilot as pilot

SHA = "a" * 40
OTHER = "b" * 40
NOW = datetime(2026, 11, 3, 18, 0, tzinfo=timezone.utc)


class FakeGitHub:
    def __init__(self, heads=(SHA, SHA), *, name=pilot.REPOSITORY,
                 identity=pilot.REPOSITORY_ID, private=False, archived=False,
                 branch=pilot.BRANCH):
        self.heads = iter(heads)
        self.name = name
        self.identity = identity
        self.private = private
        self.archived = archived
        self.branch = branch
        self.reads = []

    def __call__(self, path, token):
        self.reads.append((path, token))
        if path.endswith("/branches/main"):
            return {"name": "main", "commit": {"sha": next(self.heads)}}
        if path == "/repos/MichaelWave369/PaperGhost":
            return {"id": self.identity, "full_name": self.name,
                    "owner": {"login": pilot.OWNER},
                    "private": self.private, "archived": self.archived,
                    "default_branch": self.branch}
        raise AssertionError("unexpected URL: " + path)


def clock():
    return NOW


def preflight():
    return pilot.prepare_pilot(SHA, pilot.CONFIRMATION, FakeGitHub(), clock=clock)


def steps(install=0, test=0, build=0, checkout=SHA):
    return {"checkout_sha": checkout, "install_exit": install,
            "test_exit": test, "build_exit": build}


class FleetPilotTests(unittest.TestCase):
    def test_preflight_fixed_repo_sha_and_no_execution_authority(self):
        get = FakeGitHub()
        proof = pilot.prepare_pilot(SHA, pilot.CONFIRMATION, get,
                                    token="not-for-worker", clock=clock)
        self.assertEqual(proof["state"], "SOURCE_HEAD_MATCH_OBSERVED")
        self.assertEqual(proof["repository_id"], 1443390000)
        self.assertEqual(proof["api_gets"], 3)
        self.assertEqual([path for path, _ in get.reads], [
            "/repos/MichaelWave369/PaperGhost",
            "/repos/MichaelWave369/PaperGhost/branches/main",
            "/repos/MichaelWave369/PaperGhost/branches/main",
        ])
        self.assertEqual(proof["checks_run"], 0)
        self.assertFalse(proof["merge_authorized"])
        self.assertFalse(proof["product_verified"])
        self.assertNotIn("not-for-worker", json.dumps(proof))

    def test_requires_explicit_manual_confirmation(self):
        get = FakeGitHub()
        for wrong in (None, "", "yes", True, "RUN_ANYTHING"):
            with self.subTest(wrong=wrong):
                with self.assertRaisesRegex(pilot.PilotHeld,
                                            "EXPLICIT_WORKFLOW_OPT_IN_REQUIRED"):
                    pilot.prepare_pilot(SHA, wrong, get, clock=clock)
        self.assertEqual(get.reads, [])

    def test_reject_unpinned_or_malformed_source(self):
        get = FakeGitHub()
        for invalid in ("main", SHA[:39], SHA + "0", "X" * 40, None):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(pilot.PilotHeld, "SHA_REQUIRED"):
                    pilot.prepare_pilot(invalid, pilot.CONFIRMATION,
                                        get, clock=clock)
        self.assertEqual(get.reads, [])

    def test_wrong_identity_is_held_and_does_not_read_branch(self):
        for kwargs in ({"identity": 22}, {"name": "attacker/PaperGhost"},
                       {"private": True}, {"archived": True},
                       {"branch": "feature"}):
            with self.subTest(kwargs=kwargs):
                get = FakeGitHub(**kwargs)
                proof = pilot.prepare_pilot(SHA, pilot.CONFIRMATION, get,
                                            clock=clock)
                self.assertEqual(proof["state"], "HELD_IDENTITY_MISMATCH")
                self.assertFalse(proof["head_match"])
                self.assertEqual(len(get.reads), 1)

    def test_drift_or_inflight_push_held(self):
        for heads, expected in [
            ((OTHER, OTHER), "HELD_REQUESTED_SHA_NOT_CURRENT"),
            ((SHA, OTHER), "HELD_HEAD_CHANGED_DURING_READS"),
        ]:
            with self.subTest(heads=heads):
                proof = pilot.prepare_pilot(SHA, pilot.CONFIRMATION,
                                            FakeGitHub(heads), clock=clock)
                self.assertEqual(proof["state"], expected)
                self.assertFalse(proof["head_match"])

    def test_final_checks_pass_is_not_full_product_verification(self):
        result = pilot.finalize_pilot(SHA, preflight(), steps(),
                                      get=FakeGitHub(), clock=clock,
                                      workflow_run_id="123456")
        self.assertEqual(result["state"],
                         "AUTOMATED_CHECKS_PASSED_AT_OBSERVED_SHA")
        self.assertTrue(result["automated_checks_passed"])
        self.assertEqual(result["source_sha"], SHA)
        self.assertEqual(result["workflow_run_id"], "123456")
        self.assertEqual(result["checks"]["node_tests"]["exit_code"], 0)
        self.assertEqual(result["checks"]["vite_build"]["exit_code"], 0)
        for field in ("product_verified", "verified_complete",
                      "merge_authorized", "job_dispatch_authorized",
                      "release_verified", "production_browser_verified",
                      "future_head_stability_guaranteed",
                      "receipt_is_cryptographically_signed"):
            self.assertIs(result[field], False)
        self.assertEqual(result["manual_checks"], "NOT_RUN")

    def test_postflight_source_change_overrules_passed_checks(self):
        result = pilot.finalize_pilot(SHA, preflight(), steps(),
                    get=FakeGitHub(heads=(OTHER, OTHER)), clock=clock)
        self.assertEqual(result["state"], "HELD_POSTFLIGHT_SOURCE_CHANGED")
        self.assertFalse(result["automated_checks_passed"])
        self.assertFalse(result["merge_authorized"])

    def test_test_and_build_failures_are_not_green(self):
        for value, expected in [
            (steps(test=1), "FAILED_NODE_TESTS"),
            (steps(build=124), "FAILED_VITE_BUILD"),
            (steps(install=1, test=None, build=None),
             "FAILED_DEPENDENCY_INSTALL"),
        ]:
            with self.subTest(value=value):
                result = pilot.finalize_pilot(SHA, preflight(), value,
                                              get=FakeGitHub(), clock=clock)
                self.assertEqual(result["state"], expected)
                self.assertFalse(result["automated_checks_passed"])

    def test_missing_and_partial_results_are_held(self):
        for value, expected in [
            (None, "HELD_CHECKOUT_REVISION_MISMATCH_OR_MISSING"),
            (steps(checkout=OTHER),
             "HELD_CHECKOUT_REVISION_MISMATCH_OR_MISSING"),
            (steps(test=None, build=None), "HELD_INCOMPLETE_SANDBOX_RESULTS"),
        ]:
            with self.subTest(value=value):
                result = pilot.finalize_pilot(SHA, preflight(), value,
                                              get=FakeGitHub(), clock=clock)
                self.assertEqual(result["state"], expected)
                self.assertFalse(result["automated_checks_passed"])

    def test_forged_passing_preflight_flags_are_rejected(self):
        proof = preflight()
        for patch in [
            {"head_match": False}, {"repository_id": 999},
            {"requested_sha": OTHER}, {"code_executed": True},
            {"merge_authorized": True}, {"state": "HELD_IDENTITY_MISMATCH"},
            {"verified_complete": True},
        ]:
            with self.subTest(patch=patch):
                get = FakeGitHub()
                with self.assertRaisesRegex(pilot.PilotHeld, "PREFLIGHT_DID_NOT_PASS"):
                    pilot.finalize_pilot(SHA, {**proof, **patch}, steps(),
                                         get=get, clock=clock)
                self.assertEqual(get.reads, [])

    def test_bad_step_format_or_bool_exit_code_rejected(self):
        for value in [
            {"checkout_sha": SHA, "install_exit": True,
             "test_exit": 0, "build_exit": 0},
            steps(test=-1), steps(build=256),
            {**steps(), "command": "rm -rf /"},
            steps(install=1, test=0, build=0),
            steps(checkout="not-a-sha"),
        ]:
            with self.subTest(value=value):
                with self.assertRaises(pilot.PilotHeld):
                    pilot.finalize_pilot(SHA, preflight(), value,
                                         get=FakeGitHub(), clock=clock)

    def test_exclusive_nonclobbering_receipt(self):
        with tempfile.TemporaryDirectory() as name:
            target = Path(name) / "pilot-control" / "preflight.json"
            proof = preflight()
            pilot.write_new(target, proof)
            self.assertEqual(json.loads(target.read_text()), proof)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            with self.assertRaisesRegex(pilot.PilotHeld, "OUTPUT_ALREADY_EXISTS"):
                pilot.write_new(target, proof)
            self.assertEqual(json.loads(target.read_text()), proof)

    def test_symlink_output_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            prior = root / "prior.json"
            prior.write_text("unmodified", encoding="utf-8")
            link = root / "link.json"
            try:
                link.symlink_to(prior)
            except OSError:
                self.skipTest("Symlink creation unavailable")
            with self.assertRaisesRegex(pilot.PilotHeld, "OUTPUT_ALREADY_EXISTS"):
                pilot.write_new(link, preflight())
            self.assertEqual(prior.read_text(), "unmodified")

    def test_paperghost_build_is_source_known_vitest_typescript_vite(self):
        # The only executable commands are fixed npm test/build in the
        # network-disabled container, never an injected operator command.
        yaml = (Path(__file__).resolve().parents[2] / ".github" / "workflows" /
                "fleet-r08-paperghost-pilot.yml").read_text(encoding="utf-8")
        self.assertIn('case "$1" in test) npm test ;; build) npm run build', yaml)
        self.assertIn("repository: MichaelWave369/PaperGhost", yaml)
        self.assertIn("PILOT_SHA", yaml)
        self.assertNotIn("repository: ${{ inputs.repository }}", yaml)
        self.assertNotIn("${{ inputs.command }}", yaml)
        self.assertNotIn("npm install --force", yaml)
        self.assertNotIn("--privileged", yaml)
        self.assertIn("--network none", yaml)
        self.assertIn("--read-only", yaml)

    def test_paperghost_r08_schema_is_distinct_from_old_phimada_receipts(self):
        self.assertEqual(pilot.REPOSITORY, "MichaelWave369/PaperGhost")
        self.assertEqual(pilot.REPOSITORY_ID, 1443390000)
        self.assertEqual(pilot.BRANCH, "main")
        self.assertEqual(pilot.CONFIRMATION, "RUN_PAPERGHOST_TESTS")
        self.assertTrue(pilot.PREFLIGHT_SCHEMA.endswith(".v0.8"))
        self.assertTrue(pilot.RECEIPT_SCHEMA.endswith(".v0.8"))
        self.assertNotEqual(pilot.PREFLIGHT_SCHEMA,
                            "agentora.fleet.pilot-preflight.v0.6")
        self.assertNotEqual(pilot.RECEIPT_SCHEMA,
                            "agentora.fleet.pilot-check-receipt.v0.6")

    def test_no_phi_mada_receipt_reuse(self):
        prior = preflight()
        prior["schema"] = "agentora.fleet.pilot-preflight.v0.6"
        with self.assertRaisesRegex(pilot.PilotHeld,
                                    "PREFLIGHT_DID_NOT_PASS"):
            pilot.finalize_pilot(SHA, prior, steps(),
                                 get=FakeGitHub(), clock=clock)

    def test_do_not_label_paperghost_pilot_as_full_product_acceptance(self):
        result = pilot.finalize_pilot(SHA, preflight(), steps(),
                                     get=FakeGitHub(), clock=clock)
        self.assertTrue(result["automated_checks_passed"])
        self.assertIs(result["product_verified"], False)
        self.assertIs(result["verified_complete"], False)
        self.assertIs(result["release_verified"], False)
        self.assertIs(result["production_browser_verified"], False)
        self.assertIs(result["receipt_is_cryptographically_signed"], False)
        self.assertIs(result["job_dispatch_authorized"], False)
        self.assertIs(result["merge_authorized"], False)

    def test_no_operator_supplied_command_or_artifact_path(self):
        workflow = (Path(__file__).resolve().parents[2] / ".github" /
                    "workflows" / "fleet-r08-paperghost-pilot.yml").read_text(encoding="utf8")
        self.assertIn("on:\n  workflow_dispatch:", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("actions: write", workflow)
        self.assertIn("No application secrets, GITHUB_TOKEN, Docker socket", workflow)
        self.assertIn("-e HOME=/tmp -e CI=true", workflow)
        self.assertNotIn("${{ inputs.target_repository }}", workflow)
        self.assertNotIn("${{ inputs.run_script }}", workflow)

    def test_static_workflow_has_manual_only_and_networkless_runner(self):
        path = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "fleet-r08-paperghost-pilot.yml"
        yaml = path.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", yaml)
        self.assertNotIn("\n  push:", yaml)
        self.assertNotIn("\n  pull_request:", yaml)
        self.assertNotIn("\n  schedule:", yaml)
        for needle in (
            "permissions:\n  contents: read",
            "repository: MichaelWave369/PaperGhost",
            "persist-credentials: false",
            "--network none", "--read-only", "--cap-drop ALL",
            "--security-opt no-new-privileges",
            "--ignore-scripts", "RUN_PAPERGHOST_TESTS",
            "cancel-in-progress: false",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, yaml)


if __name__ == "__main__":
    unittest.main()
