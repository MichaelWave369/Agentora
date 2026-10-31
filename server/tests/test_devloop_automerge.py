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

if __name__ == "__main__":
    unittest.main()
