"""Read-only Fleet Mode contracts and deterministic evidence tests."""
import base64
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r01_audit as fleet

SHA = "a" * 40


def owner_row(name, ident=1, private=False):
    return {
        "name": name,
        "id": ident,
        "owner": {"login": fleet.OWNER},
        "private": private,
        "default_branch": "main",
        "archived": False,
    }


def coded(value):
    raw = value if isinstance(value, str) else json.dumps(value)
    return {"encoding": "base64", "content": base64.b64encode(raw.encode()).decode()}


class InventoryTests(unittest.TestCase):
    def test_pagination_uses_public_owner_endpoint_and_exhausts_all(self):
        first = [owner_row(f"test-{i}", i + 1) for i in range(100)]
        second = [owner_row("last", 101)]
        paths = []

        def get(path, token):
            self.assertIsNone(token)
            paths.append(path)
            return first if path.endswith("page=1") else second

        rows = fleet.inventory(get, None)
        self.assertEqual(len(rows), 101)
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(p.startswith("/users/MichaelWave369/repos?") for p in paths))

    def test_private_scope_requires_explicit_token(self):
        with self.assertRaisesRegex(fleet.AuditHeld, "REQUIRES_TOKEN"):
            fleet.inventory(lambda p, t: [], None, include_private=True)
        records = [owner_row("public", 1), owner_row("hidden", 2, private=True)]
        public = fleet.inventory(lambda p, t: records, None)
        self.assertEqual([r["name"] for r in public], ["public"])
        private = fleet.inventory(lambda p, t: records, "token", include_private=True)
        self.assertEqual(len(private), 2)

    def test_duplicate_id_and_invalid_rows_hold(self):
        bad = [owner_row("a", 42), owner_row("b", 42)]
        with self.assertRaisesRegex(fleet.AuditHeld, "DUPLICATE_ID"):
            fleet.inventory(lambda p, t: bad, None)
        with self.assertRaisesRegex(fleet.AuditHeld, "ROW_INVALID"):
            fleet.inventory(lambda p, t: [None], None)

    def test_refuses_non_get_or_arbitrary_url_paths(self):
        for value in ("https://evil.example", "broken", "/https://example.com"):
            with self.subTest(value=value), self.assertRaises(fleet.AuditHeld):
                fleet.github_get(value, None)

    def test_repo_name_validation(self):
        for value in ("../../private", "abc/xyz", "my repo", "", ".."):
            with self.subTest(value=value), self.assertRaises(fleet.AuditHeld):
                fleet.repo_path(value)


class ObservationTests(unittest.TestCase):
    def fake_get(self, path, token):
        if path.endswith("/branches/main"):
            return {"commit": {"sha": SHA}}
        if "/actions/runs?" in path:
            return {"workflow_runs": [{"head_sha": SHA, "status": "completed",
                                      "conclusion": "success"}]}
        if path.endswith("/pages"):
            return {"html_url": "https://michaelwave369.github.io/Agentora/"}
        if "/releases?" in path:
            return [{"draft": False, "tag_name": "v1"}]
        if path.endswith("/contents/package.json"):
            return coded({"dependencies": {"react": "^18"}})
        if path.endswith("/readme"):
            return coded("See https://github.com/MichaelWave369/PhiOS and "
                         "https://github.com/MichaelWave369/OtherProject")
        raise AssertionError("Unexpected API read: " + path)

    def test_green_is_never_promoted_to_functionality_or_completion(self):
        row = owner_row("Agentora")
        known = {"agentora": "Agentora", "phios": "PhiOS"}
        result = fleet.scan_one(row, self.fake_get, None, known,
                                probe=lambda u, n: "HTML_REACHABLE_NOT_RUNTIME_VERIFIED")
        self.assertEqual(result["software_type"], "REACT_CANDIDATE")
        self.assertEqual(result["ci"], "OBSERVED_RUNS_GREEN_AT_HEAD_NOT_BUILD_PROOF")
        self.assertEqual(result["release"], "PUBLISHED_METADATA_NOT_FUNCTIONALITY_VERIFIED")
        self.assertEqual(result["completion"], "UNVERIFIED")
        self.assertEqual(result["relationships"], ["PhiOS"])
        self.assertEqual(len(result["roadmap"]), 1)
        self.assertFalse(result.get("merge_authorized", False))

    def test_stale_green_run_is_not_head_green(self):
        def stale(path, token):
            if "/actions/runs?" in path:
                return {"workflow_runs": [{"head_sha": "b" * 40, "status": "completed",
                                          "conclusion": "success"}]}
            return self.fake_get(path, token)
        result = fleet.scan_one(owner_row("Agentora"), stale, None, {},
                                probe=lambda u, n: "HTTP_404")
        self.assertEqual(result["ci"], "NO_RECENT_RUN_AT_HEAD")
        self.assertEqual(result["pages"], "HTTP_404")
        self.assertEqual(result["completion"], "UNVERIFIED")

    def test_404_is_not_automatically_called_absent_functionality(self):
        def missing(path, token):
            return None
        result = fleet.scan_one(owner_row("Agentora"), missing, None, {})
        self.assertEqual(result["ci"], "NOT_VERIFIED")
        self.assertEqual(result["pages"], "NOT_CONFIGURED_OR_NOT_ACCESSIBLE")
        self.assertEqual(result["release"], "NOT_VERIFIED")
        self.assertEqual(result["completion"], "UNVERIFIED")

    def test_probe_does_not_fetch_custom_domain_or_wrong_path(self):
        for url in (
            "http://michaelwave369.github.io/Agentora/",
            "https://evil.example/Agentora/",
            "https://michaelwave369.github.io/Agentora-clone/",
            "https://michaelwave369.github.io/OtherRepo/",
            "https://michaelwave369.github.io@evil.example/Agentora/",
        ):
            self.assertEqual(fleet.probe_pages(url, "Agentora"),
                             "CUSTOM_OR_UNSAFE_URL_NOT_PROBED")

    def test_pilot_inventory_includes_unscanned_without_claiming_complete(self):
        rows = [owner_row("Agentora"), owner_row("OtherProject", 2)]
        report = fleet.assemble(rows, self.fake_get, None, "pilot",
                                probe=lambda u, n: "HTML_REACHABLE_NOT_RUNTIME_VERIFIED")
        self.assertEqual(report["repository_count"], 2)
        self.assertEqual(report["deep_audited_count"], 1)
        self.assertEqual(report["repositories"][1]["completion"], "NOT_AUDITED")
        self.assertFalse(report["merge_authorized"])
        self.assertFalse(report["job_dispatch_authorized"])
        md = fleet.markdown(report)
        self.assertIn("Completion verified: **0**", md)
        self.assertIn("Agentora", md)


if __name__ == "__main__":
    unittest.main()
