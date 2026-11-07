"""R6 code candidate: exact SHA, fixed single-file edit, no GitHub writes."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r6_code_candidate as candidate

NOW = datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc)


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip()


class PublicGithub:
    def __init__(self, sha, *, live_sha=None, archived=False, private=False):
        self.sha = sha
        self.live_sha = live_sha or sha
        self.archived = archived
        self.private = private
        self.requests = []

    def __call__(self, path, token):
        self.requests.append(path)
        if path == "/repos/MichaelWave369/PhiMadaPrime":
            return {
                "id": candidate.REPO_ID, "full_name": candidate.REPO,
                "owner": {"login": "MichaelWave369"},
                "default_branch": "main", "private": self.private,
                "archived": self.archived,
            }
        if path == "/repos/MichaelWave369/PhiMadaPrime/branches/main":
            return {"name": "main", "commit": {"sha": self.live_sha}}
        raise AssertionError("Unexpected GitHub path " + path)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "candidate-src"
        (self.root / "src").mkdir(parents=True)
        self.path = self.root / candidate.FILE
        self.path.write_text(
            "function Panel() {\n"
            "  return <div><small>Reserved at display time</small></div>;\n"
            "}\n", encoding="utf-8")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "Fleet Fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "add", "src/reponerve.jsx")
        git(self.root, "commit", "-q", "-m", "source")
        self.sha = git(self.root, "rev-parse", "HEAD")
        self.get = PublicGithub(self.sha)
        self.pre = candidate.preflight(
            self.sha, candidate.CONFIRM, get=self.get,
            clock=lambda: NOW)
        self.assertEqual(self.pre["state"], "SOURCE_HEAD_MATCH_OBSERVED")

    def apply(self):
        return candidate.create_candidate(self.root, self.sha, self.pre)

    def finalize(self, patch, info, *, get=None, steps=None):
        return candidate.finalize(
            self.sha, self.root, self.pre, info, patch,
            steps or {"checkout_sha": self.sha,
                      "install_exit": 0, "test_exit": 0, "build_exit": 0},
            get=get or self.get, clock=lambda: NOW)

    def test_writes_one_bounded_patch_and_verifies_all_fixed_checks(self):
        original = self.path.read_bytes()
        patch, info = self.apply()
        self.assertEqual(info["file"], "src/reponerve.jsx")
        self.assertEqual(info["changed_file_count"], 1)
        self.assertEqual(info["patch_sha256"], hashlib.sha256(patch).hexdigest())
        self.assertIn(b"Reserved when imported", patch)
        self.assertIn(b"Reserved at display time", patch)
        self.assertEqual(info["original_sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(git(self.root, "diff", "--name-only"), candidate.FILE)
        result = self.finalize(patch, info)
        self.assertEqual(result["state"], "CANDIDATE_AUTOMATED_CHECKS_PASSED_AT_SHA")
        self.assertEqual(result["checks"]["node_tests"], 0)
        self.assertEqual(result["source_files_pushed"], 0)
        self.assertEqual(result["pull_requests_created"], 0)
        for field in ("merge_authorized","verified_complete","product_verified",
                      "signed_attestation","release_verified"):
            self.assertIs(result[field],False)
        self.assertTrue(result["manual_review_required"])

    def test_wrong_identity_and_HEAD_are_rejected_before_edit(self):
        for get in (PublicGithub(self.sha, live_sha="f"*40),
                    PublicGithub(self.sha, archived=True),
                    PublicGithub(self.sha, private=True)):
            with self.subTest(get=get), self.assertRaises(candidate.CandidateHeld):
                candidate.preflight(self.sha, candidate.CONFIRM, get=get,
                                    clock=lambda: NOW)
        with self.assertRaisesRegex(candidate.CandidateHeld,"MANUAL_MISSION"):
            candidate.preflight(self.sha,"yes",get=self.get)
        with self.assertRaisesRegex(candidate.CandidateHeld,"EXACT_SHA"):
            candidate.preflight("main",candidate.CONFIRM,get=self.get)

    def test_already_fixed_missing_or_ambiguous_anchor_holds(self):
        for contents in ("missing", candidate.BEFORE+"\n"+candidate.BEFORE,
                         candidate.AFTER):
            with self.subTest(contents=contents):
                self.path.write_text(contents+"\n", encoding="utf-8")
                git(self.root, "add", candidate.FILE)
                git(self.root, "commit", "-q", "-m", "different")
                self.sha = git(self.root, "rev-parse", "HEAD")
                self.pre["source_sha"] = self.sha
                with self.assertRaisesRegex(candidate.CandidateHeld,"PATCH_ANCHOR"):
                    self.apply()

    def test_dirty_checkout_or_wrong_commit_holds(self):
        self.path.write_text("dirty",encoding="utf-8")
        with self.assertRaisesRegex(candidate.CandidateHeld,"CHECKOUT_NOT_CLEAN"):
            self.apply()
        with self.assertRaisesRegex(candidate.CandidateHeld,"CHECKOUT_SHA"):
            candidate.create_candidate(self.root,"f"*40,
                                       {**self.pre,"source_sha":"f"*40})

    def test_symlink_target_rejected(self):
        self.path.unlink()
        remote = Path(self.root.parent) / "external.txt"
        remote.write_text(candidate.BEFORE,encoding="utf-8")
        self.path.symlink_to(remote)
        with self.assertRaisesRegex(candidate.CandidateHeld,"TARGET_FILE_UNSAFE"):
            self.apply()
        self.assertEqual(remote.read_text(),candidate.BEFORE)

    def test_tampering_patch_receipt_or_edited_file_fails(self):
        patch, info = self.apply()
        with self.assertRaisesRegex(candidate.CandidateHeld,"PATCH_DIGEST"):
            self.finalize(patch+b"forged",info)
        changed = {**info,"merge_authorized":True}
        with self.assertRaisesRegex(candidate.CandidateHeld,"CANDIDATE_CLAIMS"):
            self.finalize(patch,changed)
        self.path.write_text(self.path.read_text()+"// edited outside scope\n")
        with self.assertRaisesRegex(candidate.CandidateHeld,"CANDIDATE_DRIFT"):
            self.finalize(patch,info)

    def test_out_of_scope_tracked_modifications_fail_postflight(self):
        other = self.root / "src" / "other.js"
        other.write_text("first",encoding="utf-8")
        git(self.root,"add","src/other.js")
        git(self.root,"commit","-q","-m","add other")
        self.sha = git(self.root,"rev-parse","HEAD")
        self.pre["source_sha"] = self.sha
        patch, info = self.apply()
        other.write_text("modified",encoding="utf-8")
        with self.assertRaisesRegex(candidate.CandidateHeld,"OUT_OF_SCOPE"):
            self.finalize(patch,info)

    def test_failed_or_incomplete_checks_not_green(self):
        patch, info = self.apply()
        for steps in (
            {"checkout_sha":self.sha,"install_exit":0,"test_exit":1,"build_exit":0},
            {"checkout_sha":self.sha,"install_exit":1,"test_exit":None,"build_exit":None},
            {"checkout_sha":self.sha,"install_exit":0,"test_exit":None,"build_exit":0},
        ):
            with self.subTest(steps=steps):
                result = self.finalize(patch,info,steps=steps)
                self.assertEqual(result["state"],"CANDIDATE_CHECKS_INCOMPLETE_OR_FAILED")
                self.assertFalse(result["merge_authorized"])

    def test_source_move_between_candidate_and_final_holds(self):
        patch, info = self.apply()
        with self.assertRaisesRegex(candidate.CandidateHeld,"POSTFLIGHT_HEAD_DRIFT"):
            self.finalize(patch,info,
                          get=PublicGithub(self.sha,live_sha="a"*40))

    def test_workflow_is_manual_read_only_and_no_credentials_in_sandbox(self):
        workflow = (Path(__file__).resolve().parents[2] /
                    ".github/workflows/fleet-r6-phimada-candidate.yml").read_text()
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull_request:", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertIn("--network none", workflow)
        self.assertIn("--cap-drop ALL", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("--ignore-scripts", workflow)
        self.assertIn("candidate-control/patch.diff",workflow)
        self.assertNotIn("git push",workflow)
        self.assertNotIn("gh pr create",workflow)


if __name__ == "__main__":
    unittest.main()
