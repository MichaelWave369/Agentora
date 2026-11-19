"""Adversarial cloud RepoNerve -> existing Agentora R9 queue probe tests."""
from datetime import datetime, timezone
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from urllib import request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import fleet_r9_cloud_reponerve_probe as probe
import fleet_r9_mission_control as r9
import fleet_r04_leases as leases
from fleet_r9_cloud_state import VolumeState, VolumeHeld
from app.services.fleet_stewards import StewardRegistry
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
            if token:
                self.assertNotIn(str(token), str(held.exception))
            self.assertEqual(str(held.exception),
                             "REPONERVE_READ_TOKEN_MISSING_OR_UNSAFE")
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

    def test_mount_gate_never_claims_ephemeral_runner_is_durable(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(probe.ProbeHeld, "MOUNT_NOT_QUALIFIED"):
                probe.require_mounted_volume(Path("/tmp/r9-state"))
        with patch.dict(os.environ, {
                "AGENTORA_R9_VOLUME_MOUNT": "/data",
                "AGENTORA_R9_DURABLE_ENABLED": "true"}):
            with patch.object(probe.os.path, "ismount", return_value=False):
                with self.assertRaisesRegex(probe.ProbeHeld, "MOUNT_NOT_QUALIFIED"):
                    probe.require_mounted_volume(Path("/data/r9-state"))
            with patch.object(probe.os.path, "ismount", return_value=True):
                with self.assertRaisesRegex(probe.ProbeHeld, "OUTSIDE_MOUNT"):
                    probe.require_mounted_volume(Path("/tmp/pretend-data/r9"))
                probe.require_mounted_volume(Path("/data/r9-state"))

    def test_source_sha_pinned_to_const_not_dynamic(self):
        self.assertEqual(probe.NERVE_SHA,
                         "a625e8ac34831420ab52f2372bf4ec9079258c4a")
        self.assertEqual(probe.REPO_ID, 1167870912)
        self.assertEqual(probe.REPO, "MichaelWave369/Agentora")

    @staticmethod
    def _seed_reponerve_schema(root):
        with sqlite3.connect(str(root / "reponerve.sqlite3")) as db:
            db.executescript("""
                CREATE TABLE scans (id INTEGER PRIMARY KEY, owner TEXT);
                CREATE TABLE repos (github_id INTEGER PRIMARY KEY, full_name TEXT);
                CREATE TABLE events (
                  id INTEGER PRIMARY KEY, scan_id INTEGER NOT NULL,
                  github_id INTEGER NOT NULL, full_name TEXT NOT NULL,
                  event_type TEXT NOT NULL);
            """)
            db.execute("INSERT INTO scans VALUES (12,?)", (probe.OWNER,))
            db.execute("INSERT INTO repos VALUES (?,?)",
                       (probe.REPO_ID, probe.REPO))
            db.execute("INSERT INTO events VALUES (51,12,?,?,?)",
                       (probe.REPO_ID, probe.REPO, "first_observed"))

    @classmethod
    def _seed_all_databases(cls, root):
        cls._seed_reponerve_schema(root)
        registry = StewardRegistry(root / "r9-stewards.sqlite3")
        ledger = leases.LeaseLedger(root / "r9-leases.sqlite3")
        r9.MissionControl(registry, ledger)

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_durable_volume_seeds_and_restarts_same_three_databases(self):
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount) as volume:
                self.assertTrue(volume.is_new)
                self._seed_all_databases(volume.working)
                volume.commit()
                self.assertFalse(volume.is_new)
            with VolumeState(mount) as recovered:
                self.assertFalse(recovered.is_new)
                self.assertEqual(
                    sorted(p.name for p in recovered.working.glob("*.sqlite3")),
                    sorted(("reponerve.sqlite3", "r9-stewards.sqlite3",
                            "r9-leases.sqlite3")))
                recovered.commit()
            self.assertFalse((mount / ".r9-inflight-writer.json").exists())

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_durable_volume_interrupted_active_writer_holds_on_restart(self):
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount) as seed:
                self._seed_all_databases(seed.working)
                seed.commit()
            with VolumeState(mount):
                pass  # Simulate a process crash before commit
            with self.assertRaisesRegex(VolumeHeld, "UNFINISHED_WRITER"):
                with VolumeState(mount):
                    pass

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_durable_volume_crashed_first_seed_never_resets(self):
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount):
                pass  # Uncommitted initial seed stays available for forensics
            with self.assertRaisesRegex(VolumeHeld, "ORPHANED_SEED"):
                with VolumeState(mount):
                    pass

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_durable_volume_rejects_two_simultaneous_writers(self):
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount) as first:
                with self.assertRaisesRegex(VolumeHeld, "WRITER_ACTIVE"):
                    with VolumeState(mount):
                        pass
                self._seed_all_databases(first.working)
                first.commit()

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_durable_volume_corruption_holds_instead_of_reinitializing(self):
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount) as seed:
                self._seed_all_databases(seed.working)
                seed.commit()
            (mount / "active" / "reponerve.sqlite3").write_bytes(b"not sqlite")
            with self.assertRaisesRegex(VolumeHeld, "DB_UNREADABLE"):
                with VolumeState(mount):
                    pass

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_durable_volume_rejects_untrusted_root_symlink(self):
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            target = Path(base) / "other-dir"
            target.mkdir()
            mount.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(VolumeHeld, "SYMLINK"):
                VolumeState(mount)

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_durable_known_event_replays_from_original_source_lineage(self):
        item = observation()
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount) as seed:
                self._seed_reponerve_schema(seed.working)
                first = probe.qualify_observation(
                    item, item["recent_events"][0], SHA,
                    seed.working, now=NOW)
                self.assertEqual(first["state"], "EPHEMERAL_ADMISSION_REPLAY_QUALIFIED")
                seed.commit()
            with VolumeState(mount) as recovered:
                newer = observation()
                newer["source_scan_id"] = 13
                result = probe.recorded_durable_event(
                    recovered.working, newer, newer["recent_events"][0])
                self.assertEqual(result["state"], "DURABLE_REPLAY_VERIFIED")
                self.assertEqual(result["mission_id"], first["mission_id"])
                self.assertTrue(result["persisted_across_runs"])
                with sqlite3.connect(
                        str(recovered.working / "r9-leases.sqlite3")) as db:
                    self.assertEqual(db.execute(
                        "SELECT COUNT(*) FROM r9_missions").fetchone()[0], 1)
                recovered.commit()

    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    @unittest.skipUnless(os.name == "posix", "durable volume requires POSIX")
    def test_new_event_holds_behind_original_queued_mission(self):
        item = observation()
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount) as seed:
                self._seed_reponerve_schema(seed.working)
                first = probe.qualify_observation(
                    item, item["recent_events"][0], SHA, seed.working, now=NOW)
                seed.commit()
            with VolumeState(mount) as recovered:
                blocker = probe.unresolved_durable_mission(recovered.working)
                self.assertEqual(blocker["mission_id"], first["mission_id"])
                self.assertEqual(blocker["state"], "QUEUED")
                recovered.commit()

    def test_durable_event_lineage_corruption_holds(self):
        item = observation()
        with tempfile.TemporaryDirectory() as base:
            mount = Path(base) / "private-state"
            with VolumeState(mount) as seed:
                self._seed_reponerve_schema(seed.working)
                probe.qualify_observation(
                    item, item["recent_events"][0], SHA, seed.working, now=NOW)
                seed.commit()
            with VolumeState(mount) as recovered:
                with sqlite3.connect(
                        str(recovered.working / "reponerve.sqlite3")) as db:
                    db.execute("UPDATE events SET scan_id=999 WHERE id=51")
                with self.assertRaisesRegex(probe.ProbeHeld, "EVENT_HISTORY_CONFLICT"):
                    probe.recorded_durable_event(
                        recovered.working, item, item["recent_events"][0])
                # Deliberately not committing the corrupted record.
            with self.assertRaisesRegex(VolumeHeld, "UNFINISHED_WRITER"):
                with VolumeState(mount):
                    pass

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
