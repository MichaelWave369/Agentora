"""Adversarial cloud RepoNerve -> existing Agentora R9 queue probe tests."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib import request

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

    def test_authenticated_public_get_to_owner_only(self):
        calls = []
        sentinel = object()

        def transport(req, *, timeout):
            calls.append((req.full_url, req.get_method(),
                          req.get_header("Authorization"), timeout,
                          list(req.unredirected_hdrs)))
            return sentinel

        opener = probe.authenticated_public_opener(
            "token-read-only-123", transport=transport)
        url = ("https://api.github.com/users/MichaelWave369/repos?"
               "per_page=100&page=1&type=owner&sort=full_name&direction=asc")
        req = request.Request(url, method="GET")
        self.assertIs(opener(req, timeout=10), sentinel)
        self.assertEqual(calls[0][0], url)
        self.assertEqual(calls[0][1], "GET")
        self.assertEqual(calls[0][2], "Bearer token-read-only-123")
        self.assertEqual(calls[0][3], 10)
        self.assertIn("Authorization", calls[0][4])

    def test_authenticated_public_client_rejects_privilege_escalation(self):
        calls = []
        opener = probe.authenticated_public_opener(
            "token-read-only-123",
            transport=lambda *args, **kwargs: calls.append((args, kwargs)))
        good_query = "per_page=100&page=2&type=owner&sort=full_name&direction=asc"
        rejected = (
            "https://api.github.com/user/repos?" + good_query,
            "https://api.github.com/users/Another/repos?" + good_query,
            "https://evil.example/users/MichaelWave369/repos?" + good_query,
            "http://api.github.com/users/MichaelWave369/repos?" + good_query,
            "https://api.github.com:443/users/MichaelWave369/repos?" + good_query,
            "https://api.github.com/users/MichaelWave369/repos?per_page=100&page=2",
            "https://api.github.com/users/MichaelWave369/repos?" +
                good_query + "&visibility=all",
            "https://api.github.com/users/MichaelWave369/repos?" +
                good_query.replace("page=2", "page=1000"),
            "https://api.github.com/users/MichaelWave369/repos?" +
                good_query.replace("page=2", "page=2&page=3"),
            "https://api.github.com/users/MichaelWave369/repos?" +
                good_query.replace("type=owner", "type=all"),
        )
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(probe.ProbeHeld):
                opener(request.Request(url, method="GET"), timeout=10)
        with self.assertRaisesRegex(probe.ProbeHeld, "METHOD_REJECTED"):
            opener(request.Request(
                "https://api.github.com/users/MichaelWave369/repos?" +
                good_query, data=b"danger", method="POST"), timeout=10)
        self.assertEqual(calls, [])

    def test_no_token_no_public_fetch_and_secret_not_logged(self):
        for token in (None, "", "short", "12345678\nOHNO", "abcd1234 xyz"):
            with self.subTest(token=token), self.assertRaises(
                probe.ProbeHeld) as held:
                probe.authenticated_public_opener(token)
            self.assertNotIn(str(token), str(held.exception))
        for source, reason in (
            ("GitHub returned HTTP 403", "REPONERVE_PUBLIC_HTTP_403"),
            ("GitHub returned HTTP 429", "REPONERVE_PUBLIC_HTTP_429"),
            ("GitHub inventory request failed: URLError",
             "REPONERVE_PUBLIC_TRANSPORT_UNAVAILABLE"),
            ("GitHub returned HTTP 403 secret-token-value",
             "REPONERVE_PUBLIC_INVENTORY_UNAVAILABLE"),
        ):
            self.assertEqual(probe.inventory_error_reason(ValueError(source)), reason)
            self.assertNotIn("secret-token-value",
                             probe.inventory_error_reason(ValueError(source)))

    def test_source_sha_pinned_to_const_not_dynamic(self):
        self.assertEqual(probe.NERVE_SHA,
                         "a625e8ac34831420ab52f2372bf4ec9079258c4a")
        self.assertEqual(probe.REPO_ID, 1167870912)
        self.assertEqual(probe.REPO, "MichaelWave369/Agentora")

    def test_replay_across_same_sqlite_db_must_hold_second_new_event(self):
        item = observation()
        next_event = dict(item["recent_events"][0], id=52)
        item["recent_events"].append(next_event)
        with tempfile.TemporaryDirectory() as root:
            probe.qualify_observation(item, item["recent_events"][0], SHA,
                                      root, now=NOW)
            with self.assertRaisesRegex(r9.MissionHeld,
                                        "REPOSITORY_HAS_UNRESOLVED_MISSION"):
                probe.qualify_observation(item, next_event, SHA,
                                          root, now=NOW)


if __name__ == "__main__":
    unittest.main()
