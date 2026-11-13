"""No-network adversarial tests for one-repo Phi Pit Crew CI watcher."""
import unittest

from scripts import fleet_pitcrew_ci_watch_r1 as watch

HEAD = "a" * 40
OLD = "b" * 40


def run(sha=HEAD, *, ident=12, attempt=1, status="completed",
        conclusion="success", event="push", path=watch.WORKFLOW):
    return {"head_sha": sha, "head_branch": "main", "event": event,
            "path": path, "id": ident, "run_attempt": attempt,
            "status": status, "conclusion": conclusion}


def mock_get(*, runs=None, sha=HEAD, target_ok=True, jobs=None):
    selected = runs if runs is not None else [run()]
    history = []

    def get(path):
        history.append(path)
        if path == "/repos/" + watch.TARGET:
            return {"id": watch.TARGET_ID if target_ok else 2,
                    "full_name": watch.TARGET, "private": False,
                    "archived": False, "default_branch": "main"}
        if path == "/repos/" + watch.TARGET + "/branches/main":
            return {"commit": {"sha": sha}}
        if path.endswith("/actions/workflows/ci.yml/runs?branch=main&event=push&per_page=30"):
            return {"total_count": len(selected), "workflow_runs": selected}
        if "/jobs?per_page=100" in path:
            listing = jobs if jobs is not None else []
            return {"total_count": len(listing), "jobs": listing}
        raise AssertionError("Unexpected GitHub API read: " + path)
    return get, history


def issue_get(comments=None, *, modified=False):
    def get(path):
        if path == "/repos/" + watch.HOME + "/issues/124":
            return {"number": 124, "state": "open",
                    "title": ("changed" if modified else watch.ISSUE_TITLE),
                    "user": {"id": watch.OWNER_ID}}
        if path == "/repos/" + watch.HOME + "/issues/124/comments?per_page=100":
            return comments if comments is not None else []
        raise AssertionError("Unexpected issue API read: " + path)
    return get


class ObserveTests(unittest.TestCase):
    def test_success_at_current_head(self):
        get, _ = mock_get()
        result = watch.observe(get)
        self.assertEqual(result["state"], "CI_SUCCESS_EXACT_HEAD")
        self.assertEqual(result["head_sha"], HEAD)

    def test_old_success_does_not_hide_current_failure(self):
        get, calls = mock_get(runs=[
            run(OLD, ident=20, conclusion="success"),
            run(HEAD, ident=21, conclusion="failure")],
            jobs=[{"name": "build <untrusted>", "conclusion": "failure"}])
        result = watch.observe(get)
        self.assertEqual(result["state"], "CI_FAILURE_EXACT_HEAD")
        self.assertEqual(result["run_id"], 21)
        self.assertEqual(result["failed_jobs"], ["build ?untrusted?"])
        self.assertTrue(any("/jobs?" in path for path in calls))

    def test_pending_never_green(self):
        get, _ = mock_get(runs=[run(status="in_progress", conclusion=None)])
        self.assertEqual(watch.observe(get)["state"], "CI_PENDING_EXACT_HEAD")

    def test_cancelled_not_success(self):
        get, _ = mock_get(runs=[run(conclusion="cancelled")])
        self.assertEqual(watch.observe(get)["state"], "CI_INCONCLUSIVE_EXACT_HEAD")

    def test_no_current_head_run_is_explicit_unknown(self):
        get, _ = mock_get(runs=[run(OLD)])
        report = watch.observe(get)
        self.assertEqual(report["state"], "NO_EXACT_HEAD_CI")
        self.assertIsNone(report["run_id"])

    def test_reject_other_events_and_workflows(self):
        get, _ = mock_get(runs=[run(event="pull_request"),
                                 run(path=".github/workflows/pages.yml")])
        self.assertEqual(watch.observe(get)["state"], "NO_EXACT_HEAD_CI")

    def test_reject_changed_repository_identity(self):
        get, _ = mock_get(target_ok=False)
        with self.assertRaisesRegex(watch.Held, "IDENTITY"):
            watch.observe(get)

    def test_newest_run_wins_even_if_old_run_was_rerun(self):
        get, _ = mock_get(runs=[run(ident=40, attempt=1, conclusion="failure"),
                                 run(ident=30, attempt=2, conclusion="success")])
        report = watch.observe(get)
        self.assertEqual(report["run_id"], 40)
        self.assertEqual(report["state"], "CI_FAILURE_EXACT_HEAD")


