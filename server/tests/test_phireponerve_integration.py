"""Contract tests for the read-only RepoNerve R1 public adapter."""
import unittest
from datetime import datetime, timedelta, timezone

from app.integrations.phireponerve_client import (
    RepoNerveUnavailable, collect_public_observations,
)

NOW = datetime(2026, 11, 7, 16, 0, tzinfo=timezone.utc)
TS = (NOW - timedelta(minutes=1)).isoformat()
PUBLIC = {"github_id": 42, "full_name": "MichaelWave369/BTM", "private": 0,
          "present": 1, "archived": 0}
PRIVATE = {"github_id": 43, "full_name": "MichaelWave369/HiddenProject",
           "private": 1, "present": 1, "archived": 0}
EVENTS = [
    {"id": 1, "github_id": 42, "event_type": "renamed", "observed_at": TS,
     "full_name": "MichaelWave369/OldSecret", "before_value": "Secret"},
    {"id": 2, "github_id": 43, "event_type": "first_observed", "observed_at": TS},
    {"id": 3, "github_id": 42, "event_type": "visibility_changed", "observed_at": TS,
     "before_value": "private"},
]


def fixture(rows=None, attempts=None, event_rows=None):
    rows = list([PUBLIC, PRIVATE] if rows is None else rows)
    scan = {"id": 7, "owner": "MichaelWave369", "status": "complete",
            "repo_count": len(rows), "observed_at": TS}
    summary = {"latest_complete": scan, "latest_attempt": attempts or scan}

    def get_json(path):
        if path == "/api/summary":
            return summary
        if path.startswith("/api/repos?limit=500&offset="):
            offset = int(path.rsplit("=", 1)[1])
            return {"items": rows[offset: offset + 500]}
        if path == "/api/events?limit=200&offset=0":
            return {"items": EVENTS if event_rows is None else event_rows}
        raise AssertionError("Unexpected path " + path)
    return get_json


class AdapterTests(unittest.TestCase):
    def test_public_only_and_no_authority(self):
        result = collect_public_observations(fixture(), now=NOW)
        self.assertEqual(result["public_repo_count"], 1)
        self.assertEqual(result["repositories"][0]["full_name"], "MichaelWave369/BTM")
        self.assertEqual(len(result["recent_events"]), 1)
        self.assertNotIn("before_value", result["recent_events"][0])
        self.assertNotIn("HiddenProject", str(result))
        self.assertNotIn("Secret", str(result))
        self.assertFalse(result["merge_authorized"])
        self.assertFalse(result["dispatch_authorized"])
        self.assertFalse(result["verified_complete"])

    def test_failed_latest_scan_is_held(self):
        with self.assertRaisesRegex(RepoNerveUnavailable, "INCOMPLETE"):
            collect_public_observations(
                fixture(attempts={"id": 8, "status": "failed"}), now=NOW)

    def test_duplicate_or_cross_owner_is_rejected(self):
        for rows in ([PUBLIC, PUBLIC], [{**PUBLIC, "full_name": "Other/BTM"}]):
            with self.subTest(rows=rows), self.assertRaises(RepoNerveUnavailable):
                collect_public_observations(fixture(rows=rows), now=NOW)

    def test_stale_scan_is_held(self):
        get = fixture()
        def stale(path):
            payload = get(path)
            if path == "/api/summary":
                scan = {**payload["latest_complete"],
                        "observed_at": (NOW - timedelta(hours=48)).isoformat()}
                return {"latest_complete": scan, "latest_attempt": scan}
            return payload
        with self.assertRaisesRegex(RepoNerveUnavailable, "STALE"):
            collect_public_observations(stale, now=NOW)

    def test_changed_scan_during_pagination_is_held(self):
        get = fixture()
        count = 0
        def moving(path):
            nonlocal count
            payload = get(path)
            if path == "/api/summary":
                count += 1
                if count > 1:
                    return {**payload, "latest_attempt": {"id": 8, "status": "complete"}}
            return payload
        with self.assertRaisesRegex(RepoNerveUnavailable, "SCAN_CHANGED"):
            collect_public_observations(moving, now=NOW)

    def test_inventory_drift_and_event_shape_are_held(self):
        get = fixture()
        def missing(path):
            if path.startswith("/api/repos?"):
                return {"items": [PUBLIC]}
            return get(path)
        with self.assertRaisesRegex(RepoNerveUnavailable, "DRIFT"):
            collect_public_observations(missing, now=NOW)
        with self.assertRaisesRegex(RepoNerveUnavailable, "EVENTS"):
            collect_public_observations(fixture(event_rows="not-a-list"), now=NOW)


if __name__ == "__main__":
    unittest.main()
