"""R2 low-risk code and post-merge handoff negative controls."""
import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import devloop_r2_policy as policy
import devloop_r2_handoff as handoff

SHA = "a" * 40
MERGED_SHA = "b" * 40
BASE_SHA = "c" * 40


def candidate(files=None):
    files = files or [{"filename": "web/src/components/Nav.tsx", "status": "modified",
                       "additions": 7, "deletions": 3,
                       "patch": "@@ -1,3 +1,7 @@\n+const value = true;"}]
    pr = {"state": "open", "draft": False, "changed_files": len(files),
          "base": {"ref": "main", "repo": {"full_name": policy.REPO}},
          "head": {"sha": SHA, "repo": {"full_name": policy.REPO}},
          "user": {"login": "MichaelWave369"},
          "labels": [{"name": policy.LABEL}]}
    return pr, files


def review(login="independent", sha=SHA, state="APPROVED"):
    return {"state": state, "commit_id": sha,
            "user": {"login": login, "type": "User"}}


def merged_event():
    return {
        "action": "closed", "pull_request": {
            "number": 71, "merged": True, "merge_commit_sha": MERGED_SHA,
            "base": {"ref": "main", "sha": BASE_SHA,
                     "repo": {"full_name": handoff.REPO}},
            "head": {"sha": SHA},
        }
    }


class CodeGateTests(unittest.TestCase):
    def test_tiny_allowlisted_component_is_candidate(self):
        pr, files = candidate()
        self.assertEqual(policy.verify_code_pr(pr, SHA, files)["lane"], "LOW_RISK_UI")

    def test_reject_unsafe_paths_and_changes(self):
        bad_paths = ["web/src/pages/Settings.tsx", "web/src/api/client.ts",
                     "web/src/components/../pages/Settings.tsx",
                     ".github/workflows/ci.yml", "scripts/devloop_automerge.py",
                     "web/package.json", "web/src/components/GraphView.tsx"]
        for path in bad_paths:
            pr, files = candidate()
            files[0]["filename"] = path
            with self.subTest(path=path), self.assertRaises(policy.CodeHeld):
                policy.verify_code_pr(pr, SHA, files)

    def test_reject_deleted_added_large_unavailable_patch_and_multiple_labels(self):
        for kind in ("added", "removed", "renamed"):
            pr, files = candidate()
            files[0]["status"] = kind
            with self.subTest(kind=kind), self.assertRaises(policy.CodeHeld):
                policy.verify_code_pr(pr, SHA, files)
        for mutation in ("patch", "size", "label", "fork", "stale"):
            pr, files = candidate()
            if mutation == "patch":
                files[0]["patch"] = None
            elif mutation == "size":
                files[0]["additions"] = 1000
            elif mutation == "label":
                pr["labels"].append({"name": "phi-automerge"})
            elif mutation == "fork":
                pr["head"]["repo"]["full_name"] = "malicious/fork"
            else:
                pr["head"]["sha"] = "d" * 40
            with self.subTest(mutation=mutation), self.assertRaises(policy.CodeHeld):
                policy.verify_code_pr(pr, SHA, files)

    def test_requires_actual_current_sha_independent_collaborator_approval(self):
        def make_api(reviews, permission="write"):
            def api(token, path, payload=None, method=None):
                if path.endswith("/reviews?per_page=100"):
                    return reviews
                if path.endswith("/collaborators/independent/permission"):
                    return {"permission": permission}
                raise AssertionError(path)
            return api
        approvals = policy.require_independent_review(
            make_api([review()]), "token", 71, SHA, "MichaelWave369")
        self.assertEqual(approvals, ["independent"])
        for reviews, permission in [
            ([], "write"),
            ([review(sha="b"*40)], "write"),
            ([review(state="CHANGES_REQUESTED")], "write"),
            ([review()], "read"),
            ([review(login="MichaelWave369")], "write"),
        ]:
            with self.subTest(reviews=reviews, perm=permission):
                with self.assertRaises(policy.CodeHeld):
                    policy.require_independent_review(
                        make_api(reviews, permission), "token", 71, SHA, "MichaelWave369")

    def test_latest_review_replaces_old_approval(self):
        reviews = [review(), review(state="COMMENTED")]
        def api(token, path, payload=None, method=None):
            if path.endswith("/reviews?per_page=100"):
                return reviews
            raise AssertionError("Should never validate superseded approval")
        with self.assertRaises(policy.CodeHeld):
            policy.require_independent_review(api, "token", 71, SHA, "MichaelWave369")