class HeadDriftTests(unittest.TestCase):
    def test_same_head_can_proceed(self):
        get, calls = mock_get()
        report = watch.observe(get)
        watch.ensure_head_unchanged(get, report)
        self.assertEqual(calls.count("/repos/" + watch.TARGET + "/branches/main"), 2)

    def test_changed_head_holds_before_issue_write(self):
        get, _ = mock_get()
        report = watch.observe(get)
        moved, _ = mock_get(sha=OLD)
        with self.assertRaisesRegex(watch.Held, "MAIN_CHANGED_DURING_OBSERVATION"):
            watch.ensure_head_unchanged(moved, report)

    def test_missing_second_branch_response_holds(self):
        get, _ = mock_get()
        report = watch.observe(get)
        with self.assertRaisesRegex(watch.Held, "MAIN_CHANGED_DURING_OBSERVATION"):
            watch.ensure_head_unchanged(lambda path: {}, report)

    def test_invalid_observation_cannot_be_confirmed(self):
        with self.assertRaisesRegex(watch.Held, "OBSERVED_HEAD_INVALID"):
            watch.ensure_head_unchanged(lambda path: self.fail("must not query"),
                                        {"head_sha": "unverified"})



class JournalTests(unittest.TestCase):
    report = {"state": "CI_SUCCESS_EXACT_HEAD", "head_sha": HEAD,
              "run_id": 12, "run_attempt": 1, "failed_jobs": []}

    def test_creates_one_comment_without_new_issue(self):
        writes = []
        def send(method, path, body):
            writes.append((method, path, body))
        result = watch.publish(issue_get(), send, self.report)
        self.assertEqual(result, "CREATED")
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], "POST")
        self.assertEqual(writes[0][1],
                         "/repos/" + watch.HOME + "/issues/124/comments")
        self.assertIn(watch.MARKER, writes[0][2]["body"])

    def test_same_report_noop(self):
        comments = [{"id": 10, "body": watch.render(self.report),
                     "user": {"login": "github-actions[bot]"}}]
        self.assertEqual(watch.publish(issue_get(comments),
                         lambda *args: self.fail("duplicate write"),
                         self.report), "UNCHANGED")

    def test_updates_only_matching_bot_comment(self):
        comments = [
            {"id": 1, "body": watch.MARKER + "\nold",
             "user": {"login": "MichaelWave369"}},
            {"id": 2, "body": watch.MARKER + "\nprevious",
             "user": {"login": "github-actions[bot]"}}]
        writes = []
        self.assertEqual(
            watch.publish(issue_get(comments),
                          lambda method, path, body: writes.append((method, path)),
                          self.report), "UPDATED")
        self.assertEqual(writes, [("PATCH",
                         "/repos/" + watch.HOME + "/issues/comments/2")])

    def test_duplicate_trusted_comments_hold(self):
        comments = [{"id": ident, "body": watch.MARKER,
                     "user": {"login": "github-actions[bot]"}}
                    for ident in (1, 2)]
        with self.assertRaisesRegex(watch.Held, "DUPLICATE"):
            watch.publish(issue_get(comments),
                          lambda *args: self.fail("must not write"),
                          self.report)

    def test_tampered_mission_holds(self):
        with self.assertRaisesRegex(watch.Held, "CANONICAL_MISSION"):
            watch.publish(issue_get(modified=True),
                          lambda *args: self.fail("must not write"),
                          self.report)

    def test_truncated_comment_page_holds(self):
        comments = [{"id": i, "body": "hello"} for i in range(100)]
        with self.assertRaisesRegex(watch.Held, "INCOMPLETE"):
            watch.publish(issue_get(comments),
                          lambda *args: self.fail("must not write"),
                          self.report)


if __name__ == "__main__":
    unittest.main()
