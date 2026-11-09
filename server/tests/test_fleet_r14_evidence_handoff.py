"""R14: genuine R13 run-to-mission correlation and owner acknowledgement."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "server/tests"))
import fleet_r12_github_missions as r12
import fleet_r13_readonly_audit as worker
import fleet_r13_independent_qa as qa
import fleet_r14_evidence_handoff as r14
from test_fleet_r13_hosted_audit_qa import (
    GitHub as R13GitHub, archive, RUN as AUDIT_RUN,
    NOW, ISSUE, TARGET,
)

QA_RUN = 700008
QA_ARTIFACT = 990023


class GitHub(R13GitHub):
    def __init__(self):
        super().__init__()
        self.init_mission()
        self.head_reads = 0
        self.qa_run = {
            "id": QA_RUN, "path": r14.QA_WORKFLOW,
            "event": "workflow_run", "status": "completed",
            "conclusion": "success", "run_attempt": 1,
            "head_branch": "main",
            "created_at": (NOW - timedelta(minutes=1)).isoformat(),
            "repository": {"full_name": r12.HOME},
            "actor": {"login": r12.OWNER},
        }
        audit = worker.audit(ISSUE, actor=r12.OWNER,
                             confirmation=worker.CONFIRM,
                             token="read-token", get=self.get)
        self.artifact_for(audit)
        result = qa.review(AUDIT_RUN, token="read-token", get=self.get,
                           download=self.download, now=NOW)
        self.qa_zip = archive(result)
        self.qa_artifacts = {"total_count": 1, "artifacts": [{
            "id": QA_ARTIFACT, "name": "fleet-r13-qa-" + str(QA_RUN),
            "size_in_bytes": len(self.qa_zip),
            "digest": "sha256:" + hashlib.sha256(self.qa_zip).hexdigest(),
            "expired": False, "workflow_run": {"id": QA_RUN},
        }]}
        self.head_reads = 0

    def get(self, path, token):
        if path == "/repos/" + r12.HOME + "/actions/runs/" + str(QA_RUN):
            return deepcopy(self.qa_run)
        if path == ("/repos/" + r12.HOME + "/actions/runs/" + str(QA_RUN)
                    + "/artifacts?per_page=100"):
            return deepcopy(self.qa_artifacts)
        return super().get(path, token)

    def download(self, artifact_id, token):
        if artifact_id == QA_ARTIFACT:
            return self.qa_zip
        if artifact_id == 990022:
            return self.audit_zip
        raise AssertionError("unexpected artifact id")

    def regenerate_qa(self, payload):
        self.qa_zip = archive(payload)
        art = self.qa_artifacts["artifacts"][0]
        art["digest"] = "sha256:" + hashlib.sha256(self.qa_zip).hexdigest()
        art["size_in_bytes"] = len(self.qa_zip)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.gh = GitHub()

    def correlate(self, **overrides):
        return r14.correlate(
            ISSUE, overrides.get("audit_run", AUDIT_RUN),
            overrides.get("qa_run", QA_RUN), token="read-token",
            get=self.gh.get, download=self.gh.download,
            now=overrides.get("now", NOW))

    def command(self, command="link", **options):
        return r14.transition(
            ISSUE, command, options.get("audit_run", AUDIT_RUN),
            options.get("qa_run", QA_RUN),
            confirmation=options.get("confirmation",
                 r14.CONFIRM_LINK if command == "link" else r14.CONFIRM_REVIEW),
            actor=options.get("actor", r12.OWNER), token="read-token",
            get=self.gh.get, post=self.gh.post, download=self.gh.download,
            now=options.get("now", NOW))

    def test_two_original_artifacts_verified_and_exact_issue_correlated(self):
        receipt = self.correlate()
        self.assertEqual(receipt["mission_issue"], ISSUE)
        self.assertEqual(receipt["target_repository"], TARGET)
        self.assertEqual(receipt["audit_run_id"], AUDIT_RUN)
        self.assertEqual(receipt["qa_run_id"], QA_RUN)
        self.assertEqual(receipt["audit_artifact_sha256"],
                         hashlib.sha256(self.gh.audit_zip).hexdigest())
        self.assertEqual(receipt["qa_artifact_sha256"],
                         hashlib.sha256(self.gh.qa_zip).hexdigest())
        self.assertEqual(receipt["source_sha"], "a" * 40)
        self.assertFalse(receipt["default_branch_protected"])
        self.assertFalse(receipt["branch_protection_gate_passed"])
        self.assertTrue(receipt["code_write_blocked"])
        self.assertEqual(len(self.gh.posts), 2)  # R12 setup only.

    def test_owner_link_then_distinct_review_acknowledgment(self):
        first = self.command()
        self.assertEqual(first["state"], r14.PHASE_EVIDENCE)
        self.assertFalse(first["owner_acknowledged"])
        self.assertFalse(first["independent_human_qa_complete"])
        self.assertFalse(first["merge_authorized"])
        self.assertEqual(first["comment_id"], 9003)
        second = self.command("acknowledge")
        self.assertEqual(second["state"], r14.PHASE_ACK)
        self.assertTrue(second["owner_acknowledged"])
        self.assertFalse(second["independent_human_qa_complete"])
        self.assertFalse(second["merge_authorized"])
        self.assertTrue(second["code_write_blocked"])
        self.assertEqual(second["comment_id"], 9004)
        issue_digest = first["issue_sha256"]
        saved = r14.history(self.gh.get, "read-token", ISSUE, issue_digest)
        self.assertEqual([x["seq"] for x in saved], [1, 2])
        self.assertEqual([x["state"] for x in saved],
                         [r14.PHASE_EVIDENCE, r14.PHASE_ACK])
        self.assertNotIn("read-token", json.dumps(self.gh.posts))
        self.assertIn("Code writes: **BLOCKED**", r14.summary(second))

    def test_no_owner_confirmation_no_api_reads_or_comments(self):
        before = len(self.gh.calls)
        for opts in ({"actor": "stranger"},
                     {"confirmation": "yes"},
                     {"actor": None}):
            with self.subTest(opts=opts), self.assertRaisesRegex(
                    r12.MissionHeld, "R14_EXPLICIT_OWNER_CONFIRMATION_REQUIRED"):
                self.command(**opts)
        self.assertEqual(len(self.gh.calls), before)

    def test_second_action_requires_first_and_stronger_confirmation(self):
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_REVIEW_REQUIRES_IDENTICAL"):
            self.command("acknowledge")
        with self.assertRaisesRegex(r12.MissionHeld, "R14_EXPLICIT_OWNER"):
            self.command("acknowledge", confirmation=r14.CONFIRM_LINK)
        self.assertEqual(len(self.gh.posts), 2)

    def test_no_replay_or_duplicate_handoff(self):
        self.command()
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_EVIDENCE_ALREADY_LINKED"):
            self.command()
        self.command("acknowledge")
        with self.assertRaises(r12.MissionHeld):
            self.command("acknowledge")

    def test_qa_workflow_identity_or_status_fail_closed(self):
        for key, value in (("path", ".github/workflows/evil.yml"),
                           ("event", "push"), ("run_attempt", 2),
                           ("conclusion", "failure"), ("head_branch", "bad")):
            good = self.gh.qa_run[key]
            self.gh.qa_run[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                    r12.MissionHeld, "R14_QA_GITHUB_RUN_IDENTITY_INVALID"):
                self.correlate()
            self.gh.qa_run[key] = good

    def test_wrong_or_replayed_run_ids_hold(self):
        for aid, qid in ((AUDIT_RUN, AUDIT_RUN), (0, QA_RUN),
                         (AUDIT_RUN, 0)):
            with self.subTest(aid=aid, qid=qid), self.assertRaises(
                    r12.MissionHeld):
                self.correlate(audit_run=aid, qa_run=qid)

    def test_digest_mutation_of_original_zip_is_held(self):
        self.gh.qa_zip += b"tamper"
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_QA_ORIGINAL_ZIP_DIGEST_MISMATCH"):
            self.correlate()

    def test_forged_qa_receipt_rejected_even_with_matching_zip_digest(self):
        receipt = qa.review(AUDIT_RUN, token="read-token",
                            get=self.gh.get, download=self.gh.download, now=NOW)
        receipt["merge_authorized"] = True
        self.gh.regenerate_qa(receipt)
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_QA_RECEIPT_NOT_INDEPENDENTLY"):
            self.correlate()

    def test_source_changes_after_completed_audit_is_held(self):
        self.gh.head = "b" * 40
        with self.assertRaises(r12.MissionHeld):
            self.correlate()

    def test_branch_protection_is_a_gate_not_a_write_permission(self):
        # This proves R14 may observe protection but cannot confer execution.
        self.gh.branch_protected = True
        with self.assertRaises(r12.MissionHeld):
            # Existing R13 audit reported branch_protected=False;
            # retrospective protection mutation makes evidence stale.
            self.correlate()
        gh = GitHub()
        gh.branch_protected = True
        # Reconstruct both audit+QA receipts with the new observed policy.
        audit = worker.audit(ISSUE, actor=r12.OWNER,
                            confirmation=worker.CONFIRM,
                            token="read-token", get=gh.get)
        gh.artifact_for(audit)
        review = qa.review(AUDIT_RUN, token="read-token",
                           get=gh.get, download=gh.download, now=NOW)
        gh.regenerate_qa(review)
        self.gh = gh
        ready = self.correlate()
        self.assertTrue(ready["branch_protection_gate_passed"])
        self.assertTrue(ready["code_write_blocked"])

    def test_out_of_order_or_spoofed_r14_comment_is_held(self):
        first = self.command()
        self.gh.comments[-1]["user"]["login"] = "attacker"
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_UNTRUSTED_OR_EDITED_COMMENT"):
            self.command("acknowledge")
        self.gh.comments[-1]["user"]["login"] = "github-actions[bot]"
        self.gh.comments.append(deepcopy(self.gh.comments[-1]))
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_RECORD_IDENTITY_OR_AUTHORITY_INVALID"):
            self.command("acknowledge")

    def test_edited_mission_blocks_followup(self):
        self.command()
        self.gh.issue["body"] += "\nEdited after verified handoff."
        with self.assertRaises(r12.MissionHeld):
            self.command("acknowledge")

    def test_qa_artifact_metadata_expiry_or_duplicates_hold(self):
        art = self.gh.qa_artifacts["artifacts"][0]
        art["expired"] = True
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_QA_ARTIFACT_METADATA_UNTRUSTED"):
            self.correlate()
        art["expired"] = False
        self.gh.qa_artifacts["artifacts"].append(deepcopy(art))
        self.gh.qa_artifacts["total_count"] = 2
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "R14_QA_ARTIFACT_MISSING_OR_AMBIGUOUS"):
            self.correlate()

    def test_hold_stale_qa_run(self):
        self.gh.qa_run["created_at"] = (
            NOW - timedelta(days=9)).isoformat()
        with self.assertRaisesRegex(r12.MissionHeld, "R14_QA_TIME_NOT_CORRELATED"):
            self.correlate()

    def test_workflow_permissions_and_careful_owner_gate(self):
        path = ROOT / ".github/workflows/fleet-r14-mission-handoff.yml"
        text = path.read_text()
        self.assertIn("github.actor == 'MichaelWave369'", text)
        self.assertIn("issues: write", text)
        self.assertIn("actions: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("pull-requests: write", text)
        self.assertNotIn("workflow_run:", text)
        self.assertIn("persist-credentials: false", text)


if __name__ == "__main__":
    unittest.main()