class HandoffTests(unittest.TestCase):
    def test_default_no_preapproval_never_executes(self):
        outcome = handoff.assess(merged_event(), handoff.REPO,
                                 {"schema": handoff.SCHEMA, "items": []})
        self.assertEqual(outcome["disposition"], "NO_PREAPPROVED_NEXT_RUNG")
        self.assertFalse(outcome["executable"])

    def test_exact_preapproved_task_produces_handoff_only(self):
        entry = {"source_pr": 71, "source_head_sha": SHA,
                 "approved_by": handoff.OWNER, "target_repo": handoff.REPO,
                 "task_id": "r2-next-001", "title": "Review the next bounded rung"}
        outcome = handoff.assess(
            merged_event(), handoff.REPO,
            {"schema": handoff.SCHEMA, "items": [entry]})
        self.assertEqual(outcome["disposition"], "READY_FOR_OPERATOR_DISPATCH")
        self.assertFalse(outcome["executable"])
        self.assertEqual(outcome["merge_commit_sha"], MERGED_SHA)

    def test_approval_cannot_be_reused_on_a_changed_pr(self):
        entry = {"source_pr": 71, "source_head_sha": "d"*40,
                 "approved_by": handoff.OWNER, "target_repo": handoff.REPO,
                 "task_id": "r2-next-001", "title": "Review the next bounded rung"}
        with self.assertRaises(handoff.HandoffHeld):
            handoff.assess(merged_event(), handoff.REPO,
                           {"schema": handoff.SCHEMA, "items": [entry]})

    def test_reject_unmerged_duplicate_wrong_repo_and_bad_manifest(self):
        event = merged_event()
        event["pull_request"]["merged"] = False
        with self.assertRaises(handoff.HandoffHeld):
            handoff.assess(event, handoff.REPO,
                           {"schema": handoff.SCHEMA, "items": []})
        event = merged_event()
        with self.assertRaises(handoff.HandoffHeld):
            handoff.assess(event, handoff.REPO,
                           {"schema": handoff.SCHEMA, "items": [
                               {"source_pr": 71}, {"source_pr": 71}]})
        with self.assertRaises(handoff.HandoffHeld):
            handoff.assess(event, "untrusted/fork",
                           {"schema": handoff.SCHEMA, "items": []})
        with self.assertRaises(handoff.HandoffHeld):
            handoff.assess(event, handoff.REPO, {"items": []})


class CodeWorkflowIntegrationTests(unittest.TestCase):
    def test_owner_code_label_requires_real_review_green_ci_and_exact_sha(self):
        import devloop_automerge as gate
        pr, files = candidate()
        calls = []
        def mock_api(token, path, payload=None, method=None):
            calls.append((path, payload, method))
            if path == "/repos/" + gate.REPO:
                return {"allow_auto_merge": True}
            if path == "/repos/" + gate.REPO + "/pulls/71":
                return pr
            if path.endswith("/pulls/71/files?per_page=100"):
                return files
            if path.endswith("/pulls/71/reviews?per_page=100"):
                return [review()]
            if path.endswith("/collaborators/independent/permission"):
                return {"permission": "write"}
            if path.endswith("/check-runs?per_page=100"):
                runs = [{"name": name, "status": "completed", "conclusion": "success",
                         "app": {"slug": "github-actions"}}
                        for name in gate.REQUIRED]
                return {"total_count": len(runs), "check_runs": runs}
            if path.endswith("/pulls/71/merge"):
                self.assertEqual(method, "PUT")
                self.assertEqual(payload, {"sha": SHA, "merge_method": "squash"})
                return {"merged": True}
            raise AssertionError("unexpected API path " + path)
        old_api, old_protected = gate.api, gate.protected
        try:
            gate.api = mock_api
            gate.protected = lambda token: None
            event = {"action": "labeled", "label": {"name": gate.CODE_LABEL},
                     "sender": {"login": gate.OWNER},
                     "pull_request": {"number": 71, "head": {"sha": SHA}}}
            result = gate.run(event, "token", gate.REPO)
            self.assertEqual(result, "R2_CODE_EXACT_HEAD_REVIEWED_CI_GREEN_MERGED")
            self.assertEqual(sum(p.endswith("/merge") for p, _, _ in calls), 1)
        finally:
            gate.api, gate.protected = old_api, old_protected

    def test_no_review_no_merge_even_with_owner_label_and_green_ci(self):
        import devloop_automerge as gate
        pr, files = candidate()
        paths = []
        def mock_api(token, path, payload=None, method=None):
            paths.append(path)
            if path == "/repos/" + gate.REPO:
                return {"allow_auto_merge": True}
            if path == "/repos/" + gate.REPO + "/pulls/71":
                return pr
            if path.endswith("/pulls/71/files?per_page=100"):
                return files
            if path.endswith("/pulls/71/reviews?per_page=100"):
                return []
            raise AssertionError("Unexpected write or check: " + path)
        old_api, old_protected = gate.api, gate.protected
        try:
            gate.api = mock_api
            gate.protected = lambda token: None
            event = {"action": "labeled", "label": {"name": gate.CODE_LABEL},
                     "sender": {"login": gate.OWNER},
                     "pull_request": {"number": 71, "head": {"sha": SHA}}}
            with self.assertRaises(gate.Block) as ctx:
                gate.run(event, "token", gate.REPO)
            self.assertEqual(str(ctx.exception), "R2_INDEPENDENT_WRITE_REVIEW_REQUIRED")
            self.assertFalse(any(p.endswith("/merge") for p in paths))
        finally:
            gate.api, gate.protected = old_api, old_protected


if __name__ == "__main__":
    unittest.main()
