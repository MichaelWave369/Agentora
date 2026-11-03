"""Fleet R0.4 same-host SQLite reservation, zero execution authority."""
import contextlib
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r04_leases as mod

NOW = 1_793_700_000_000
SHA = "a" * 40
OTHER = "b" * 40


def intake(name="BTM", repo_id=5, sha=SHA):
    return {
        "schema": mod.INTAKE_SCHEMA,
        "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": mod.OWNER,
        "repository": mod.OWNER + "/" + name,
        "repository_id": repo_id,
        "source_sha": sha,
        "request_sha256": "c" * 64,
        "verified_complete": False,
        "operator_approved": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False,
        "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests", "verification_state": "NOT_RUN",
                    "evidence_receipt": None}],
    }


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / "fleet.db"
        self.ledger = mod.LeaseLedger(self.path)

    def test_lease_is_fenced_and_has_no_execution_or_merge_authority(self):
        a = self.ledger.reserve(intake(), "desk-1", now_ms=NOW)
        self.assertEqual(a["generation"], 1)
        self.assertFalse(a["execution_authorized"])
        self.assertFalse(a["merge_authorized"])
        self.assertFalse(a["verified_complete"])
        snapshot = self.ledger.status(NOW)
        self.assertEqual(snapshot["active_reservations"], 1)
        self.assertEqual(snapshot["actual_jobs_dispatched"], 0)
        self.assertNotIn(a["token"], json.dumps(snapshot))
        self.assertNotIn(a["token"], json.dumps(self.ledger.events()))
        with self.assertRaisesRegex(mod.LeaseHeld, "REPO_ALREADY_RESERVED"):
            self.ledger.reserve(intake(), "desk-2", now_ms=NOW + 1)

    def test_many_threads_share_one_reservation_for_same_repo(self):
        gate = threading.Barrier(8)

        def attempt(n):
            ledger = mod.LeaseLedger(self.path)
            gate.wait()
            try:
                return ledger.reserve(intake(), "worker-" + str(n), now_ms=NOW)
            except mod.LeaseHeld as exc:
                return str(exc)

        with ThreadPoolExecutor(max_workers=8) as pool:
            outcomes = list(pool.map(attempt, range(8)))
        winners = [x for x in outcomes if isinstance(x, dict)]
        self.assertEqual(len(winners), 1)
        self.assertEqual(outcomes.count("REPO_ALREADY_RESERVED"), 7)
        self.assertEqual(self.ledger.status(NOW)["active_reservations"], 1)

    def test_different_repos_can_be_reserved_in_parallel(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.ledger.reserve, intake("BTM", 5), "desk-a", 300, NOW),
                       pool.submit(self.ledger.reserve, intake("PhiOS", 8), "desk-b", 300, NOW)]
            a, b = [f.result() for f in futures]
        self.assertEqual(a["generation"], 1)
        self.assertEqual(b["generation"], 1)
        self.assertEqual(self.ledger.status(NOW)["active_reservations"], 2)

    def test_heartbeat_and_release_invalidate_old_capability(self):
        a = self.ledger.reserve(intake(), "desk-1", ttl_seconds=30, now_ms=NOW)
        b = self.ledger.renew(a, ttl_seconds=90, now_ms=NOW + 29_000)
        self.assertEqual(b["expires_ms"], NOW + 119_000)
        self.assertEqual(self.ledger.status(NOW + 60_000)["active_reservations"], 1)
        rel = self.ledger.release(a, now_ms=NOW + 60_000)
        self.assertEqual(rel["state"], "RELEASED_NOT_COMPLETED")
        with self.assertRaisesRegex(mod.LeaseHeld, "LEASE_EXPIRED_OR_FENCED"):
            self.ledger.renew(a, now_ms=NOW + 61_000)
        new = self.ledger.reserve(intake(), "desk-2", now_ms=NOW + 61_000)
        self.assertEqual(new["generation"], 2)
        self.assertNotEqual(new["token"], a["token"])

    def test_expiry_takeover_fences_previous_token_and_revision(self):
        first = self.ledger.reserve(intake(), "desk-1", ttl_seconds=30, now_ms=NOW)
        self.assertEqual(self.ledger.status(NOW + 30_000)["reservations"][0]["state"], "EXPIRED")
        second = self.ledger.reserve(intake(sha=OTHER), "desk-2", now_ms=NOW + 30_000)
        self.assertEqual(second["generation"], 2)
        self.assertEqual(second["source_sha"], OTHER)
        for action in (self.ledger.renew, self.ledger.release):
            with self.assertRaisesRegex(mod.LeaseHeld, "LEASE_EXPIRED_OR_FENCED"):
                action(first, now_ms=NOW + 30_001)
        self.assertEqual(self.ledger.status(NOW + 30_001)["reservations"][0]["worker"], "desk-2")

    def test_forged_token_or_worker_or_sha_rejected(self):
        a = self.ledger.reserve(intake(), "desk-1", now_ms=NOW)
        for altered in ({**a, "token": "wrong"}, {**a, "worker": "desk-2"},
                        {**a, "source_sha": OTHER}, {**a, "generation": 0},
                        {**a, "repository_id": 99}):
            with self.assertRaises(mod.LeaseHeld):
                self.ledger.renew(altered, now_ms=NOW + 2)
        self.assertEqual(self.ledger.status(NOW + 3)["active_reservations"], 1)

    def test_intake_rejects_authority_claims_and_bad_identity(self):
        good = intake()
        self.assertEqual(mod.validate_intake(good)["source_sha"], SHA)
        for altered in ({**good, "dispatch_authorized": True},
                        {**good, "operator_approved": 0},
                        {**good, "verified_complete": True},
                        {**good, "head_revalidated_by_agentora": True},
                        {**good, "owner": "SomeoneElse"},
                        {**good, "repository": "SomeoneElse/BTM"},
                        {**good, "repository_id": True},
                        {**good, "source_sha": "HEAD"},
                        {**good, "request_sha256": "short"},
                        {**good, "independent_checks_run": 1},
                        {**good, "checks": [{"verification_state": "PASSED", "evidence_receipt": None}]}):
            with self.subTest(altered=altered):
                with self.assertRaises(mod.LeaseHeld):
                    mod.validate_intake(altered)

    def test_reject_unsafe_ttl_and_clock(self):
        for ttl in (0, 29, 1801, True, "300"):
            with self.assertRaisesRegex(mod.LeaseHeld, "INVALID_TTL"):
                self.ledger.reserve(intake(), "desk-1", ttl_seconds=ttl, now_ms=NOW)
        for now in (-1, True, "now"):
            with self.assertRaisesRegex(mod.LeaseHeld, "INVALID_CLOCK"):
                self.ledger.reserve(intake(), "desk-1", now_ms=now)
        self.assertEqual(self.ledger.status(NOW)["active_reservations"], 0)

    def test_audit_events_do_not_assert_completion(self):
        a = self.ledger.reserve(intake(), "desk-1", now_ms=NOW)
        self.ledger.renew(a, now_ms=NOW + 100)
        self.ledger.release(a, now_ms=NOW + 200)
        events = self.ledger.events()
        self.assertEqual([x["event_type"] for x in events],
                         ["RESERVED", "RENEWED", "RELEASED_NOT_COMPLETED"])
        self.assertEqual(self.ledger.status(NOW + 300)["active_reservations"], 0)
        self.assertNotIn("token", json.dumps(events))
        self.assertNotIn("COMPLETE", self.ledger.status(NOW + 300)["reservations"][0]["state"])

    def test_local_cli_roundtrip_does_not_dispatch_or_merge(self):
        intake_path = Path(self.dir.name) / "verification-intake.json"
        intake_path.write_text(json.dumps(intake()), encoding="utf-8")
        capability = Path(self.dir.name) / "private" / "desk-1.json"
        common = ["--db", str(self.path)]

        def cmd(args):
            capture = io.StringIO()
            with contextlib.redirect_stdout(capture):
                code = mod.main(common + args)
            return code, json.loads(capture.getvalue()) if code == 0 else None

        code, reserved = cmd(["reserve", "--intake", str(intake_path),
                               "--worker", "desk-1", "--lease-file", str(capability)])
        self.assertEqual(code, 0)
        self.assertFalse(reserved["execution_authorized"])
        self.assertNotIn("token", reserved)
        self.assertTrue(capability.is_file())
        if os.name == "posix":
            self.assertEqual(stat.S_IMODE(capability.stat().st_mode), 0o600)
        code, status = cmd(["status"])
        self.assertEqual(code, 0)
        self.assertEqual(status["active_reservations"], 1)
        code, result = cmd(["renew", "--lease-file", str(capability)])
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "RENEWED")
        code, result = cmd(["release", "--lease-file", str(capability)])
        self.assertEqual(code, 0)
        self.assertEqual(result["state"], "RELEASED_NOT_COMPLETED")
        self.assertFalse(capability.exists())
        self.assertEqual(self.ledger.status()["active_reservations"], 0)

    def test_file_validation_and_token_permissions_fail_closed(self):
        request = Path(self.dir.name) / "intake.json"
        request.write_text("not JSON", encoding="utf-8")
        with self.assertRaisesRegex(mod.LeaseHeld, "INTAKE_JSON_INVALID"):
            mod.load_intake(request)
        request.write_text(json.dumps(intake()), encoding="utf-8")
        self.assertEqual(mod.load_intake(request)["repository"], mod.OWNER + "/BTM")
        capability = Path(self.dir.name) / "lease.json"
        mod.save_capability(capability, self.ledger.reserve(intake(), "desk-1"), exclusive=True)
        self.assertEqual(mod.load_capability(capability)["generation"], 1)
        if os.name == "posix":
            os.chmod(capability, 0o644)
            with self.assertRaisesRegex(mod.LeaseHeld, "LEASE_FILE_PERMISSIONS_UNSAFE"):
                mod.load_capability(capability)


if __name__ == "__main__":
    unittest.main()
