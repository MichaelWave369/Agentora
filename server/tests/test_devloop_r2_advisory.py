"""R2 advisory stays read-only and never confers merge authority."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import devloop_r2_advisory as advisory
import devloop_r2_policy as policy

SHA = "a" * 40

class AdvisoryTests(unittest.TestCase):
    def base_pr(self):
        return {"state": "open", "draft": False, "changed_files": 1,
                "head": {"sha": SHA, "repo": {"full_name": policy.REPO}},
                "base": {"ref": "main", "repo": {"full_name": policy.REPO}},
                "user": {"login": "MichaelWave369"}}

    def base_file(self):
        return {"filename": "web/src/components/Nav.tsx", "status": "modified",
                "additions": 2, "deletions": 1,
                "patch": "@@ -1 +1,2 @@\n+const x = true;"}

    def test_advisory_is_not_merge_authority(self):
        paths = []
        def api(token, path, payload=None, method=None):
            self.assertIsNone(payload)
            paths.append(path)
            if path.endswith("/pulls/24"):
                return self.base_pr()
            if path.endswith("/pulls/24/files?per_page=100"):
                return [self.base_file()]
            if path.endswith("/pulls/24/reviews?per_page=100"):
                return [{"state": "APPROVED", "commit_id": SHA,
                         "user": {"login": "reviewer", "type": "User"}}]
            if path.endswith("/collaborators/reviewer/permission"):
                return {"permission": "write"}
            raise AssertionError(path)
        event = {"pull_request": {"number": 24}}
        report = advisory.analyze(event, policy.REPO, api, "token")
        self.assertEqual(report["disposition"], "LOW_RISK_UI_CANDIDATE")
        self.assertEqual(report["review_status"],
                         "CURRENT_SHA_INDEPENDENT_APPROVAL_VERIFIED")
        self.assertFalse(report["merge_authorized"])
        self.assertFalse(any("/merge" in p for p in paths))

    def test_unsafe_files_are_held_not_classified_as_low_risk(self):
        def api(token, path, payload=None, method=None):
            if path.endswith("/pulls/24"):
                return self.base_pr()
            if path.endswith("/pulls/24/files?per_page=100"):
                row = self.base_file()
                row["filename"] = ".github/workflows/ci.yml"
                return [row]
            raise AssertionError("Review API must not be called for unsafe paths")
        report = advisory.analyze(
            {"pull_request": {"number": 24}}, policy.REPO, api, "token")
        self.assertEqual(report["disposition"], "OUT_OF_SCOPE")
        self.assertFalse(report["merge_authorized"])

    def test_api_writer_is_rejected_before_network(self):
        with self.assertRaises(policy.CodeHeld):
            advisory.read("secret", "/repos/" + policy.REPO, {"x": 1}, "POST")

    def test_fork_or_draft_never_passes_classification(self):
        for mode in ("fork", "draft"):
            pr = self.base_pr()
            if mode == "fork":
                pr["head"]["repo"]["full_name"] = "untrusted/fork"
            else:
                pr["draft"] = True
            def api(token, path, payload=None, method=None):
                if path.endswith("/pulls/24"):
                    return pr
                raise AssertionError(path)
            report = advisory.analyze(
                {"pull_request": {"number": 24}}, policy.REPO, api, "token")
            self.assertEqual(report["disposition"], "OUT_OF_SCOPE")


if __name__ == "__main__":
    unittest.main()
