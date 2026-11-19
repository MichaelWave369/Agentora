"""Offline adversarial tests for the hosted R10 receipt reconciler."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import autonomous_turn_contract as contract
import fleet_r10_hosted_dispatch as hosted
import fleet_r10_hosted_reconcile as rec

NOW = datetime(2026, 11, 19, 18, 0, tzinfo=timezone.utc)
RUN_ID = 44585625138
MERGE = "c" * 40
PR = 159


def task():
    return {
        "schema": "agentora.autonomous-task.v1",
        "task_id": "r10-hosted-receipt-test",
        "repository": hosted.REPO,
        "repository_id": hosted.REPO_ID,
        "target_branch": "main",
        "source_sha": "a" * 40,
        "created_utc": (NOW - timedelta(minutes=10)).isoformat(),
        "expires_utc": (NOW + timedelta(hours=4)).isoformat(),
        "acceptance": ["Check original docs change."],
        "allowed_paths": ["docs/AUTONOMOUS_TURN_R1.md"],
        "max_files": 1,
        "max_changed_lines": 20,
        "max_patch_bytes": 4000,
        "tests": ["docs-contract"],
        "max_repairs": 0,
        "merge_policy": "docs",
        "edits": [{"path": "docs/AUTONOMOUS_TURN_R1.md",
                   "before_sha256": "b" * 64,
                   "old": "old line", "new": "new line"}],
        "repairs": [],
        "human_scope": "Update one documentation line.",
        "phimada_request_sha256": None,
    }


def bot_comment(body):
    return {"id": 99, "body": body,
            "user": {"id": hosted.BOT_ID, "login": "github-actions[bot]"}}


class Fake:
    token = "fake-token"

    def __init__(self, *, with_link=True):
        t = task()
        self.issue = {
            "id": 123456, "number": 123, "state": "open",
            "title": hosted.TITLE_PREFIX + " test",
            "user": {"id": hosted.OWNER_ID, "login": "MichaelWave369"},
            "repository_url": hosted.API_ROOT,
            "body": json.dumps(t),
        }
        digest = contract.task_digest(t)
        fence = (hosted.FENCE_PREFIX + "123 -->\n"
                 "Task SHA-256: " + digest + "\n"
                 "State: SUBMISSION_UNCERTAIN")
        link = (hosted.RUN_LINK_PREFIX + "123 -->\n"
                "Task SHA-256: " + digest + "\n"
                f"R1 run ID: {RUN_ID}\n"
                f"Run URL: https://github.com/{hosted.REPO}/actions/runs/{RUN_ID}")
        self.rows = [bot_comment(fence)]
        if with_link:
            self.rows.append(bot_comment(link))
        self.writes = []
        self.change_on_read = False
        self.full_comments = False

    def request(self, path, *, payload=None):
        if path.startswith("/issues?"):
            return [self.issue] if path.endswith("&page=1&direction=asc") else []
        if path.startswith("/issues/123/comments?"):
            if self.full_comments:
                return [bot_comment("irrelevant")] * 100
            return self.rows
        if path == "/issues/123":
            if self.change_on_read:
                self.issue = dict(self.issue, body="{}")
            return self.issue
        if path == "/issues/123/comments" and payload is not None:
            self.writes.append(("comment", payload["body"]))
            self.rows.append(bot_comment(payload["body"]))
            return {"id": 456}
        raise AssertionError("unexpected: " + path)


def verified(client, scoped_task, run_id):
    assert run_id == RUN_ID
    assert contract.task_digest(scoped_task) == contract.task_digest(task())
    return {"pr_number": PR, "merge_sha": MERGE, "ci_status": "PASSED"}


class Writer:
    def __init__(self):
        self.calls = []

    def __call__(self, path, payload=None, method=None):
        self.calls.append((path, payload, method))
        return {"number": 123, "state": "closed", "state_reason": "completed"}


class HostedReconcileTests(unittest.TestCase):
    def test_observe_verified_without_writes(self):
        c = Fake()
        result = rec.reconcile_issue(c, c.issue, verify=verified)
        self.assertEqual(result["state"], "VERIFIED_MERGED")
        self.assertEqual(result["merge_sha"], MERGE)
        self.assertEqual(c.writes, [])

    def test_missing_run_link_holds_without_dispatch_or_close(self):
        c = Fake(with_link=False)
        result = rec.reconcile_issue(c, c.issue, close_verified=True,
                                     verify=verified)
        self.assertEqual(result["state"], "HELD_NO_ORIGINAL_RUN_LINK")
        self.assertEqual(c.writes, [])

    def test_fake_user_run_link_is_not_authentic(self):
        c = Fake()
        c.rows[1]["user"] = {"id": hosted.OWNER_ID, "login": "MichaelWave369"}
        self.assertEqual(rec.reconcile_issue(c, c.issue, verify=verified)["state"],
                         "HELD_NO_ORIGINAL_RUN_LINK")

    def test_fence_digest_change_is_a_hold(self):
        c = Fake()
        c.issue["body"] = json.dumps({**task(), "task_id": "r10-mutated-task"})
        with self.assertRaisesRegex(hosted.Held, "FENCE_DIGEST_MISMATCH"):
            rec.reconcile_issue(c, c.issue, verify=verified)

    def test_link_digest_change_is_a_hold(self):
        c = Fake()
        c.rows[1]["body"] = c.rows[1]["body"].replace(
            contract.task_digest(task()), "f" * 64)
        with self.assertRaisesRegex(hosted.Held, "RUN_LINK_INVALID"):
            rec.reconcile_issue(c, c.issue, verify=verified)

    def test_duplicate_links_hold(self):
        c = Fake()
        c.rows.append(dict(c.rows[1]))
        with self.assertRaisesRegex(hosted.Held, "RUN_LINK_AMBIGUOUS"):
            rec.reconcile_issue(c, c.issue, verify=verified)

    def test_unfinished_run_stays_open(self):
        c = Fake()
        result = rec.reconcile_issue(c, c.issue, close_verified=True,
                                     verify=lambda *args: None)
        self.assertEqual(result["state"], "AWAITING_R1_COMPLETION")
        self.assertFalse(c.writes)

    def test_incomplete_comment_pagination_holds(self):
        c = Fake()
        c.full_comments = True
        with self.assertRaisesRegex(hosted.Held, "COMMENT_HISTORY_INCOMPLETE"):
            rec.reconcile_issue(c, c.issue, verify=verified)
        self.assertFalse(c.writes)

    def test_verified_close_writes_one_receipt_and_one_patch(self):
        c, writer = Fake(), Writer()
        with patch.object(rec.github, "GitHub", return_value=writer):
            result = rec.reconcile_issue(c, c.issue, close_verified=True,
                                         verify=verified)
        self.assertEqual(result["state"], "CLOSED_VERIFIED")
        self.assertEqual(len(c.writes), 1)
        self.assertIn("State: VERIFIED_MERGED", c.writes[0][1])
        self.assertEqual(writer.calls, [(
            rec.github.BASE + "/issues/123",
            {"state": "closed", "state_reason": "completed"}, "PATCH")])

    def test_comment_replay_no_duplicate_receipt(self):
        c, writer = Fake(), Writer()
        receipt = rec.complete_body(123, task(), RUN_ID, verified(None, task(), RUN_ID))
        c.rows.append(bot_comment(receipt))
        with patch.object(rec.github, "GitHub", return_value=writer):
            result = rec.reconcile_issue(c, c.issue, close_verified=True,
                                         verify=verified)
        self.assertEqual(result["state"], "CLOSED_VERIFIED")
        self.assertFalse(c.writes)
        self.assertEqual(len(writer.calls), 1)

    def test_changed_issue_rejected_before_writes(self):
        c = Fake()
        c.change_on_read = True
        with self.assertRaisesRegex(hosted.Held, "ISSUE_CHANGED_BEFORE_WRITE"):
            rec.reconcile_issue(c, c.issue, close_verified=True, verify=verified)
        self.assertFalse(c.writes)

    def test_inconsistent_completion_comment_holds(self):
        c = Fake()
        c.rows.append(bot_comment(rec.COMPLETE_PREFIX + "123 -->\nwrong receipt"))
        with self.assertRaisesRegex(hosted.Held, "COMPLETION_CONFLICT"):
            rec.reconcile_issue(c, c.issue, close_verified=True, verify=verified)
        self.assertFalse(c.writes)

    def test_expired_original_task_is_historically_valid(self):
        c = Fake()
        result = rec.reconcile_issue(c, c.issue, verify=verified)
        self.assertEqual(result["state"], "VERIFIED_MERGED")

    def test_run_not_verified_cannot_close(self):
        c = Fake()
        def held(*_):
            raise hosted.Held("UNVERIFIED")
        with self.assertRaisesRegex(hosted.Held, "UNVERIFIED"):
            rec.reconcile_issue(c, c.issue, close_verified=True, verify=held)
        self.assertFalse(c.writes)


if __name__ == "__main__":
    unittest.main()
