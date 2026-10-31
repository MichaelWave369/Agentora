"""Offline tests for the DevLoop R0 GitHub auto-merge gate."""
import importlib.util
from pathlib import Path
import unittest

script = Path(__file__).resolve().parents[2] / "scripts" / "devloop_automerge.py"
spec = importlib.util.spec_from_file_location("devloop_automerge", script)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
SHA = "a" * 40

def candidate():
    return ({
        "state": "open", "draft": False, "changed_files": 1,
        "base": {"ref": "main", "repo": {"full_name": gate.REPO}},
        "head": {"sha": SHA, "repo": {"full_name": gate.REPO}},
        "labels": [{"name": gate.LABEL}]
    }, [{"filename": "docs/safe.md", "status": "modified"}])

def rules(contexts=None):
    contexts = contexts if contexts is not None else sorted(gate.REQUIRED)
    return [{
        "target": "branch", "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"]}},
        "rules": [{"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": c} for c in contexts]}}]
    }]

class DevLoopGateTests(unittest.TestCase):
    def test_allowed_docs_pr(self):
        pr, files = candidate()
        gate.verify_pr(pr, SHA, files)
        gate.verify_rules(rules())

    def test_absent_disabled_and_incomplete_ruleset(self):
        variants = [[], rules(["web"]), rules()]
        variants[-1][0]["enforcement"] = "disabled"
        for case in variants:
            with self.subTest(case=case), self.assertRaises(gate.Block):
                gate.verify_rules(case)

    def test_wrong_branch_ruleset_refused(self):
        config = rules()
        config[0]["conditions"]["ref_name"]["include"] = ["refs/heads/release"]
        with self.assertRaises(gate.Block):
            gate.verify_rules(config)

    def test_docs_only(self):
        for filename in ("README.md", "docs/one.md", "docs/nested/two.md"):
            self.assertTrue(gate.is_doc(filename))
        for filename in (".github/workflows/ci.yml", "scripts/a.py", "requirements.txt",
                         "docs/../unsafe.md", "docs//bad.md", "docs/README.txt"):
            self.assertFalse(gate.is_doc(filename))

    def test_rejections(self):
        for mode in ("draft", "fork", "stale", "blocked", "rename", "delete", "count"):
            pr, files = candidate()
            sha = SHA
            if mode == "draft":
                pr["draft"] = True
            if mode == "fork":
                pr["head"]["repo"]["full_name"] = "untrusted/fork"
            if mode == "stale":
                sha = "b" * 40
            if mode == "blocked":
                pr["labels"].append({"name": "hold"})
            if mode == "rename":
                files[0]["status"] = "renamed"
            if mode == "delete":
                files[0]["status"] = "removed"
            if mode == "count":
                pr["changed_files"] = 2
            with self.subTest(mode=mode), self.assertRaises(gate.Block):
                gate.verify_pr(pr, sha, files)

    def test_no_mutation_without_owner_label(self):
        original = gate.api
        calls = []
        def fake_api(token, path, payload=None):
            calls.append((path, payload))
            if "/pulls/3" in path:
                pr, _ = candidate()
                return dict(pr, number=3)
            raise AssertionError("no additional calls expected")
        gate.api = fake_api
        try:
            snapshot = {"number": 3, "head": {"sha": SHA}}
            event = {"action": "labeled", "label": {"name": gate.LABEL},
                     "sender": {"login": "attacker"}, "pull_request": snapshot}
            with self.assertRaises(gate.Block):
                gate.run(event, "fake", gate.REPO)
            self.assertEqual(len(calls), 1)
        finally:
            gate.api = original

    def test_hidden_settings_is_not_misreported_as_disabled(self):
        original = gate.api
        calls = []
        def fake_api(token, path, payload=None):
            calls.append(path)
            if "/pulls/3" in path:
                pr, _ = candidate()
                return dict(pr, number=3)
            if path == "/repos/" + gate.REPO:
                return {"full_name": gate.REPO}  # contents:read-only token
            raise AssertionError("unexpected request")
        gate.api = fake_api
        try:
            event = {"action": "labeled", "label": {"name": gate.LABEL},
                     "sender": {"login": gate.OWNER},
                     "pull_request": {"number": 3, "head": {"sha": SHA}}}
            with self.assertRaises(gate.Block) as ctx:
                gate.run(event, "fake", gate.REPO)
            self.assertEqual(str(ctx.exception),
                             "AUTO_MERGE_SETTING_HIDDEN_CHECK_TOKEN_CONTENTS_WRITE")
            self.assertEqual(len(calls), 2)
        finally:
            gate.api = original

    def test_graphql_clean_vs_permission_errors(self):
        old = gate.api
        pr = {"node_id": "PR_test"}
        def response_api(token, path, payload=None, method=None):
            return {"data": {"enablePullRequestAutoMerge": None},
                    "errors": [{"type": "UNPROCESSABLE",
                                "message": "Pull request Pull request is in clean status"}]}
        try:
            gate.api = response_api
            with self.assertRaises(gate.AlreadyClean):
                gate.graphql("token", pr, True, SHA)
            gate.api = lambda *args, **kwargs: {
                "data": {"enablePullRequestAutoMerge": None},
                "errors": [{"message": "Resource not accessible by integration"}]}
            with self.assertRaises(gate.Block) as ctx:
                gate.graphql("token", pr, True, SHA)
            self.assertEqual(str(ctx.exception), "GRAPHQL_TOKEN_ACCESS_REJECTED")
        finally:
            gate.api = old

    def test_direct_merge_exact_head_only_after_required_green(self):
        old_api, old_protected = gate.api, gate.protected
        pr, files = candidate()
        calls = []
        def fake_api(token, path, payload=None, method=None):
            calls.append((path, payload, method))
            if path.endswith("/check-runs?per_page=100"):
                return {"total_count": 3, "check_runs": [
                    {"name": name, "status": "completed", "conclusion": "success",
                     "app": {"slug": "github-actions"}} for name in sorted(gate.REQUIRED)]}
            if path.endswith("/pulls/52"):
                return pr
            if path.endswith("/pulls/52/merge"):
                self.assertEqual(payload, {"sha": SHA, "merge_method": "squash"})
                self.assertEqual(method, "PUT")
                return {"merged": True, "sha": "b" * 40}
            raise AssertionError("unexpected API path: " + path)
        try:
            gate.api = fake_api
            gate.protected = lambda token: gate.verify_rules(rules())
            result = gate.merge_already_clean("token", 52, SHA, files)
            self.assertEqual(result, "EXACT_HEAD_REQUIRED_CI_GREEN_MERGED")
            self.assertEqual(sum(p.endswith("/merge") for p, _, _ in calls), 1)
        finally:
            gate.api, gate.protected = old_api, old_protected

    def test_direct_merge_refuses_failed_or_missing_checks(self):
        old_api, old_protected = gate.api, gate.protected
        pr, files = candidate()
        for failure in ("missing", "failed", "forged"):
            calls = []
            def fake_api(token, path, payload=None, method=None):
                calls.append(path)
                if path.endswith("/check-runs?per_page=100"):
                    runs = [{"name": name, "status": "completed",
                             "conclusion": "success", "app": {"slug": "github-actions"}}
                            for name in sorted(gate.REQUIRED)]
                    if failure == "missing":
                        runs = runs[:2]
                    if failure == "failed":
                        runs[0]["conclusion"] = "failure"
                    if failure == "forged":
                        runs[0]["app"]["slug"] = "other-app"
                    return {"total_count": len(runs), "check_runs": runs}
                raise AssertionError("unexpected write or live PR read")
            try:
                gate.api = fake_api
                gate.protected = lambda token: gate.verify_rules(rules())
                with self.subTest(failure=failure), self.assertRaises(gate.Block):
                    gate.merge_already_clean("token", 52, SHA, files)
                self.assertFalse(any(p.endswith("/merge") for p in calls))
            finally:
                gate.api, gate.protected = old_api, old_protected

    def test_direct_merge_refuses_replaced_head(self):
        old_api, old_protected = gate.api, gate.protected
        pr, files = candidate()
        def fake_api(token, path, payload=None, method=None):
            if path.endswith("/check-runs?per_page=100"):
                return {"total_count": 3, "check_runs": [
                    {"name": name, "status": "completed", "conclusion": "success",
                     "app": {"slug": "github-actions"}} for name in sorted(gate.REQUIRED)]}
            if path.endswith("/pulls/52"):
                altered = dict(pr)
                altered["head"] = {"sha": "b"*40, "repo": {"full_name": gate.REPO}}
                return altered
            raise AssertionError("must never send merge request")
        try:
            gate.api = fake_api
            gate.protected = lambda token: gate.verify_rules(rules())
            with self.assertRaises(gate.Block):
                gate.merge_already_clean("token", 52, SHA, files)
        finally:
            gate.api, gate.protected = old_api, old_protected


if __name__ == "__main__":
    unittest.main()
