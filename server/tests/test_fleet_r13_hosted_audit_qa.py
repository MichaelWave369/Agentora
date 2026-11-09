"""R13 hosted audit and independent GitHub artifact/metadata QA regression."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest
from zipfile import ZipFile

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[2] / "scripts"))
sys.path.insert(0, str(HERE.parent))
import fleet_r12_github_missions as r12
import fleet_r13_readonly_audit as worker
import fleet_r13_independent_qa as qa
from test_fleet_r12_github_missions import FakeGH, body, ISSUE, TARGET

RUN = 700007
ARTIFACT = 990022
NOW = datetime(2026, 11, 8, 22, 20, tzinfo=timezone.utc)


def archive(receipt, extra=None):
    output = BytesIO()
    with ZipFile(output, "w") as z:
        z.writestr("fleet-r13/receipt.json", json.dumps(receipt))
        z.writestr("fleet-r13/summary.md", "# Pending independent QA\n")
        for key, value in (extra or {}).items():
            z.writestr(key, value)
    return output.getvalue()


class GitHub(FakeGH):
    def __init__(self):
        super().__init__()
        self.issue["body"] = body(kind="Read-only audit")
        self.repo["disabled"] = False
        self.head = "a" * 40
        self.branch_protected = False
        self.commit_signature = False
        self.fail_head_recheck = False
        self.head_reads = 0
        self.audit_run = {
            "id": RUN, "path": qa.WORKFLOW,
            "event": "workflow_dispatch", "status": "completed",
            "conclusion": "success", "run_attempt": 1,
            "head_branch": "main",
            "created_at": (NOW - timedelta(minutes=2)).isoformat(),
            "repository": {"full_name": r12.HOME},
            "actor": {"login": r12.OWNER},
        }
        self.audit_artifacts = None
        self.audit_zip = None

    def get(self, path, token):
        if path == "/repos/" + TARGET + "/branches/main":
            self.head_reads += 1
            sha = ("e" * 40 if self.fail_head_recheck
                   and self.head_reads >= 4 else self.head)
            return {"commit": {"sha": sha},
                    "protected": self.branch_protected}
        if path == "/repos/" + TARGET + "/commits/" + self.head:
            return {"sha": self.head, "parents": [],
                    "commit": {"verification":
                               {"verified": self.commit_signature}}}
        if path == "/repos/" + r12.HOME + "/actions/runs/" + str(RUN):
            return deepcopy(self.audit_run)
        if path == ("/repos/" + r12.HOME + "/actions/runs/" + str(RUN)
                    + "/artifacts?per_page=100"):
            return deepcopy(self.audit_artifacts)
        return super().get(path, token)

    def init_mission(self):
        for action, args in (
            ("triage", {}),
            ("propose_worker", {"worker": "builder_a"}),
        ):
            r12.transition(ISSUE, action, actor=r12.OWNER,
                           confirmation=r12.CONFIRM, token="test",
                           get=self.get, post=self.post, **args)

    def artifact_for(self, receipt):
        self.audit_zip = archive(receipt)
        self.audit_artifacts = {"total_count": 1, "artifacts": [{
            "id": ARTIFACT,
            "name": "fleet-r13-audit-" + str(RUN),
            "size_in_bytes": len(self.audit_zip),
            "digest": "sha256:" + hashlib.sha256(self.audit_zip).hexdigest(),
            "expired": False, "workflow_run": {"id": RUN},
        }]}


class R13Tests(unittest.TestCase):
    def setUp(self):
        self.gh = GitHub()
        self.gh.init_mission()

    def audit(self, **kwargs):
        return worker.audit(ISSUE, actor=kwargs.get("actor", r12.OWNER),
                            confirmation=kwargs.get("confirmation", worker.CONFIRM),
                            token="test", get=self.gh.get)

    def review(self, **kwargs):
        return qa.review(RUN, token="test", get=self.gh.get,
                         download=lambda aid, tok: self.gh.audit_zip,
                         now=kwargs.get("now", NOW))

    def test_actual_hosted_worker_claim_is_public_metadata_only(self):
        report = self.audit()
        self.assertEqual(report["mission_issue"], ISSUE)
        self.assertEqual(report["target_repository"], TARGET)
        self.assertEqual(report["exact_source_sha"], "a" * 40)
        self.assertEqual(report["mission_journal_seq"], 2)
        self.assertEqual(report["proposed_worker"], "builder_a")
        self.assertFalse(report["target_source_executed"])
        self.assertFalse(report["worker_is_model_agent"])
        self.assertFalse(report["independent_qa_complete"])
        self.assertFalse(report["merge_authorized"])
        self.assertEqual(len(self.gh.posts), 2)

    def test_owner_confirmation_holds_before_api_reads(self):
        baseline = len(self.gh.calls)
        for opts in ({"actor": "intruder"},
                     {"confirmation": "RUN_ARBITRARY"},
                     {"actor": None}):
            with self.subTest(opts=opts), self.assertRaisesRegex(
                    r12.MissionHeld, "OWNER_CONFIRMATION_REQUIRED"):
                self.audit(**opts)
        self.assertEqual(len(self.gh.calls), baseline)

    def test_wrong_mission_kind_is_not_an_executable_job(self):
        self.gh.issue["body"] = body(kind="Documentation")
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "AUDIT_MISSION_KIND_REQUIRED"):
            self.audit()

    def test_wrong_proposed_worker_is_held(self):
        record = self.gh.comments[-1]
        payload = json.loads(record["body"].split("~~~json\n", 1)[1].split("\n~~~")[0])
        payload["worker_role"] = "untrusted_worker"
        record["body"] = (r12.MARK + "\n~~~json\n" +
                          json.dumps(payload) + "\n~~~")
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "EXACT_PROPOSED_READONLY_ROLE_REQUIRED"):
            self.audit()

    def test_audit_refuses_changed_source_during_two_head_checks(self):
        self.gh.fail_head_recheck = True
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "SOURCE_MOVED_DURING_AUDIT"):
            self.audit()

    def test_private_or_disabled_target_held(self):
        for field, value in (("private", True), ("archived", True),
                             ("disabled", True)):
            with self.subTest(field=field):
                gh = GitHub()
                gh.init_mission()
                setattr(self, "gh", gh)
                gh.repo[field] = value
                with self.assertRaises(r12.MissionHeld):
                    self.audit()

    def test_branch_protection_is_reported_not_automatically_approved(self):
        self.gh.branch_protected = True
        data = self.audit()
        self.assertIs(data["observations"]["default_branch_protected"], True)
        self.assertFalse(data["verified_complete"])

    def test_separate_workflow_correlates_real_zip_and_live_metadata(self):
        audit = self.audit()
        self.gh.artifact_for(audit)
        result = self.review()
        self.assertEqual(result["state"],
                         "AUDIT_METADATA_CORROBORATED_PENDING_HUMAN_QA")
        self.assertEqual(result["source_sha"], "a" * 40)
        self.assertEqual(result["artifact_sha256"],
                         hashlib.sha256(self.gh.audit_zip).hexdigest())
        self.assertTrue(result["automated_independent_evidence_recheck"])
        for flag in ("independent_human_qa_complete",
                     "independent_qa_complete", "verified_complete",
                     "merge_authorized", "deployment_authorized"):
            self.assertFalse(result[flag])
        self.assertEqual(len(self.gh.posts), 2)

    def test_wrong_workflow_event_attempt_or_failed_run_rejected(self):
        data = self.audit()
        for field, value in (("path", ".github/workflows/unknown.yml"),
                             ("event", "push"), ("run_attempt", 2),
                             ("conclusion", "failure"),
                             ("head_branch", "other")):
            self.gh.artifact_for(data)
            self.gh.audit_run[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                    r12.MissionHeld, "QA_AUDIT_RUN_IDENTITY_NOT_TRUSTED"):
                self.review()
            self.gh.audit_run[field] = {
                "path": qa.WORKFLOW, "event": "workflow_dispatch",
                "run_attempt": 1, "conclusion": "success",
                "head_branch": "main"}[field]

    def test_tampered_zip_digest_is_rejected_before_parsing(self):
        self.gh.artifact_for(self.audit())
        self.gh.audit_zip += b"attacker"
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "QA_GITHUB_ARTIFACT_DIGEST_MISMATCH"):
            self.review()

    def test_forged_approval_receipt_never_accepted(self):
        data = self.audit()
        data["merge_authorized"] = True
        self.gh.artifact_for(data)
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "QA_AUDIT_RECEIPT_NOT_CORROBORATED"):
            self.review()

    def test_source_or_branch_protection_drift_held(self):
        data = self.audit()
        self.gh.artifact_for(data)
        self.gh.branch_protected = True
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "QA_AUDIT_RECEIPT_NOT_CORROBORATED"):
            self.review()

    def test_unexpected_zip_member_or_duplicate_rejected(self):
        data = self.audit()
        for extra in ({"evil.py": "exit()"},
                      {"../evil.json": "{}"},
                      {"fleet-r13/report.json": "{}"}):
            with self.subTest(extra=extra), self.assertRaises(
                    r12.MissionHeld):
                qa.read_receipt(archive(data, extra))

    def test_expired_or_ambiguous_artifact_held(self):
        self.gh.artifact_for(self.audit())
        self.gh.audit_artifacts["artifacts"][0]["expired"] = True
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "QA_ARTIFACT_METADATA_INVALID"):
            self.review()
        self.gh.artifact_for(self.audit())
        self.gh.audit_artifacts["artifacts"].append(
            deepcopy(self.gh.audit_artifacts["artifacts"][0]))
        self.gh.audit_artifacts["total_count"] = 2
        with self.assertRaisesRegex(r12.MissionHeld,
                                    "QA_ARTIFACT_MISSING_OR_AMBIGUOUS"):
            self.review()

    def test_old_run_held(self):
        self.gh.artifact_for(self.audit())
        with self.assertRaisesRegex(r12.MissionHeld, "QA_RUN_TOO_OLD"):
            self.review(now=NOW + timedelta(days=9))

    def test_workflows_are_readonly_and_qa_is_separate(self):
        root = HERE.parents[2] / ".github/workflows"
        worker_yaml = (root / "fleet-r13-readonly-audit.yml").read_text()
        qa_yaml = (root / "fleet-r13-independent-qa.yml").read_text()
        self.assertIn("github.actor == 'MichaelWave369'", worker_yaml)
        self.assertIn("RUN_FLEET_R13_READ_ONLY_AUDIT", worker_yaml)
        self.assertIn("issues: read", worker_yaml)
        self.assertIn("workflow_run:", qa_yaml)
        self.assertIn("actions: read", qa_yaml)
        self.assertNotIn("contents: write", worker_yaml + qa_yaml)
        self.assertNotIn("issues: write", worker_yaml + qa_yaml)
        self.assertNotIn("pull-requests: write", worker_yaml + qa_yaml)


if __name__ == "__main__":
    unittest.main()
