"""R2 persistent stewardship tests: no execution authority, state durability, rotation fairness."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from app.services.fleet_stewards import StewardHeld, StewardRegistry

NOW = datetime(2026, 11, 7, 18, 0, tzinfo=timezone.utc)
TS = (NOW - timedelta(minutes=2)).isoformat()


def row(repo_id, name, archived=False):
    return {"github_id": repo_id, "full_name": "MichaelWave369/" + name,
            "archived": archived, "source_only": True, "verified_complete": False}


def sample(ids=(1, 2, 3), scan_id=1, observed_at=TS):
    rows = [row(i, "Project" + str(i)) for i in ids]
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": scan_id,
        "observed_at": observed_at, "public_repo_count": len(rows),
        "repositories": rows, "recent_events": [],
        "source_only": True, "dispatch_authorized": False,
        "merge_authorized": False, "verified_complete": False,
    }


class StewardsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "stewards.sqlite3"
        self.store = StewardRegistry(self.db)

    def test_first_ingest_assigns_stable_logical_stewards_and_replay_is_noop(self):
        first = self.store.ingest(sample(), now=NOW)
        self.assertEqual(first["stewards_created"], 3)
        same = self.store.ingest(sample(), now=NOW)
        self.assertEqual(same["state"], "IDEMPOTENT")
        registry = StewardRegistry(self.db)
        exported = registry.snapshot()
        self.assertEqual([r["steward_key"] for r in exported["stewards"]],
                         ["steward-gh-1", "steward-gh-2", "steward-gh-3"])
        self.assertFalse(exported["dispatch_authorized"])
        self.assertFalse(exported["merge_authorized"])
        self.assertFalse(exported["verified_complete"])

    def test_rename_preserves_steward_history_and_absence_is_not_deletion(self):
        self.store.ingest(sample(), now=NOW)
        self.store.plan_rotation("turn-one", batch_size=2, now=NOW)
        next_scan = sample(ids=(1, 3), scan_id=2,
                           observed_at=(NOW - timedelta(minutes=1)).isoformat())
        next_scan["repositories"][0]["full_name"] = "MichaelWave369/Renamed"
        self.store.ingest(next_scan, now=NOW)
        visible = self.store.snapshot()["stewards"]
        self.assertEqual([r["github_id"] for r in visible], [1, 3])
        self.assertEqual(visible[0]["steward_key"], "steward-gh-1")
        self.assertEqual(visible[0]["planned_count"], 1)
        self.assertEqual(visible[0]["full_name"], "MichaelWave369/Renamed")
        self.assertNotIn("Project2", str(self.store.snapshot()))
        with self.store._tx() as db:
            absent = db.execute("SELECT present FROM stewards WHERE github_id=2").fetchone()
        self.assertEqual(absent["present"], 0)

    def test_archived_repositories_are_visible_but_not_planned(self):
        source = sample()
        source["repositories"][0]["archived"] = True
        self.store.ingest(source, now=NOW)
        export = self.store.snapshot()
        self.assertEqual(export["stewards"][0]["state"], "PAUSED_ARCHIVED")
        selection = self.store.plan_rotation("turn-1", batch_size=3, now=NOW)
        self.assertEqual([r["github_id"] for r in selection["selected"]], [2, 3])

    def test_rotation_fairness_and_idempotency_across_restarts(self):
        self.store.ingest(sample(), now=NOW)
        a = self.store.plan_rotation("a", batch_size=2, now=NOW)
        b = StewardRegistry(self.db).plan_rotation("b", batch_size=2, now=NOW)
        c = StewardRegistry(self.db).plan_rotation("c", batch_size=2, now=NOW)
        self.assertEqual([[r["github_id"] for r in s["selected"]] for s in (a, b, c)],
                         [[1, 2], [3, 1], [2, 3]])
        replay = self.store.plan_rotation("a", batch_size=2, now=NOW)
        self.assertEqual(replay["state"], "REPLAYED_ADVISORY")
        self.assertEqual(replay["selected"], a["selected"])
        with self.assertRaisesRegex(StewardHeld, "REQUEST_REPLAY_MISMATCH"):
            self.store.plan_rotation("a", batch_size=3, now=NOW)
        self.assertTrue(all(s["dispatch_authorized"] is False for s in (a, b, c, replay)))

    def test_forged_authority_private_fields_and_inconsistent_events_are_rejected(self):
        for field, value in (("dispatch_authorized", True), ("merge_authorized", True),
                             ("verified_complete", True), ("owner", "Attacker")):
            bad = sample()
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(StewardHeld):
                self.store.ingest(bad, now=NOW)
        bad = sample()
        bad["repositories"][0]["private"] = True
        with self.assertRaisesRegex(StewardHeld, "REPO_FIELDS_INVALID"):
            self.store.ingest(bad, now=NOW)
        bad = sample()
        bad["recent_events"] = [{"id": 1, "github_id": 999,
            "full_name": "MichaelWave369/Private", "event_type": "first_observed",
            "observed_at": TS}]
        with self.assertRaisesRegex(StewardHeld, "EVENT_IDENTITY_INVALID"):
            self.store.ingest(bad, now=NOW)

    def test_failed_or_rollback_scan_is_not_ingested(self):
        self.store.ingest(sample(), now=NOW)
        changed = sample()
        changed["repositories"][0]["full_name"] = "MichaelWave369/Collision"
        with self.assertRaisesRegex(StewardHeld, "SCAN_ID_CONTENT_CHANGED"):
            self.store.ingest(changed, now=NOW)
        old = sample(scan_id=0)
        with self.assertRaises(StewardHeld):
            self.store.ingest(old, now=NOW)
        stale = sample(scan_id=2, observed_at=(NOW - timedelta(days=3)).isoformat())
        with self.assertRaisesRegex(StewardHeld, "TIME_STALE"):
            self.store.ingest(stale, now=NOW)
        self.assertEqual(len(self.store.snapshot()["stewards"]), 3)

    def test_no_source_and_invalid_planning_inputs_are_held(self):
        with self.assertRaisesRegex(StewardHeld, "NO_SOURCE_OBSERVATIONS"):
            self.store.plan_rotation("turn", now=NOW)
        self.store.ingest(sample(), now=NOW)
        for req, n in (("a/slash", 1), ("safe", 0), ("safe", 7), ("safe", True)):
            with self.subTest(req=req, n=n), self.assertRaises(StewardHeld):
                self.store.plan_rotation(req, batch_size=n, now=NOW)

    def test_no_schedule_on_zero_public_repos(self):
        self.store.ingest(sample(ids=()), now=NOW)
        picked = self.store.plan_rotation("turn", batch_size=3, now=NOW)
        self.assertEqual(picked["selected"], [])
        self.assertEqual(self.store.snapshot()["stewards"], [])


if __name__ == "__main__":
    unittest.main()
