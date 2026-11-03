"""Fleet R0.2 contracts: fixtures prove proposal-only behavior."""
import base64
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r01_audit as fleet
import fleet_r02_plan as plan

NOW = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
HEAD = "a" * 40
OTHER = "b" * 40


def row(name="Agentora", sha=HEAD, visibility="public", status="UNVERIFIED", ident=1):
    data = {
        "repository": "MichaelWave369/" + name,
        "repository_id": ident,
        "visibility": visibility,
        "head_sha": sha,
        "ci": "OBSERVED_RUNS_GREEN_AT_HEAD_NOT_BUILD_PROOF",
        "pages": "HTML_REACHABLE_NOT_RUNTIME_VERIFIED",
        "release": "PUBLISHED_METADATA_NOT_FUNCTIONALITY_VERIFIED",
        "relationships": ["PhiOS"],
        "completion": status,
    }
    return data


def audit(rows=None):
    rows = rows if rows is not None else [row(), row("PhiOS", status="NOT_AUDITED", ident=2)]
    return {
        "schema": fleet.SCHEMA,
        "generated_utc": (NOW - timedelta(minutes=5)).isoformat(),
        "owner": fleet.OWNER,
        "repository_count": len(rows),
        "deep_audited_count": sum(r["completion"] == "UNVERIFIED" for r in rows),
        "merge_authorized": False,
        "job_dispatch_authorized": False,
        "repositories": rows,
    }


def payload(content):
    raw = content if isinstance(content, str) else json.dumps(content)
    return {"encoding": "base64", "content": base64.b64encode(raw.encode()).decode()}


def fake_get(path, token):
    if path.endswith("/contents"):
        return [{"name": "package.json"}, {"name": "index.html"},
                {"name": "README.md"}, {"name": "src"}]
    if path.endswith("/contents/package.json"):
        return payload({"dependencies": {"react": "18", "vite": "^7"}})
    if path.endswith("/readme"):
        return payload("A React application; see https://github.com/MichaelWave369/PhiOS")
    raise AssertionError("unexpected API path " + path)


