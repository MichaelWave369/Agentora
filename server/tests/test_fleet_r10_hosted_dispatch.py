"""Adversarial offline tests for GitHub-hosted R10 docs transport."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r10_hosted_dispatch as hosted


NOW = datetime(2026, 11, 18, 20, tzinfo=timezone.utc)


def task(*, source_sha="a" * 40):
    return {
        "schema": "agentora.autonomous-task.v1",
        "task_id": "r10-hosted-docs-test",
        "repository": "MichaelWave369/Agentora",
        "repository_id": 1167870912,
        "target_branch": "main",
        "source_sha": source_sha,
        "created_utc": (NOW - timedelta(minutes=5)).isoformat(),
        "expires_utc": (NOW + timedelta(hours=3)).isoformat(),
        "acceptance": ["Documentation change is exact and reviewed."],
        "allowed_paths": ["docs/AUTONOMOUS_TURN_R1.md"],
        "max_files": 1,
        "max_changed_lines": 20,
        "max_patch_bytes": 4000,
        "tests": ["docs-contract"],
        "max_repairs": 0,
        "merge_policy": "docs",
        "edits": [{
            "path": "docs/AUTONOMOUS_TURN_R1.md",
            "before_sha256": "b" * 64,
            "old": "original text",
            "new": "revised text",
        }],
        "repairs": [],
        "human_scope": "Review one exact documentation edit.",
        "phimada_request_sha256": None,
    }


def issue(number=123, *, owner=hosted.OWNER_ID, body=None, title=None):
    return {
        "number": number, "state": "open", "repository_url": hosted.API_ROOT,
        "user": {"id": owner, "login": "MichaelWave369"},
        "title": title or hosted.TITLE_PREFIX + " documented change",
        "body": json.dumps(task() if body is None else body),
    }


class FakeAPI:
    def __init__(self, issues=()):
        self.issues = list(issues)
        self.comments = {}
        self.writes = []
        self.fail_dispatch = False
        self.fail_fence = False
        self.full_comments = False
        self.detail_response = False
        self.token = "fake-token"

    def request(self, path, *, payload=None):
        if path.startswith("/issues?"):
            page = int(path.split("&page=", 1)[-1].split("&", 1)[0])
            return self.issues[(page - 1) * 100:page * 100]
        if path.endswith("/comments?per_page=100&page=1") or (
                "/comments?per_page=100&page=" in path):
            num = int(path.split("/")[2])
            if self.full_comments:
                return [{"body": "unrelated", "user": {"id": 1}}] * 100
            return self.comments.get(num, [])
        if path.endswith("/comments") and payload is not None:
            if self.fail_fence:
                raise hosted.Held("FENCE_WRITE_UNCERTAIN")
            num = int(path.split("/")[2])
            self.writes.append(("fence", num))
            self.comments.setdefault(num, []).append({
                "id": 99, "body": payload["body"],
                "user": {"id": hosted.BOT_ID, "login": "github-actions[bot]"},
            })
            return {"id": 99}
        if path == hosted.DISPATCH and payload is not None:
            self.writes.append(("dispatch", payload))
            if self.fail_dispatch:
                raise hosted.Held("DISPATCH_RESPONSE_UNAVAILABLE")
            if self.detail_response:
                return {"workflow_run_id": 12345,
                        "run_url": hosted.API_ROOT + "/actions/runs/12345",
                        "html_url": "https://github.com/" + hosted.REPO + "/actions/runs/12345"}
            return {"status": 204}
        raise AssertionError("Unexpected API call: " + path)


def good_preflight(client, scoped_task):
    if scoped_task["source_sha"] != "a" * 40:
        raise hosted.Held("SOURCE_DRIFT")


class HostedDispatchTests(unittest.TestCase):
    @staticmethod
    def _run_identity(actor, *, event="workflow_dispatch", triggered=None, attempt=1):
        return {
            "id": 12345, "repository": {"id": hosted.REPO_ID},
            "head_sha": "a" * 40, "head_branch": "main",
            "event": event, "run_attempt": attempt,
            "path": ".github/workflows/autonomous-turn-r1.yml@refs/heads/main",
            "actor": actor, "triggering_actor": triggered or actor,
        }

    def test_fixed_actions_bot_run_is_only_dispatch_intent(self):
        bot = {"id": hosted.BOT_ID, "type": "Bot", "login": "github-actions[bot]"}
        run = self._run_identity(bot)
        self.assertIsNone(hosted.github.run_identity(run, task(), 12345, "a" * 40))

    def test_bot_issue_and_mixed_actor_are_rejected(self):
        bot = {"id": hosted.BOT_ID, "type": "Bot", "login": "github-actions[bot]"}
        human = {"id": hosted.OWNER_ID, "type": "User", "login": "MichaelWave369"}
        for run in (self._run_identity(bot, event="issues"),
                    self._run_identity(bot, triggered=human),
                    self._run_identity(bot, attempt=2)):
            with self.subTest(run=run):
                with self.assertRaises(hosted.contract.Held):
                    hosted.github.run_identity(run, task(), 12345, "a" * 40)

    def test_original_owner_run_remains_allowed(self):
        human = {"id": hosted.OWNER_ID, "type": "User", "login": "MichaelWave369"}
        run = self._run_identity(human, event="issues")
        self.assertIsNone(hosted.github.run_identity(run, task(), 12345, "a" * 40))

    def test_owner_only(self):
        wrong = issue(owner=5)
        client = FakeAPI([wrong])
        self.assertEqual(hosted.dispatch_one(client, now=NOW, preflight=good_preflight)["state"],
                         "NO_ELIGIBLE_UNFENCED_TASK")
        self.assertEqual(client.writes, [])

    def test_full_dry_run_checks_scope_but_does_not_write(self):
        client = FakeAPI([issue()])
        result = hosted.dispatch_one(client, now=NOW, dry_run=True,
                                     preflight=good_preflight)
        self.assertEqual(result["state"], "ELIGIBLE_NOT_DISPATCHED")
        self.assertEqual(client.writes, [])

    def test_exactly_one_fence_before_dispatch_then_no_duplicate(self):
        client = FakeAPI([issue(), issue(124)])
        result = hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(result["state"], "FENCED_DISPATCH_ACCEPTED_RUN_UNCONFIRMED")
        self.assertEqual([w[0] for w in client.writes], ["fence", "dispatch"])
        # First issue is fenced; next scheduled tick may process the second,
        # never resubmitting the original one.
        result2 = hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(result2["issue"], 124)
        self.assertEqual(client.writes[2][0], "fence")
        self.assertEqual(len([w for w in client.writes if w[0] == "dispatch"]), 2)

    def test_2026_dispatch_run_details_are_verified(self):
        client = FakeAPI([issue()])
        client.detail_response = True
        result = hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(result["state"], "FENCED_DISPATCH_ACCEPTED_RUN_IDENTIFIED")
        self.assertEqual(result["workflow_run_id"], 12345)
        self.assertTrue(client.writes[-1][1]["return_run_details"])
        self.assertEqual(hosted.dispatch_one(client, now=NOW,
                                             preflight=good_preflight)["state"],
                         "NO_ELIGIBLE_UNFENCED_TASK")

    def test_ambiguous_dispatch_never_repeats(self):
        client = FakeAPI([issue()])
        client.fail_dispatch = True
        with self.assertRaisesRegex(hosted.Held, "DISPATCH_RESPONSE_UNAVAILABLE"):
            hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual([w[0] for w in client.writes], ["fence", "dispatch"])
        self.assertEqual(hosted.dispatch_one(client, now=NOW,
                                             preflight=good_preflight)["state"],
                         "NO_ELIGIBLE_UNFENCED_TASK")
        self.assertEqual(len(client.writes), 2)

    def test_uncertain_fence_failure_never_dispatches(self):
        client = FakeAPI([issue()])
        client.fail_fence = True
        with self.assertRaisesRegex(hosted.Held, "FENCE_WRITE_UNCERTAIN"):
            hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(client.writes, [])

    def test_mutated_body_after_fence_cannot_redispatch(self):
        client = FakeAPI([issue()])
        hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        client.issues[0]["body"] = json.dumps(task(source_sha="c"*40))
        result = hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(result["state"], "NO_ELIGIBLE_UNFENCED_TASK")

    def test_fake_user_comment_is_not_bot_fence(self):
        client = FakeAPI([issue()])
        client.comments[123] = [{
            "body": hosted.FENCE_PREFIX + "123 -->",
            "user": {"id": hosted.OWNER_ID, "login": "MichaelWave369"},
        }]
        self.assertFalse(hosted.existing_fence(client, 123))
        result = hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(result["issue"], 123)

    def test_fail_closed_on_comment_pagination(self):
        client = FakeAPI([issue()])
        client.full_comments = True
        with self.assertRaisesRegex(hosted.Held, "COMMENT_HISTORY_INCOMPLETE"):
            hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertFalse(client.writes)

    def test_invalid_scope_never_dispatches(self):
        unsafe = task()
        unsafe["merge_policy"] = "reviewed-code"
        client = FakeAPI([issue(body=unsafe)])
        result = hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(result["state"], "NO_ELIGIBLE_UNFENCED_TASK")
        self.assertFalse(client.writes)

    def test_expired_task_does_not_dispatch(self):
        client = FakeAPI([issue()])
        later = NOW + timedelta(hours=4)
        result = hosted.dispatch_one(client, now=later, preflight=good_preflight)
        self.assertEqual(result["state"], "NO_ELIGIBLE_UNFENCED_TASK")
        self.assertFalse(client.writes)

    def test_drift_holds_before_fence(self):
        client = FakeAPI([issue(body=task(source_sha="c"*40))])
        result = hosted.dispatch_one(client, now=NOW, preflight=good_preflight)
        self.assertEqual(result["state"], "NO_ELIGIBLE_UNFENCED_TASK")
        self.assertFalse(client.writes)


if __name__ == "__main__":
    unittest.main()
