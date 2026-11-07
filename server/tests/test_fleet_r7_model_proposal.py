"""R7: model output remains untrusted; Git edits and CI evidence fail closed."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r7_model_proposal as r7

NOW = datetime(2026, 11, 7, 22, 0, tzinfo=timezone.utc)
OLD = "<small>Reserved at display time</small>"
NEW = "<small>Reserved when imported</small>"


def git(root, *args):
    out = subprocess.run(["git", "-C", str(root), *args],
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


class FakeGitHub:
    def __init__(self, sha, *, live=None, private=False, archived=False, ident=None):
        self.sha = sha
        self.live = sha if live is None else live
        self.private = private
        self.archived = archived
        self.ident = r7.REPO_ID if ident is None else ident
        self.calls = []

    def __call__(self, path, token):
        self.calls.append(path)
        if path == "/repos/MichaelWave369/PhiMadaPrime":
            return {"id": self.ident, "full_name": r7.REPO,
                    "owner": {"login": "MichaelWave369"}, "private": self.private,
                    "archived": self.archived, "default_branch": "main"}
        if path == "/repos/MichaelWave369/PhiMadaPrime/branches/main":
            return {"name": "main", "commit": {"sha": self.live}}
        raise AssertionError("Unexpected GitHub endpoint: " + path)


def raw_suggestion(old=OLD, new=NEW):
    return json.dumps({"old_text": old, "new_text": new,
                       "rationale": "Clarify when the reservation snapshot was measured."})


class R7Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "source"
        (self.root / "src").mkdir(parents=True)
        self.file = self.root / r7.FILE
        self.file.write_text(
            "export function Reservations(){\n"
            "  return <section><small>Reserved at display time</small></section>;\n"
            "}\n", encoding="utf-8")
        git(self.root, "init", "-q", "-b", "main")
        git(self.root, "config", "user.name", "R7 Fixture")
        git(self.root, "config", "user.email", "fixture@example.invalid")
        git(self.root, "add", r7.FILE)
        git(self.root, "commit", "-q", "-m", "source fixture")
        self.sha = git(self.root, "rev-parse", "HEAD")
        self.get = FakeGitHub(self.sha)
        self.pre = r7.preflight(self.sha, r7.CONFIRM, get=self.get,
                                clock=lambda: NOW)
        self.proposal = r7.wrap_model_suggestion(
            raw_suggestion(), source_sha=self.sha,
            original_bytes=self.file.read_bytes(), model="qwen2.5-coder:7b")

    def apply(self, proposal=None):
        return r7.create_candidate(self.root, self.sha, self.pre,
                                   self.proposal if proposal is None else proposal)

    def finish(self, patch, candidate, *, steps=None, proposal=None, github=None):
        return r7.finalize(
            self.root, self.sha, self.pre,
            self.proposal if proposal is None else proposal,
            candidate, patch,
            steps if steps is not None else {
                "checkout_sha": self.sha, "install_exit": 0,
                "test_exit": 0, "build_exit": 0},
            get=github if github is not None else self.get,
            clock=lambda: NOW)

    def test_local_model_output_becomes_untrusted_scoped_proposal(self):
        payloads = []
        def fake_model(prompt):
            payloads.append(prompt)
            return raw_suggestion()
        out = r7.suggest_local(self.sha, self.root, self.pre,
                               "qwen2.5-coder:7b",
                               "Clarify the reservation snapshot time label.",
                               model_request=fake_model)
        self.assertEqual(out, self.proposal)
        self.assertEqual(out["source_sha"], self.sha)
        self.assertEqual(out["original_sha256"],
                         hashlib.sha256(self.file.read_bytes()).hexdigest())
        self.assertEqual(out["file"], r7.FILE)
        self.assertEqual(out["source_trust"], "UNTRUSTED_MODEL_TEXT")
        self.assertFalse(out["merge_authorized"])
        self.assertFalse(out["dispatch_authorized"])
        self.assertEqual(len(payloads), 1)
        self.assertIn("PUBLIC SOURCE FILE", payloads[0]["prompt"])
        self.assertNotIn("GITHUB_TOKEN", payloads[0]["prompt"])

    def test_apply_real_local_branch_and_reviewable_diff(self):
        patch, candidate = self.apply()
        self.assertEqual(candidate["state"], "MODEL_SUGGESTION_APPLIED_LOCALLY_FOR_REVIEW")
        self.assertEqual(candidate["changed_file_count"], 1)
        self.assertEqual(candidate["source_files_pushed"], 0)
        self.assertEqual(candidate["pull_requests_created"], 0)
        self.assertTrue(candidate["candidate_branch"].startswith("r7/proposal-"))
        self.assertEqual(git(self.root, "branch", "--show-current"),
                         candidate["candidate_branch"])
        self.assertEqual(git(self.root, "diff", "--name-only"), r7.FILE)
        self.assertIn(NEW.encode(), patch)
        self.assertIn(OLD.encode(), patch)
        out = self.finish(patch, candidate)
        self.assertEqual(out["state"], "FIXED_AUTOMATED_CHECKS_REPORTED_PASSED_AT_SHA")
        self.assertTrue(out["manual_code_review_required"])
        self.assertTrue(out["model_output_is_untrusted"])
        for key in ("merge_authorized", "release_verified", "product_verified",
                    "verified_complete", "dispatch_authorized",
                    "independent_reproduction_performed"):
            self.assertIs(out[key], False)
        self.assertEqual(out["source_files_pushed"], 0)

    def test_refuse_forged_authority_or_other_repository_file_source(self):
        changes = [
            ("repository", "MichaelWave369/PhiOS"),
            ("repository_id", 1),
            ("file", "../other.py"),
            ("source_sha", "f" * 40),
            ("dispatch_authorized", True),
            ("merge_authorized", True),
            ("source_trust", "TRUSTED"),
            ("operation", "shell"),
            ("original_sha256", "f" * 64),
        ]
        for key, value in changes:
            with self.subTest(key=key), self.assertRaises(r7.ProposalHeld):
                self.apply({**self.proposal, key: value})
        self.assertEqual(git(self.root, "branch", "--show-current"), "main")
        self.assertEqual(git(self.root, "status", "--porcelain"), "")

    def test_replacement_anchors_must_be_unique_small_and_real(self):
        for old, new in [
            ("missing", "replacement"),
            ("", "blank"),
            (OLD, OLD),
            (OLD, "x" * 3000),
            (OLD, "line1\r\nline2"),
            (OLD, "ok\x00bad"),
        ]:
            with self.subTest(old=old, new=new[:24]):
                with self.assertRaises(r7.ProposalHeld):
                    self.apply({**self.proposal, "old_text": old, "new_text": new})
        duplicated = OLD + "\n" + OLD
        self.file.write_text(duplicated, encoding="utf-8")
        git(self.root, "add", r7.FILE)
        git(self.root, "commit", "-q", "-m", "double label")
        newsha = git(self.root, "rev-parse", "HEAD")
        prop = {**self.proposal, "source_sha": newsha,
                "original_sha256": hashlib.sha256(self.file.read_bytes()).hexdigest()}
        pre = {**self.pre, "source_sha": newsha}
        with self.assertRaisesRegex(r7.ProposalHeld, "REPLACEMENT_NOT_UNIQUE"):
            r7.create_candidate(self.root, newsha, pre, prop)

    def test_malicious_json_and_confused_model_claims_are_rejected(self):
        with self.assertRaisesRegex(r7.ProposalHeld, "DUPLICATE_JSON_KEY"):
            r7.decode_json(b'{"a":1,"a":2}')
        with self.assertRaises(r7.ProposalHeld):
            r7.decode_json(b"{}" * 5000)
        with self.assertRaisesRegex(r7.ProposalHeld, "MODEL_REPLY_FIELDS"):
            r7.wrap_model_suggestion(
                json.dumps({"old_text": OLD, "new_text": NEW,
                            "rationale": "For display.",
                            "merge_authorized": True}),
                source_sha=self.sha,
                original_bytes=self.file.read_bytes(), model="qwen3:4b")
        with self.assertRaises(r7.ProposalHeld):
            r7.suggest_local(self.sha, self.root, self.pre, "../../evil",
                             "Change the reservation label to something clearer.",
                             model_request=lambda _: raw_suggestion())

    def test_changed_checkout_refused_and_symlink_never_followed(self):
        self.file.write_text("unexpected working tree edit", encoding="utf-8")
        with self.assertRaisesRegex(r7.r6.CandidateHeld, "CHECKOUT_NOT_CLEAN"):
            self.apply()
        self.file.unlink()
        other = self.root.parent / "secret"
        other.write_text(OLD, encoding="utf-8")
        self.file.symlink_to(other)
        with self.assertRaisesRegex(r7.r6.CandidateHeld, "CHECKOUT_NOT_CLEAN"):
            self.apply()
        self.assertEqual(other.read_text(), OLD)

    def test_postflight_patch_digest_scope_and_branch_are_independent(self):
        patch, candidate = self.apply()
        forged = {**candidate, "merge_authorized": True}
        with self.assertRaisesRegex(r7.ProposalHeld, "CANDIDATE_CLAIMS"):
            self.finish(patch, forged)
        with self.assertRaisesRegex(r7.ProposalHeld, "PROPOSAL_OR_PATCH"):
            self.finish(patch + b"forged", candidate)
        alternate = {**self.proposal, "rationale": "More marketing-friendly terminology."}
        with self.assertRaisesRegex(r7.ProposalHeld, "PROPOSAL_OR_PATCH"):
            self.finish(patch, candidate, proposal=alternate)
        self.file.write_text(self.file.read_text(encoding="utf-8") + "// alteration\n")
        with self.assertRaisesRegex(r7.ProposalHeld, "REVIEWED_CANDIDATE"):
            self.finish(patch, candidate)

    def test_out_of_scope_modification_and_source_drift_fail(self):
        other = self.root / "src" / "other.js"
        other.write_text("initial", encoding="utf-8")
        git(self.root, "add", "src/other.js")
        git(self.root, "commit", "-q", "-m", "second source")
        self.sha = git(self.root, "rev-parse", "HEAD")
        self.pre["source_sha"] = self.sha
        self.proposal["source_sha"] = self.sha
        patch, candidate = self.apply()
        other.write_text("altered", encoding="utf-8")
        with self.assertRaisesRegex(r7.r6.CandidateHeld, "OUT_OF_SCOPE"):
            self.finish(patch, candidate)

    def test_failed_checks_never_green_and_sha_drift_holds(self):
        patch, candidate = self.apply()
        out = self.finish(patch, candidate, steps={
            "checkout_sha": self.sha, "install_exit": 0,
            "test_exit": 1, "build_exit": 0})
        self.assertEqual(out["state"], "CANDIDATE_CHECKS_FAILED_OR_INCOMPLETE")
        self.assertFalse(out["merge_authorized"])
        with self.assertRaisesRegex(r7.ProposalHeld, "POSTFLIGHT_HEAD_CHANGED"):
            self.finish(patch, candidate,
                        github=FakeGitHub(self.sha, live="f"*40))
        with self.assertRaisesRegex(r7.ProposalHeld, "CHECKOUT_OR_STEPS"):
            self.finish(patch, candidate, steps={
                "checkout_sha": "f" * 40, "install_exit": 0,
                "test_exit": 0, "build_exit": 0})

    def test_preflight_refuses_nonpublic_stale_or_wrong_source(self):
        for getter in (FakeGitHub(self.sha, private=True),
                       FakeGitHub(self.sha, archived=True),
                       FakeGitHub(self.sha, ident=123),
                       FakeGitHub(self.sha, live="f"*40)):
            with self.subTest(getter=getter), self.assertRaises(r7.ProposalHeld):
                r7.preflight(self.sha, r7.CONFIRM, get=getter,
                             clock=lambda: NOW)
        with self.assertRaisesRegex(r7.ProposalHeld, "OPERATOR_OPT_IN"):
            r7.preflight(self.sha, "please do it", get=self.get)
        with self.assertRaisesRegex(r7.ProposalHeld, "SOURCE_SHA"):
            r7.preflight("main", r7.CONFIRM, get=self.get)

    def test_manual_workflow_and_no_git_write_powers(self):
        path = (Path(__file__).resolve().parents[2] /
                ".github/workflows/fleet-r7-phimada-model-proposal.yml")
        source = path.read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch:", source)
        self.assertIn("contents: read", source)
        self.assertNotIn("contents: write", source)
        self.assertNotIn("pull_request:", source)
        self.assertNotIn("schedule:", source)
        self.assertIn("--network none", source)
        self.assertIn("--ignore-scripts", source)
        self.assertIn("persist-credentials: false", source)
        self.assertNotIn("git push", source)
        self.assertNotIn("gh pr create", source)
        self.assertIn("proposal_b64", source)


if __name__ == "__main__":
    unittest.main()
