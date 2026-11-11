"""R0.2 fake-GitHub adversarial tests; no network access or credentials."""
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import phi_evidence_wire as wire
import phi_evidence_live as live

REPO = "MichaelWave369/PhiMadaPrime"
SHA = "a" * 40
HASH = "b" * 64
ISSUE = 132
PR = 47


def gmed():
    return {
        "schema": "gmed-report:v1", "state": "GMED",
        "merged": True, "sha": SHA,
        "counts": {"total": 2, "passed": 1, "accepted": 2,
                   "failed": 0, "pending": 0, "unknown": 0},
        "checks": [
            {"kind": "check", "name": "web", "status": "completed",
             "conclusion": "success", "grade": "good"},
            {"kind": "check", "name": "docs", "status": "completed",
             "conclusion": "skipped", "grade": "good"},
        ],
    }


def r14():
    return {
        "schema": "agentora.fleet.r14.evidence-handoff.v1",
        "seq": 1, "command": "link",
        "target_repository": REPO, "source_sha": SHA,
        "state": "EVIDENCE_LINKED_PENDING_OWNER_REVIEW",
        "owner_acknowledged": False, "mission_issue": ISSUE,
        "audit_run_id": 210, "qa_run_id": 220,
        "issue_sha256": HASH, "audit_artifact_sha256": HASH,
        "qa_artifact_sha256": HASH, "default_branch_protected": True,
        "branch_protection_gate_passed": True,
        "code_write_blocked": True, "worker_execution_authorized": False,
        "independent_human_qa_complete": False,
        "merge_authorized": False, "deployment_authorized": False,
    }


class FakeGitHub:
    def __init__(self, journal=None):
        self.journal = journal or r14()
        self.check_rows = [
            {"id": 1, "name": "web", "status": "completed",
             "conclusion": "success", "head_sha": SHA},
            {"id": 2, "name": "docs", "status": "completed",
             "conclusion": "skipped", "head_sha": SHA},
        ]
        self.branch_sha = SHA
        self.second_branch_sha = SHA
        self.calls = {}
        self.status_rows = []
        self.comment_user = "github-actions[bot]"
        self.comment_updated = "2026-11-10T16:00:00Z"
        self.comment_created = "2026-11-10T16:00:00Z"
        self.merged = True
        self.merged_sha = SHA
        self.missing_comment = False
        self.forced_next = None
        self.default_branch = "main"
        self.pr_base_repo = REPO

    def __call__(self, path):
        self.calls[path] = self.calls.get(path, 0) + 1
        root = "/repos/" + REPO
        home = "/repos/MichaelWave369/Agentora"
        result = None
        if path == root + "/pulls/" + str(PR):
            result = {
                "number": PR, "merged": self.merged,
                "merged_at": "2026-11-10T16:30:00Z",
                "merge_commit_sha": self.merged_sha,
                "base": {"ref": "main", "repo": {"full_name": self.pr_base_repo}},
            }
        elif path == root:
            result = {"full_name": REPO, "default_branch": self.default_branch,
                      "private": False, "archived": False, "disabled": False}
        elif path == root + "/branches/main":
            sha = (self.branch_sha if self.calls[path] == 1
                   else self.second_branch_sha)
            result = {"commit": {"sha": sha}, "protected": True}
        elif path.startswith(root + "/commits/" + SHA + "/check-runs?filter=latest&per_page=100&page=1"):
            result = {"total_count": len(self.check_rows),
                      "check_runs": self.check_rows}
        elif path.startswith(root + "/commits/" + SHA + "/status?per_page=100&page=1"):
            result = {"statuses": self.status_rows}
        elif path == home + "/issues/" + str(ISSUE):
            result = {"number": ISSUE}
        elif path == home + "/issues/" + str(ISSUE) + "/comments?per_page=100&page=1":
            body = (live.R14_MARK + "\n~~~json\n" +
                    json.dumps(self.journal, sort_keys=True,
                               separators=(",", ":")) + "\n~~~")
            result = [] if self.missing_comment else [{
                "id": 9001, "body": body,
                "user": {"login": self.comment_user},
                "created_at": self.comment_created,
                "updated_at": self.comment_updated,
            }]
        else:
            raise AssertionError("unexpected GitHub path: " + path)
        return result, self.forced_next is True


