"""R8: genuine GitHub artifact audit and explicit draft-only PR publication tests."""
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r7_model_proposal as r7
import fleet_r8_independent_review as r8
import fleet_r8_reviewed_pr_publisher as pub

NOW = datetime(2026, 11, 7, 23, 30, tzinfo=timezone.utc)
START = NOW - timedelta(minutes=30)
END = NOW - timedelta(minutes=20)
PRE = NOW - timedelta(minutes=27)
POST = NOW - timedelta(minutes=22)
SOURCE_SHA = "a" * 40
CONTROLLER_SHA = "c" * 40
RUN_ID = 1234567
ORIGINAL = (
    "export function RepoNervePanel() {\n"
    "  return <div><small>Reserved at display time</small></div>;\n"
    "}\n"
).encode("utf-8")


def record_zip(*, mutate=None):
    old, new = "<small>Reserved at display time</small>", "<small>Reserved when imported</small>"
    proposed = ORIGINAL.decode().replace(old, new).encode()
    patch = "".join(r8.difflib.unified_diff(
        ORIGINAL.decode().splitlines(keepends=True),
        proposed.decode().splitlines(keepends=True),
        fromfile="a/" + r7.FILE, tofile="b/" + r7.FILE,
    )).encode("utf-8")
    proposal = {
        "schema": r7.SCHEMA, "repository": r7.REPO, "repository_id": r7.REPO_ID,
        "source_sha": SOURCE_SHA, "file": r7.FILE,
        "original_sha256": r8.digest(ORIGINAL),
        "operation": "replace_once", "old_text": old, "new_text": new,
        "rationale": "Clarify when the reservation snapshot was measured.",
        "model_label": "qwen2.5-coder:7b",
        "source_trust": "UNTRUSTED_MODEL_TEXT",
        "dispatch_authorized": False, "merge_authorized": False,
    }
    proposal_hash = r8.digest(r7.canonical(proposal))
    patch_hash = r8.digest(patch)
    candidate_hash = r8.digest(proposed)
    branch = "r7/proposal-" + SOURCE_SHA[:12] + "-" + proposal_hash[:10]
    preflight = {
        "schema": r7.PREFLIGHT, "state": "SOURCE_HEAD_MATCH_OBSERVED",
        "repository": r7.REPO, "repository_id": r7.REPO_ID,
        "source_sha": SOURCE_SHA, "observed_utc": PRE.isoformat(),
        "mission": r7.MISSION, "dispatch_authorized": False,
        "merge_authorized": False, "verified_complete": False,
    }
    candidate = {
        "schema": r7.CANDIDATE,
        "state": "MODEL_SUGGESTION_APPLIED_LOCALLY_FOR_REVIEW",
        "repository": r7.REPO, "repository_id": r7.REPO_ID,
        "source_sha": SOURCE_SHA, "file": r7.FILE, "mission": r7.MISSION,
        "candidate_branch": branch, "proposal_sha256": proposal_hash,
        "original_sha256": r8.digest(ORIGINAL),
        "candidate_sha256": candidate_hash, "patch_sha256": patch_hash,
        "changed_file_count": 1, "source_files_pushed": 0,
        "pull_requests_created": 0, "merge_authorized": False,
        "verified_complete": False,
    }
    steps = {"checkout_sha": SOURCE_SHA, "install_exit": 0,
             "test_exit": 0, "build_exit": 0}
    final = {
        "schema": r7.FINAL,
        "state": "FIXED_AUTOMATED_CHECKS_REPORTED_PASSED_AT_SHA",
        "repository": r7.REPO, "repository_id": r7.REPO_ID,
        "source_sha": SOURCE_SHA, "file": r7.FILE,
        "proposal_sha256": proposal_hash, "candidate_sha256": candidate_hash,
        "patch_sha256": patch_hash, "candidate_branch": branch,
        "reported_checks": {"install_exit": 0, "test_exit": 0, "build_exit": 0},
        "postflight_observed_utc": POST.isoformat(),
        "model_output_is_untrusted": True,
        "independent_reproduction_performed": False,
        "manual_code_review_required": True,
        "source_files_pushed": 0, "pull_requests_created": 0,
        "release_verified": False, "product_verified": False,
        "verified_complete": False, "dispatch_authorized": False,
        "merge_authorized": False,
    }
    records = {
        "preflight.json": preflight, "proposal.json": proposal,
        "candidate.json": candidate, "steps.json": steps, "final.json": final,
        "patch.diff": patch,
    }
    if mutate:
        mutate(records)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name, value in records.items():
            z.writestr("r7-review/" + name, value if type(value) is bytes else
                       json.dumps(value).encode())
    return stream.getvalue(), patch_hash, proposed


