"""R2.1 Solo Sovereign Mode: owner approval is not independent review.

These tests run entirely offline with in-memory GitHub responses. No merge is
sent unless the owner-authored one-file PR, exact SHA and full CI are rechecked.
"""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import devloop_automerge as gate
import devloop_r2_policy as policy

SHA = "a" * 40
BASE_SHA = "c" * 40


def solo_candidate():
    pr = {
        "state": "open", "draft": False, "changed_files": 1,
        "user": {"login": gate.OWNER},
        "base": {"ref": "main", "sha": BASE_SHA,
                 "repo": {"full_name": gate.REPO}},
        "head": {"sha": SHA, "repo": {"full_name": gate.REPO}},
        "labels": [{"name": gate.SOLO_LABEL}]
    }
    files = [{
        "filename": "web/src/components/Nav.tsx", "status": "modified",
        "additions": 1, "deletions": 1,
        "patch": '@@ -1 +1 @@\n-<nav aria-label="Primary navigation">\n+<nav aria-label="Main navigation">'
    }]
    event = {
        "action": "labeled", "label": {"name": gate.SOLO_LABEL},
        "sender": {"login": gate.OWNER},
        "pull_request": {"number": 82, "head": {"sha": SHA}}
    }
    return pr, files, event


class SoloPolicyTests(unittest.TestCase):
    def test_owner_authored_single_nav_change_is_eligible(self):
        pr, files, _ = solo_candidate()
        result = policy.verify_solo_pr(pr, SHA, files)
        self.assertEqual(result["lane"], "SOLO_SOVEREIGN_R21")
        self.assertEqual(result["paths"], ["web/src/components/Nav.tsx"])

    def test_reject_other_code_workflows_docs_forks_and_other_author(self):
        for name in ("web/src/components/TemplateGallery.tsx",
                     "web/src/api/client.ts", ".github/workflows/ci.yml",
                     "scripts/devloop_automerge.py", "docs/manual.md"):
            pr, files, _ = solo_candidate()
            files[0]["filename"] = name
            with self.subTest(name=name), self.assertRaises(policy.CodeHeld):
                policy.verify_solo_pr(pr, SHA, files)
        for case in ("other_author", "fork", "draft", "moved_sha",
                     "missing_label", "held_label", "docs_label",
                     "reviewed_label", "too_big", "two_files"):
            pr, files, _ = solo_candidate()
            if case == "other_author":
                pr["user"]["login"] = "untrusted"
            elif case == "fork":
                pr["head"]["repo"]["full_name"] = "third-party/fork"
            elif case == "draft":
                pr["draft"] = True
            elif case == "moved_sha":
                pr["head"]["sha"] = "b" * 40
            elif case == "missing_label":
                pr["labels"] = []
            elif case == "held_label":
                pr["labels"].append({"name": "security-review"})
            elif case == "docs_label":
                pr["labels"].append({"name": gate.LABEL})
            elif case == "reviewed_label":
                pr["labels"].append({"name": gate.CODE_LABEL})
            elif case == "too_big":
                files[0]["additions"] = 11
            elif case == "two_files":
                files.append(dict(files[0], filename="web/src/components/TemplateGallery.tsx"))
                pr["changed_files"] = 2
            with self.subTest(case=case), self.assertRaises(policy.CodeHeld):
                policy.verify_solo_pr(pr, SHA, files)

    def test_existing_code_and_doc_lanes_do_not_accept_solo_label(self):
        pr, files, _ = solo_candidate()
        pr["labels"].append({"name": gate.CODE_LABEL})
        with self.assertRaises(policy.CodeHeld):
            policy.verify_code_pr(pr, SHA, files)
        docs = [{"filename": "docs/test.md", "status": "modified"}]
        pr["labels"].append({"name": gate.LABEL})
        with self.assertRaises(gate.Block):
            gate.verify_pr(pr, SHA, docs)


