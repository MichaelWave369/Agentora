"""R1.1 late-CI recovery: only synthetic GitHub API fixtures, never a live merge."""
from copy import deepcopy
import importlib
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "scripts"))

from test_autonomous_turn_r1 import (SyntheticGitHub, task, value_for,
                                    isolated, SOURCE, CONTROL)
c = importlib.import_module("autonomous_turn_contract")
g = importlib.import_module("autonomous_turn_github")
r = importlib.import_module("autonomous_turn_recover")
cli = importlib.import_module("autonomous_turn")


class RecoveryGitHub(SyntheticGitHub):
    def __init__(self, t):
        super().__init__(t)
        self.run.update({"status": "completed", "conclusion": "success"})
        self.new_run = {"id": 22, "repository": self.repo, "head_sha": SOURCE,
                        "head_branch": "main", "event": "workflow_dispatch",
                        "run_attempt": 1, "path": r.WORKFLOW,
                        "actor": self.owner, "triggering_actor": self.owner}
        self.recovery_reviews = []

    def _call(self, path, payload, method):
        if path == g.BASE+"/actions/runs/22":
            return self.new_run
        if path == g.BASE+"/actions/runs/22/approvals":
            return self.recovery_reviews
        return super()._call(path, payload, method)


class LateCiRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.t = task()
        self.api = RecoveryGitHub(self.t)
        self.value = value_for(self.t)
        self.sandbox = isolated(self.t, self.value)
        self.pub = g.publish(self.api, self.t, self.value, self.sandbox, 11, CONTROL)
        self.api.check_mutation = lambda rows: [
            {**row, "status": "queued", "conclusion": None} for row in rows]
        self.obs = g.observe(self.api, self.t, self.pub, self.value,
                             11, CONTROL, polls=1)
        self.assertEqual(self.obs["state"], "CI_PENDING_TIMEOUT")
        self.api.check_mutation = lambda rows: rows
        self.api.recovery_reviews = [{
            "state": "approved",
            "comment": r.approval_comment(self.t, 11, self.pub["pr_number"],
                                          self.pub["head_sha"]),
            "user": self.api.owner,
            "environments": [{"id": 123, "name": g.ENVIRONMENT}]}]

    def check(self, stage="finish", api=None, task_override=None,
              observed=None, source_run=11, pr_num=None, head=None,
              recovery_run=22, control_sha=SOURCE):
        api = api or self.api
        t = task_override or self.t
        with TemporaryDirectory() as tmp:
            path = Path(tmp)
            for name, value in (("task", t), ("published", self.pub),
                                ("proposal", self.value), ("sandbox", self.sandbox),
                                ("observation", self.obs if observed is None else observed)):
                cli.write(path/(name+".json"), value)
            return r.execute(api, source_run, pr_num or self.pub["pr_number"],
                             head or self.pub["head_sha"], c.task_digest(self.t),
                             recovery_run, control_sha, path, stage)

    def test_plan_is_read_only_and_finish_rechecks_real_green_ci_and_merge(self):
        result = self.check(stage="plan")
        self.assertEqual(result["state"], "RECOVERY_REVIEW_REQUIRED")
        self.assertFalse(any(path.endswith("/merge") for path,_,_ in self.api.calls))
        result = self.check()
        self.assertEqual(result["state"], "MERGED")
        self.assertFalse(result["project_verified_complete"])
        self.assertEqual(sum(path.endswith("/merge") for path,_,_ in self.api.calls), 1)

    def test_missing_wrong_or_bot_new_owner_review_refuses_all_merges(self):
        for mode in ("missing", "digest", "bot", "rejected", "extra-reviewer"):
            self.setUp()
            if mode == "missing": self.api.recovery_reviews = []
            if mode == "digest": self.api.recovery_reviews[0]["comment"] += "X"
            if mode == "bot": self.api.recovery_reviews[0]["user"] = {
                "id": c.OWNER_ID, "type": "Bot"}
            if mode == "rejected": self.api.recovery_reviews[0]["state"] = "rejected"
            if mode == "extra-reviewer":
                self.api.env["protection_rules"][0]["reviewers"] *= 2
            with self.subTest(mode=mode), self.assertRaises(c.Held):
                self.check()
            self.assertFalse(any(path.endswith("/merge") for path,_,_ in self.api.calls))

    def test_wrong_run_or_pr_identity_refuses(self):
        for mode in ("recovery-actor", "recovery-path", "rerun", "head",
                     "wrong-pr", "wrong-original-review", "source-drift"):
            self.setUp()
            if mode == "recovery-actor": self.api.new_run["actor"] = {
                "id": c.OWNER_ID + 1, "type": "User"}
            if mode == "recovery-path": self.api.new_run["path"] = ".github/workflows/untrusted.yml"
            if mode == "rerun": self.api.new_run["run_attempt"] = 2
            if mode == "wrong-original-review": self.api.reviews = []
            if mode == "source-drift": self.api.main = "e"*40
            if mode == "head": self.pub["head_sha"] = "f"*40
            with self.subTest(mode=mode), self.assertRaises(c.Held):
                self.check(pr_num=100 if mode == "wrong-pr" else None)
            self.assertFalse(any(path.endswith("/merge") for path,_,_ in self.api.calls))

    def test_wrong_original_state_or_missing_timeout_refuses(self):
        for mode in ("not-final", "not-timeout", "repair-budget"):
            self.setUp()
            observed = deepcopy(self.obs)
            t = deepcopy(self.t)
            if mode == "not-final": self.api.run["status"] = "in_progress"
            if mode == "not-timeout": observed["state"] = "CI_PASSED"
            if mode == "repair-budget": t["max_repairs"] = 1
            with self.subTest(mode=mode), self.assertRaises(c.Held):
                self.check(task_override=t, observed=observed)
            self.assertFalse(any(path.endswith("/merge") for path,_,_ in self.api.calls))

    def test_recovery_workflow_preserves_owner_and_no_publisher_key(self):
        path = ROOT/".github/workflows/autonomous-turn-recover.yml"
        workflow = path.read_text()
        self.assertIn("environment: autonomous-turn-owner", workflow)
        self.assertIn("github.ref == 'refs/heads/main'", workflow)
        self.assertIn("github.actor == 'MichaelWave369'", workflow)
        self.assertIn("checks: write", workflow)
        self.assertNotIn("publisher_key", workflow)
        self.assertNotIn("create-github-app-token", workflow)
        self.assertNotIn("phi-automerge", workflow)
        self.assertIn("github-token:", workflow)


if __name__ == "__main__":
    unittest.main()