class FakeGitHub:
    def __init__(self, raw):
        self.archive = raw
        self.calls = []
        self.head = SOURCE_SHA
        self.controller = CONTROLLER_SHA
        self.run_status = "completed"
        self.run_conclusion = "success"
        self.run_path = r8.RUN_WORKFLOW
        self.artifact_digest = "sha256:" + r8.digest(raw)
        self.file = ORIGINAL
        self.reponame = r7.REPO
        self.priv = False

    def __call__(self, path, token=None):
        self.calls.append((path, token))
        base = "/repos/" + r8.AGENTORA + "/actions/runs/" + str(RUN_ID)
        if path == base:
            return {
                "id": RUN_ID, "event": "workflow_dispatch",
                "path": self.run_path, "status": self.run_status,
                "conclusion": self.run_conclusion, "run_attempt": 1,
                "head_sha": self.controller,
                "repository": {"id": r8.AGENTORA_ID, "full_name": r8.AGENTORA},
                "head_repository": {"full_name": r8.AGENTORA},
                "created_at": START.isoformat(), "updated_at": END.isoformat(),
            }
        if path == base + "/artifacts?per_page=100":
            return {
                "total_count": 1, "artifacts": [{
                    "id": 765, "name": r8.ARTIFACT_PREFIX + str(RUN_ID),
                    "expired": False, "size_in_bytes": len(self.archive),
                    "digest": self.artifact_digest,
                    "workflow_run": {"id": RUN_ID},
                }],
            }
        if path == "/repos/MichaelWave369/PhiMadaPrime":
            return {
                "id": r7.REPO_ID, "full_name": self.reponame,
                "owner": {"login": "MichaelWave369"},
                "private": self.priv, "archived": False,
                "default_branch": "main",
            }
        if path == "/repos/MichaelWave369/PhiMadaPrime/branches/main":
            return {"name": "main", "commit": {"sha": self.head}}
        if path == ("/repos/MichaelWave369/PhiMadaPrime/contents/"
                    "src/reponerve.jsx?ref=" + SOURCE_SHA):
            return {
                "type": "file", "path": r7.FILE, "encoding": "base64",
                "size": len(self.file),
                "content": base64.b64encode(self.file).decode(),
                "sha": hashlib.sha1(
                    b"blob " + str(len(self.file)).encode() + b"\0" +
                    self.file).hexdigest(),
            }
        raise AssertionError("Unexpected API GET: " + path)