class FleetR02Tests(unittest.TestCase):
    def test_green_ci_html_and_release_never_promote_to_complete(self):
        result = plan.generate(audit(), fake_get, now=NOW)
        self.assertEqual(result["verified_complete_count"], 0)
        self.assertFalse(result["merge_authorized"])
        self.assertFalse(result["job_dispatch_authorized"])
        self.assertTrue(result["operator_review_required"])
        self.assertEqual(result["inventory_count"], 2)
        self.assertEqual(result["deep_audited_count"], 1)
        self.assertEqual(result["not_audited_count"], 1)
        self.assertEqual(result["profiles"][0]["surface_candidates"], ["web_app"])
        self.assertEqual(result["profiles"][0]["completion"], "UNVERIFIED")
        self.assertTrue(result["tasks"])
        self.assertTrue(all(t["state"] == "REVIEW_ONLY_NOT_DISPATCHABLE"
                            for t in result["tasks"]))
        self.assertEqual(result["edges"][0]["kind"], plan.LINK_TYPE)
        self.assertFalse(result["edges"][0]["verified_runtime_integration"])

    def test_stale_audit_refused_even_when_green(self):
        bad = audit()
        bad["generated_utc"] = (NOW - timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(plan.PlanHeld, "STALE"):
            plan.generate(bad, fake_get, now=NOW)

    def test_private_public_boundary(self):
        private = audit([row(visibility="private")])
        with self.assertRaisesRegex(plan.PlanHeld, "PRIVATE_INPUT_REJECTED"):
            plan.generate(private, fake_get, now=NOW)
        result = plan.generate(private, fake_get, now=NOW, allow_private=True)
        self.assertFalse(result["public_output"])
        self.assertEqual(result["verified_complete_count"], 0)

    def test_rejects_forged_completion_and_authority(self):
        bad = audit()
        bad["repositories"][0]["completion"] = "COMPLETE"
        with self.assertRaises(plan.PlanHeld):
            plan.generate(bad, fake_get, now=NOW)
        bad = audit()
        bad["merge_authorized"] = True
        with self.assertRaisesRegex(plan.PlanHeld, "AUTHORITY"):
            plan.generate(bad, fake_get, now=NOW)

    def test_missing_head_is_review_only_with_blocking_precondition(self):
        result = plan.generate(audit([row(sha=None)]), fake_get, now=NOW)
        self.assertTrue(all(x["prerequisites"] == [plan.SHA_REQUIRED] for x in result["tasks"]))
        self.assertTrue(all(x["head_sha"] == "UNVERIFIED_HEAD" for x in result["tasks"]))

    def test_receipts_dont_authorize_completion_even_when_matching(self):
        receipts = [
            {"repository": "MichaelWave369/Agentora", "head_sha": HEAD,
             "check_id": "browser_smoke", "observed_utc": NOW.isoformat(),
             "expires_utc": (NOW + timedelta(days=2)).isoformat(),
             "result": "PASS", "merge_authorized": True},
            {"repository": "MichaelWave369/Agentora", "head_sha": OTHER,
             "check_id": "build", "observed_utc": NOW.isoformat(),
             "expires_utc": (NOW + timedelta(days=2)).isoformat()},
        ]
        result = plan.generate(audit(), fake_get, receipts=receipts, now=NOW)
        claims = result["profiles"][0]["receipt_review"]
        self.assertEqual(claims[0]["disposition"], "SHA_AND_TIME_MATCH_UNTRUSTED_PROVENANCE")
        self.assertEqual(claims[1]["disposition"], "INVALID_OR_STALE_EVIDENCE")
        self.assertEqual(result["verified_complete_count"], 0)
        self.assertFalse(result["merge_authorized"])

    def test_unknown_project_gets_classification_review(self):
        def unknown(path, token):
            return [] if path.endswith("/contents") else None
        result = plan.generate(audit([row()]), unknown, now=NOW)
        self.assertEqual(result["profiles"][0]["surface_candidates"], [])
        self.assertEqual(result["tasks"][0]["check_id"], "classification_review")
        self.assertEqual(result["tasks"][0]["priority"], 110)

    def test_roles_can_coexist_without_confusing_with_verified_runtime(self):
        obj = {
            "paths": ["package.json", "index.html", "settings.gradle"],
            "package": {"dependencies": {"react": "^18"}},
            "readme": "WebXR Quest 3",
        }
        category = plan.classify(row(), obj)
        self.assertEqual(category["surface_candidates"], ["android", "web_app", "webxr"])
        self.assertIn("ROOT_ANDROID_BUILD_HINT", category["classification_signals"])

    def test_queue_stable_and_prioritized(self):
        first = plan.generate(audit(), fake_get, now=NOW)
        second = plan.generate(audit(), fake_get, now=NOW)
        self.assertEqual(first["tasks"], second["tasks"])
        scores = [t["priority"] for t in first["tasks"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(len({t["id"] for t in first["tasks"]}), len(first["tasks"]))

    def test_invalid_coverage_and_duplicate_ids_hold(self):
        bogus = audit()
        bogus["deep_audited_count"] = 99
        with self.assertRaisesRegex(plan.PlanHeld, "DEEP_COVERAGE"):
            plan.generate(bogus, fake_get, now=NOW)
        duplicate = audit([row(), row("PhiOS")])
        with self.assertRaisesRegex(plan.PlanHeld, "DUPLICATE_REPOSITORY_ID"):
            plan.generate(duplicate, fake_get, now=NOW)

    def test_read_errors_are_visible_not_silently_reclassified(self):
        def err(path, token):
            raise fleet.AuditHeld("API_LIMIT")
        result = plan.generate(audit([row()]), err, now=NOW)
        profile = result["profiles"][0]
        self.assertEqual(profile["surface_candidates"], [])
        self.assertIn("ROOT_FETCH_HELD", profile["limitations"])
        self.assertEqual(profile["completion"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main()