class SoloWorkflowTests(unittest.TestCase):
    def make_api(self, *, pending=False, moved=False, base_moved=False,
                 diff_changed=False, forged=False):
        pr, files, event = solo_candidate()
        calls = []
        counters = {"pr": 0, "files": 0}
        def fake_api(token, path, payload=None, method=None):
            calls.append((path, payload, method))
            if path == "/repos/" + gate.REPO:
                return {"allow_auto_merge": True}
            if path.endswith("/pulls/82"):
                counters["pr"] += 1
                response = dict(pr)
                if counters["pr"] >= 2:
                    if moved:
                        response["head"] = {
                            "sha": "b" * 40, "repo": {"full_name": gate.REPO}}
                    if base_moved:
                        response["base"] = dict(pr["base"], sha="d" * 40)
                return response
            if path.endswith("/pulls/82/files?per_page=100"):
                counters["files"] += 1
                if diff_changed and counters["files"] > 1:
                    return [dict(files[0], patch=files[0]["patch"] + "\n+// changed")]
                return files
            if path.endswith("/check-runs?per_page=100"):
                checks = [
                    {"name": name, "status": "completed", "conclusion": "success",
                     "app": {"slug": "github-actions"}}
                    for name in sorted(gate.REQUIRED)]
                if pending:
                    checks[0]["status"] = "in_progress"
                    checks[0]["conclusion"] = None
                if forged:
                    checks[0]["app"]["slug"] = "untrusted"
                return {"total_count": 3, "check_runs": checks}
            if path.endswith("/pulls/82/merge"):
                self.assertEqual(method, "PUT")
                self.assertEqual(payload, {"sha": SHA, "merge_method": "squash"})
                return {"merged": True, "sha": "d" * 40}
            raise AssertionError("unexpected GitHub operation: " + path)
        return fake_api, calls, event

    def test_owner_label_merges_only_current_sha_after_green(self):
        api, calls, event = self.make_api()
        with patch.object(gate, "api", api), patch.object(gate, "protected", lambda t: None):
            result = gate.run(event, "fake", gate.REPO)
        self.assertEqual(result, "R21_SOLO_EXACT_HEAD_CI_GREEN_MERGED")
        self.assertEqual(sum(p.endswith("/merge") for p, _, _ in calls), 1)
        self.assertFalse(any(p == "/graphql" for p, _, _ in calls))
        self.assertEqual(sum(p.endswith("/check-runs?per_page=100") for p, _, _ in calls), 2)

    def test_owner_label_from_nonowner_cannot_merge(self):
        api, calls, event = self.make_api()
        event["sender"]["login"] = "not-owner"
        with patch.object(gate, "api", api), patch.object(gate, "protected", lambda t: None):
            with self.assertRaises(gate.Block) as context:
                gate.run(event, "fake", gate.REPO)
        self.assertEqual(str(context.exception), "NOT_OWNER_LABEL_EVENT")
        self.assertFalse(any(p.endswith("/merge") for p, _, _ in calls))

    def test_pending_forged_moved_base_or_diff_never_merges(self):
        for case in ("pending", "forged", "moved", "base_moved", "diff_changed"):
            opts = {case: True}
            api, calls, event = self.make_api(**opts)
            with self.subTest(case=case):
                with patch.object(gate, "api", api), patch.object(gate, "protected", lambda t: None):
                    with self.assertRaises(gate.Block):
                        gate.run(event, "fake", gate.REPO)
                self.assertFalse(any(p.endswith("/merge") for p, _, _ in calls))

    def test_no_merge_if_event_head_is_stale(self):
        api, calls, event = self.make_api()
        event["pull_request"]["head"]["sha"] = "b" * 40
        with patch.object(gate, "api", api), patch.object(gate, "protected", lambda t: None):
            with self.assertRaises(gate.Block):
                gate.run(event, "fake", gate.REPO)
        self.assertFalse(any(p.endswith("/merge") for p, _, _ in calls))

    def test_audit_explicitly_identifies_solo_lane(self):
        _, _, event = solo_candidate()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(gate.os, "makedirs") as mkdir:
                original_open = gate.open if hasattr(gate, "open") else open
                def redirect_open(filename, *args, **kwargs):
                    return original_open(str(Path(directory) / Path(filename).name), *args, **kwargs)
                with patch("builtins.open", side_effect=redirect_open):
                    gate.write_audit(event, "R21_SOLO_EXACT_HEAD_CI_GREEN_MERGED", "SUCCESS")
            data = json.loads((Path(directory) / "merge-decision.json").read_text())
            self.assertEqual(data["lane"], "solo")
            self.assertEqual(data["head_sha"], SHA)


if __name__ == "__main__":
    unittest.main()