class Writer:
    def __init__(self):
        self.calls = []
        self.break_on = None

    def __call__(self, path, method, data, token):
        self.calls.append((path, method, data, token))
        if self.break_on == path:
            raise TimeoutError("outcome unknown")
        if path == pub.REF_PATH:
            return (201, {"ref": data["ref"]})
        if path == pub.CONTENT_PATH:
            return (200, {"content": {"path": r7.FILE}})
        if path == pub.PULL_PATH:
            return (201, {"number": 218, "draft": True, "state": "open",
                          "html_url": "https://github.com/" + pub.REPO + "/pull/218"})
        raise AssertionError("Unexpected write")


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.patch_sha, self.revised = record_zip()
        self.github = FakeGitHub(self.raw)
        self.writer = Writer()
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.ledger_path = Path(temp.name) / "private" / "handoffs.sqlite3"

    def audit(self, *, github=None, raw=None):
        return r8.review(RUN_ID, self.raw if raw is None else raw,
                         CONTROLLER_SHA, get=github or self.github,
                         clock=lambda: NOW)

    def publish(self, *, execute=False, request_id="r8-first",
                reviewed_patch_sha256=None, confirmation=None,
                github=None, writer=None, raw=None, **kwargs):
        return pub.publish(
            RUN_ID, self.raw if raw is None else raw,
            CONTROLLER_SHA, request_id=request_id,
            reviewed_patch_sha256=reviewed_patch_sha256,
            execute=execute, confirmation=confirmation,
            get=github or self.github, writer=writer or self.writer,
            journal_path=self.ledger_path, clock=lambda: NOW, **kwargs)

    def test_github_evidence_review_is_independent_and_non_authorizing(self):
        report, revised = self.audit()
        self.assertEqual(revised, self.revised)
        self.assertEqual(report["state"],
                         "GITHUB_R7_PATCH_CORROBORATED_REVIEW_REQUIRED")
        self.assertTrue(report["archive_digest_correlated"])
        self.assertTrue(report["independent_patch_reconstruction"])
        self.assertEqual(report["patch_sha256"], self.patch_sha)
        self.assertEqual(report["source_sha"], SOURCE_SHA)
        for flag in ("merge_authorized", "verified_complete", "product_verified",
                     "publication_authorized", "signed_attestation"):
            self.assertIs(report[flag], False)

    def test_default_dry_run_has_zero_writes_and_no_journal(self):
        report = self.publish()
        self.assertEqual(report["state"], "DRY_RUN_VERIFIED_NOT_PUBLISHED")
        self.assertFalse(report["github_writes_attempted"])
        self.assertIsNone(report["draft_pr_number"])
        self.assertFalse(self.ledger_path.exists())
        self.assertEqual(self.writer.calls, [])

    def test_reviewed_exact_sha_can_publish_one_draft_pr_only(self):
        report = self.publish(
            execute=True, confirmation=pub.CONFIRM,
            reviewed_patch_sha256=self.patch_sha, token="private-test-token")
        self.assertEqual(report["state"], "DRAFT_PR_CREATED_AWAITING_REVIEW")
        self.assertEqual(report["draft_pr_number"], 218)
        self.assertFalse(report["merge_authorized"])
        self.assertEqual(len(self.writer.calls), 3)
        ref, put, pr = [x[2] for x in self.writer.calls]
        self.assertEqual(ref["sha"], SOURCE_SHA)
        self.assertEqual(ref["ref"], "refs/heads/" + report["branch"])
        self.assertEqual(base64.b64decode(put["content"]), self.revised)
        self.assertEqual(put["sha"], report["source_blob_sha"] if
                         "source_blob_sha" in report else
                         self.audit()[0]["source_blob_sha"])
        self.assertTrue(pr["draft"])
        self.assertEqual(pr["base"], "main")
        self.assertNotIn("private-test-token", json.dumps(report))
        with pub.PublishLedger(self.ledger_path).transaction() as db:
            rows = db.execute("SELECT * FROM r8_attempts").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "DRAFT_PR_CREATED_AWAITING_REVIEW")
        with self.assertRaisesRegex(pub.PublishHeld, "ALREADY_ATTEMPTED"):
            self.publish(execute=True, confirmation=pub.CONFIRM,
                         reviewed_patch_sha256=self.patch_sha,
                         token="private-test-token")
        self.assertEqual(len(self.writer.calls), 3)

    def test_operator_approval_is_separate_from_worker_result(self):
        for arguments in (
            {"confirmation": "yes", "reviewed_patch_sha256": self.patch_sha},
            {"confirmation": None, "reviewed_patch_sha256": self.patch_sha},
            {"confirmation": pub.CONFIRM, "reviewed_patch_sha256": "f"*64},
            {"confirmation": pub.CONFIRM, "reviewed_patch_sha256": None},
            {"confirmation": pub.CONFIRM, "reviewed_patch_sha256": self.patch_sha,
             "token": None},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(pub.PublishHeld):
                self.publish(execute=True, **arguments)
        self.assertFalse(self.ledger_path.exists())
        self.assertFalse(self.writer.calls)

    def test_bad_github_run_workflow_identity_and_controller_sha_held(self):
        for key, value in (
            ("run_status", "in_progress"), ("run_conclusion", "failure"),
            ("run_path", ".github/workflows/other.yml"),
            ("controller", "f"*40),
        ):
            fake = FakeGitHub(self.raw)
            setattr(fake, key, value)
            with self.subTest(key=key), self.assertRaises(r8.ReviewHeld):
                self.audit(github=fake)

    def test_artifact_digest_mismatch_or_tamper_refused(self):
        changed = bytearray(self.raw)
        changed[-6] ^= 1
        with self.assertRaisesRegex(r8.ReviewHeld, "GITHUB_ARTIFACT_DIGEST"):
            self.audit(raw=bytes(changed))
        fake = FakeGitHub(self.raw)
        fake.artifact_digest = "sha256:" + "f"*64
        with self.assertRaisesRegex(r8.ReviewHeld, "GITHUB_ARTIFACT_DIGEST"):
            self.audit(github=fake)

    def test_source_revision_change_private_repo_or_file_mismatch_held(self):
        for attr, value in (("head", "d"*40), ("priv", True),
                            ("reponame", "MichaelWave369/Other"),
                            ("file", b"replaced")):
            fake = FakeGitHub(self.raw)
            setattr(fake, attr, value)
            with self.subTest(attr=attr), self.assertRaises((
                r8.ReviewHeld, r8.pilot.PilotHeld, r7.ProposalHeld
            )):
                self.audit(github=fake)

    def test_forged_receipts_and_failed_tests_cannot_publish(self):
        variants = [
            lambda a: a["final.json"].update(merge_authorized=True),
            lambda a: a["final.json"].update(product_verified=True),
            lambda a: a["steps.json"].update(test_exit=1),
            lambda a: a["candidate.json"].update(file="../private.py"),
            lambda a: a["proposal.json"].update(source_sha="f"*40),
            lambda a: a["proposal.json"].update(merge_authorized=True),
            lambda a: a["final.json"].update(patch_sha256="f"*64),
        ]
        for mutate in variants:
            raw, _, _ = record_zip(mutate=mutate)
            fake = FakeGitHub(raw)
            with self.subTest(mutate=mutate), self.assertRaises((
                r8.ReviewHeld, r7.ProposalHeld, ValueError
            )):
                self.audit(github=fake, raw=raw)
        self.assertEqual(self.writer.calls, [])

    def test_unknown_write_outcome_never_retries_and_does_not_claim_pr(self):
        self.writer.break_on = pub.CONTENT_PATH
        with self.assertRaisesRegex(pub.PublishHeld, "RECONCILE"):
            self.publish(execute=True, confirmation=pub.CONFIRM,
                         reviewed_patch_sha256=self.patch_sha,
                         token="private-test-token")
        with pub.PublishLedger(self.ledger_path).transaction() as db:
            saved = db.execute("SELECT state FROM r8_attempts").fetchone()
        self.assertEqual(saved["state"], "BRANCH_CREATED_NOT_PR")
        with self.assertRaisesRegex(pub.PublishHeld, "ALREADY_ATTEMPTED"):
            self.publish(execute=True, request_id="r8-again",
                         confirmation=pub.CONFIRM,
                         reviewed_patch_sha256=self.patch_sha,
                         token="private-test-token")
        self.assertEqual(len(self.writer.calls), 2)

    def test_fixed_write_endpoint_allowlist(self):
        with self.assertRaisesRegex(pub.PublishHeld, "GITHUB_WRITE_PATH_REFUSED"):
            pub.github_write("/repos/MichaelWave369/PhiOS/pulls", "POST", {},
                             "token")
        with self.assertRaisesRegex(r8.ReviewHeld, "GITHUB_READ_ENDPOINT_REFUSED"):
            r8.fixed_get("/repos/MichaelWave369/PhiOS")

    def test_unique_archive_members_only(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            z.writestr("r7-review/../private.key", "invalid")
        with self.assertRaises(r8.ReviewHeld):
            r8.read_zip(stream.getvalue())


if __name__ == "__main__":
    unittest.main()
