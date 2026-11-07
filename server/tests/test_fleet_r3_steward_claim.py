"""R3 integration tests: steward identity + local fenced reservation, zero execution."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
from unittest.mock import patch
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r3_steward_claim as r3
import fleet_r04_leases as r4
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 7, 19, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
OBSERVED = (NOW - timedelta(minutes=2)).isoformat()


def observed(rows=None, scan=1):
    rows = [(42, "BTM", False), (43, "PhiOS", False)] if rows is None else rows
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": scan,
        "observed_at": OBSERVED, "public_repo_count": len(rows),
        "repositories": [
            {"github_id": rid, "full_name": "MichaelWave369/" + name,
             "archived": arch, "source_only": True, "verified_complete": False}
            for rid, name, arch in rows
        ],
        "recent_events": [], "source_only": True,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def intake(name="BTM", rid=42):
    return {
        "schema": r4.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": r4.OWNER, "repository": "MichaelWave369/" + name,
        "repository_id": rid, "source_sha": "a" * 40,
        "request_sha256": "b" * 64, "verified_complete": False,
        "operator_approved": False, "dispatch_authorized": False,
        "merge_authorized": False, "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN", "evidence_receipt": None}],
    }


class StewardLeaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.registry = StewardRegistry(root / "stewards.sqlite3")
        self.ledger = r4.LeaseLedger(root / "leases.sqlite3")
        self.registry.ingest(observed(), now=NOW)
        self.lease_file = root / "private" / "worker1.lease"

    def test_claim_reuses_real_lease_and_no_authority(self):
        claim = r3.claim(self.registry, self.ledger, intake(), "worker1",
                         self.lease_file, now=NOW, now_ms=MS)
        self.assertEqual(claim["state"], "LOCAL_RESERVED_FOR_REVIEW")
        self.assertEqual(claim["steward_key"], "steward-gh-42")
        self.assertEqual(claim["generation"], 1)
        self.assertFalse(claim["dispatch_authorized"])
        self.assertFalse(claim["execution_authorized"])
        self.assertNotIn("token", json.dumps(claim))
        self.assertIn("token", self.lease_file.read_text(encoding="utf-8"))
        status = r3.public_status(self.registry, self.ledger, now=NOW, now_ms=MS)
        self.assertEqual(status["active_reservations"], 1)
        self.assertFalse(status["merge_authorized"])
        self.assertNotIn("token", json.dumps(status))
        self.assertNotIn("request_sha256", json.dumps(status))
        self.assertEqual(status["actual_jobs_dispatched"], 0)

    def test_second_worker_cannot_claim_same_repo(self):
        r3.claim(self.registry, self.ledger, intake(), "worker1",
                 self.lease_file, now=NOW, now_ms=MS)
        with self.assertRaisesRegex(r4.LeaseHeld, "REPO_ALREADY_RESERVED"):
            r3.claim(self.registry, self.ledger, intake(), "worker2",
                     self.lease_file.parent / "worker2.lease",
                     now=NOW, now_ms=MS + 1)
        self.assertEqual(self.ledger.status(now_ms=MS)["active_reservations"], 1)

    def test_identity_archival_and_visibility_fence_claim(self):
        for bad in (intake(name="Nope"), intake(rid=43)):
            with self.assertRaises(r3.HandoffHeld):
                r3.claim(self.registry, self.ledger, bad, "worker1",
                         self.lease_file, now=NOW, now_ms=MS)
        self.registry.ingest(observed([(42, "BTM", True)], scan=2), now=NOW)
        with self.assertRaisesRegex(r3.HandoffHeld, "STEWARD_ARCHIVED"):
            r3.claim(self.registry, self.ledger, intake(), "worker1",
                     self.lease_file, now=NOW, now_ms=MS)
        self.registry.ingest(observed([], scan=3), now=NOW)
        with self.assertRaisesRegex(r3.HandoffHeld, "STEWARD_NOT_VISIBLE"):
            r3.claim(self.registry, self.ledger, intake(), "worker1",
                     self.lease_file, now=NOW, now_ms=MS)

    def test_lease_expiry_fences_stale_owner(self):
        previous = r3.claim(self.registry, self.ledger, intake(), "worker1",
                            self.lease_file, ttl=30, now=NOW, now_ms=MS)
        old_cap = r4.load_capability(self.lease_file)
        new = r3.claim(self.registry, self.ledger, intake(), "worker2",
                       self.lease_file.parent / "worker2.lease",
                       ttl=30, now=NOW, now_ms=MS + 30000)
        self.assertEqual(new["generation"], previous["generation"] + 1)
        with self.assertRaisesRegex(r4.LeaseHeld, "LEASE_EXPIRED_OR_FENCED"):
            self.ledger.release(old_cap, now_ms=MS + 30001)

    def test_capability_write_failure_releases_reservation(self):
        with patch.object(r3.leases, "save_capability",
                          side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                r3.claim(self.registry, self.ledger, intake(), "worker1",
                         self.lease_file, now=NOW, now_ms=MS)
        self.assertEqual(self.ledger.status(now_ms=MS)["active_reservations"], 0)

    def test_existing_capability_file_held_without_touching_existing_data(self):
        self.lease_file.parent.mkdir()
        self.lease_file.write_text("keep this", encoding="utf-8")
        with self.assertRaisesRegex(r3.HandoffHeld, "LEASE_FILE_EXISTS"):
            r3.claim(self.registry, self.ledger, intake(), "worker1",
                     self.lease_file, now=NOW, now_ms=MS)
        self.assertEqual(self.lease_file.read_text(), "keep this")
        self.assertEqual(self.ledger.status(now_ms=MS)["active_reservations"], 0)

    def test_status_does_not_reveal_absent_or_archived_repos(self):
        r3.claim(self.registry, self.ledger, intake(), "worker1",
                 self.lease_file, now=NOW, now_ms=MS)
        self.registry.ingest(observed([(43, "PhiOS", True)], scan=2), now=NOW)
        data = r3.public_status(self.registry, self.ledger, now=NOW, now_ms=MS)
        self.assertEqual(data["reservations"], [])
        self.assertNotIn("BTM", json.dumps(data))

    def test_stale_source_or_invalid_worker_is_held(self):
        with self.assertRaisesRegex(r3.HandoffHeld, "WORKER_INVALID"):
            r3.claim(self.registry, self.ledger, intake(), "worker/bad",
                     self.lease_file, now=NOW, now_ms=MS)
        with self.assertRaisesRegex(r3.HandoffHeld, "SOURCE_STALE"):
            r3.claim(self.registry, self.ledger, intake(), "worker1",
                     self.lease_file, now=NOW + timedelta(days=3), now_ms=MS)


if __name__ == "__main__":
    unittest.main()