class LiveEvidenceTests(unittest.TestCase):
    def assert_held(self, fake, receipt=None, r14_receipt=None,
                    sha=SHA):
        with self.assertRaises(wire.EvidenceHeld):
            live.corroborate(REPO, PR, sha, receipt or gmed(),
                             r14_receipt or r14(), get=fake)

    def test_correlated_receipts_and_live_metadata_still_no_permission(self):
        output = live.corroborate(REPO, PR, SHA, gmed(), r14(),
                                  get=FakeGitHub())
        self.assertEqual(output["state"],
                         "GITHUB_METADATA_CORROBORATED_REVIEW_ONLY")
        self.assertEqual(output["r14_github_comment_id"], 9001)
        self.assertEqual(output["check_run_count"], 2)
        for field in ("formal_proof_checked", "merge_authorized",
                      "deployment_authorized", "code_write_authorized",
                      "worker_dispatch_authorized",
                      "r14_r13_qa_artifact_bytes_revalidated",
                      "independent_human_qa_complete",
                      "independent_cryptographic_attestation",
                      "required_check_policy_verified"):
            self.assertIs(output[field], False)

    def test_pr_is_not_merged(self):
        fake = FakeGitHub()
        fake.merged = False
        self.assert_held(fake)

    def test_pr_merge_sha_does_not_match(self):
        fake = FakeGitHub()
        fake.merged_sha = "c" * 40
        self.assert_held(fake)

    def test_pr_base_repository_does_not_match(self):
        fake = FakeGitHub()
        fake.pr_base_repo = "MichaelWave369/PhiOS"
        self.assert_held(fake)

    def test_branch_drift_before_checks(self):
        fake = FakeGitHub()
        fake.branch_sha = "c" * 40
        self.assert_held(fake)

    def test_branch_drift_during_review(self):
        fake = FakeGitHub()
        fake.second_branch_sha = "d" * 40
        self.assert_held(fake)

    def test_default_branch_changed(self):
        fake = FakeGitHub()
        fake.default_branch = "release"
        self.assert_held(fake)

    def test_missing_check_not_passing(self):
        fake = FakeGitHub()
        fake.check_rows.pop()
        self.assert_held(fake)

    def test_extra_undisclosed_check_not_passing(self):
        fake = FakeGitHub()
        fake.check_rows.append({"id": 3, "name": "other",
                                "status": "completed", "conclusion": "success",
                                "head_sha": SHA})
        self.assert_held(fake)

    def test_failing_check_not_passing(self):
        fake = FakeGitHub()
        fake.check_rows[0]["conclusion"] = "failure"
        self.assert_held(fake)

    def test_pending_check_not_passing(self):
        fake = FakeGitHub()
        fake.check_rows[0]["status"] = "in_progress"
        fake.check_rows[0]["conclusion"] = None
        self.assert_held(fake)

    def test_wrong_check_head_not_passing(self):
        fake = FakeGitHub()
        fake.check_rows[0]["head_sha"] = "c" * 40
        self.assert_held(fake)

    def test_incomplete_list_pagination(self):
        fake = FakeGitHub()
        fake.forced_next = True
        self.assert_held(fake)

    def test_unlisted_legacy_failure(self):
        fake = FakeGitHub()
        fake.status_rows.append({"context": "old", "state": "failure"})
        self.assert_held(fake)

    def test_r14_comment_missing(self):
        fake = FakeGitHub()
        fake.missing_comment = True
        self.assert_held(fake)

    def test_r14_comment_spoofed(self):
        fake = FakeGitHub()
        fake.comment_user = "not-github-actions"
        self.assert_held(fake)

    def test_r14_comment_edited(self):
        fake = FakeGitHub()
        fake.comment_updated = "2026-11-10T16:01:00Z"
        self.assert_held(fake)

    def test_r14_comment_payload_changed(self):
        fake = FakeGitHub()
        fake.journal["audit_run_id"] += 1
        self.assert_held(fake)

    def test_gmed_receipt_does_not_match_live_check(self):
        fake = FakeGitHub()
        receipt = gmed()
        receipt["checks"][0]["name"] = "nonexistent"
        self.assert_held(fake, receipt)

    def test_bogus_review_does_not_grant_authority(self):
        fake = FakeGitHub()
        bogus = r14()
        bogus["merge_authorized"] = True
        self.assert_held(fake, r14_receipt=bogus)

    def test_wrong_source_sha_held_before_io(self):
        fake = FakeGitHub()
        self.assert_held(fake, sha="c" * 40)
        self.assertEqual(fake.calls, {})


if __name__ == "__main__":
    unittest.main()
