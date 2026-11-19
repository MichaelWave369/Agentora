"""Adversarial cloud RepoNerve -> existing Agentora R9 queue probe tests."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fleet_r9_cloud_reponerve_probe as probe
import fleet_r9_mission_control as r9
from app.services.fleet_stewards import StewardHeld

NOW = datetime(2026, 11, 19, 20, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def observation(*, kind="first_observed", event_id=51, archived=False):
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369",
        "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1",
        "source_scan_id": 12,
        "observed_at": NOW.isoformat(),
        "public_repo_count": 1,
        "repositories": [{
            "github_id": probe.REPO_ID, "full_name": probe.REPO,
            "archived": archived, "source_only": True,
            "verified_complete": False,
        }],
        "recent_events": [{
            "id": event_id, "github_id": probe.REPO_ID,
            "full_name": probe.REPO, "event_type": kind,
            "observed_at": NOW.isoformat(),
        }],
        "source_only": True,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "verified_complete": False,
    }


class FakeStore:
    def __init__(self, public=True, many=False):
        self.names = [probe.REPO, "MichaelWave369/Another"]
        self.repos = [{
            "github_id": i, "full_name": name, "private": 0 if public else 1,
            "present": 1, "archived": 0
        } for i, name in [(probe.REPO_ID, self.names[0]),
                          (1234, self.names[1])]]
        agentora = {"id": 1, "github_id": probe.REPO_ID, "full_name": probe.REPO,
                    "event_type": "first_observed", "observed_at": NOW.isoformat()}
        other = lambda i: {"id": i, "github_id": 1234,
                           "full_name": self.names[1],
                           "event_type": "first_observed", "observed_at": NOW.isoformat()}
        self.events_list = (
            [other(i) for i in range(201, 1, -1)] + [agentora]
            if many else [agentora])

    def summary(self):
        scan = {"id": 12, "owner": probe.OWNER,
                "status": "complete", "observed_at": NOW.isoformat(),
                "repo_count": 2}
        return {"latest_complete": scan, "latest_attempt": scan}

    def repositories(self, limit, offset):
        return self.repos[offset:offset + limit]

    def events(self, limit, offset):
        return self.events_list[offset:offset + limit]


class ProbeTests(unittest.TestCase):
    def test_actual_r9_enqueue_and_exact_replay_inside_single_runner(self):
        with tempfile.TemporaryDirectory() as root:
            item = observation()
            result = probe.qualify_observation(item, item["recent_events"][0],
                                               SHA, root, now=NOW)
        self.assertEqual(result["state"], "EPHEMERAL_ADMISSION_REPLAY_QUALIFIED")
        self.assertEqual(result["mission_id"],
                         f"r10-e51-gh{probe.REPO_ID}")
        self.assertTrue(result["dedupe_verified"])
        self.assertEqual(result["r9_rows"], 1)
        self.assertIs(result["persisted_across_runs"], False)
        self.assertIs(result["dispatch_authorized"], False)
        self.assertIs(result["merge_authorized"], False)

    def test_reject_non_allowlisted_repository(self):
        item = observation()
        wrong = dict(item["recent_events"][0], full_name="MichaelWave369/Other")
        with self.assertRaisesRegex(probe.ProbeHeld, "AGENTORA_EVENT_NOT_ALLOWLISTED"):
            probe.held_intake(item, wrong, SHA)

    def test_reject_unapproved_event_type(self):
        item = observation(kind="renamed")
        with self.assertRaisesRegex(probe.ProbeHeld, "AGENTORA_EVENT_NOT_ALLOWLISTED"):
            probe.held_intake(item, item["recent_events"][0], SHA)

    def test_reject_non_hex_source_sha(self):
        item = observation()
        with self.assertRaisesRegex(probe.ProbeHeld, "SOURCE_SHA_INVALID"):
            probe.held_intake(item, item["recent_events"][0], "not-a-sha")

    def test_forged_authority_is_rejected_by_steward(self):
        item = observation()
        item["dispatch_authorized"] = True
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(StewardHeld, "AUTHORITY_FORGERY"):
                probe.qualify_observation(item, item["recent_events"][0],
                                          SHA, root, now=NOW)

    def test_non_public_archived_steward_is_held(self):
        item = observation(archived=True)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(r9.stewardship.HandoffHeld):
                probe.qualify_observation(item, item["recent_events"][0],
                                          SHA, root, now=NOW)

    def test_mismatched_event_not_in_source_held(self):
        item = observation()
        bad = dict(item["recent_events"][0], id=99)
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaisesRegex(r9.MissionHeld, "SOURCE_EVENT_NOT_IN_CURRENT_SCAN"):
                probe.qualify_observation(item, bad, SHA, root, now=NOW)

    def test_only_fixed_reponerve_read_routes(self):
        get = probe.store_get_json(FakeStore())
        self.assertEqual(get("/api/summary")["latest_complete"]["id"], 12)
        self.assertEqual(len(get("/api/repos?limit=500&offset=0")["items"]), 2)
        self.assertEqual(len(get("/api/events?limit=200&offset=0")["items"]), 1)
        for path in ("/api/private", "/api/summary?owner=other",
                     "/api/repos?limit=1&offset=0",
                     "/api/events?limit=200&offset=99999",
                     "https://attacker.example/api/summary"):
            with self.subTest(path=path), self.assertRaises(probe.ProbeHeld):
                get(path)

    def test_event_pagination_reaches_original_agentora_event(self):
        get = probe.store_get_json(FakeStore(many=True))
        obs, event = probe.find_owned_event(get, now=NOW)
        self.assertEqual(obs["source_scan_id"], 12)
        self.assertEqual(event["id"], 1)
        self.assertEqual(event["github_id"], probe.REPO_ID)

    def test_no_event_returns_advisory_only(self):
        fake = FakeStore()
        fake.events_list = []
        obs, event = probe.find_owned_event(probe.store_get_json(fake), now=NOW)
        self.assertIsNone(event)
        self.assertEqual(obs["public_repo_count"], 2)

    def test_source_sha_pinned_to_const_not_dynamic(self):
        self.assertEqual(probe.NERVE_SHA,
                         "a625e8ac34831420ab52f2372bf4ec9079258c4a")
        self.assertEqual(probe.REPO_ID, 1167870912)
        self.assertEqual(probe.REPO, "MichaelWave369/Agentora")

    def test_replay_across_same_sqlite_db_must_hold_second_new_event(self):
        item = observation()
        with tempfile.TemporaryDirectory() as root:
            probe.qualify_observation(item, item["recent_events"][0], SHA,
                                      root, now=NOW)
            changed = observation(event_id=52)
            with self.assertRaisesRegex(r9.MissionHeld,
                                        "REPOSITORY_HAS_UNRESOLVED_MISSION"):
                probe.qualify_observation(changed, changed["recent_events"][0],
                                          SHA, root, now=NOW)


if __name__ == "__main__":
    unittest.main()
