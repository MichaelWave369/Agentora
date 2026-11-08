"""R4 contract: live SHA, local lease, and fixed GitHub sandbox artifact correlation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import fleet_r4_steward_evidence as r4
import fleet_r04_leases as leases
import fleet_r3_steward_claim as claims
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 7, 19, 0, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
TS = (NOW - timedelta(minutes=2)).isoformat()
SHA = "a" * 40
RUN = 1234


def observations():
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": 7,
        "observed_at": TS, "public_repo_count": 1,
        "repositories": [{
            "github_id": r4.pilot.REPOSITORY_ID,
            "full_name": r4.pilot.REPOSITORY,
            "archived": False, "source_only": True, "verified_complete": False,
        }],
        "recent_events": [], "source_only": True,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def intake():
    return {
        "schema": leases.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER, "repository": r4.pilot.REPOSITORY,
        "repository_id": r4.pilot.REPOSITORY_ID,
        "default_branch": "main", "source_sha": SHA,
        "request_sha256": "b"*64,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id":"automated_tests", "verification_state":"NOT_RUN",
                    "evidence_receipt": None}],
    }


def evidence_receipt():
    return {
        "schema": r4.evidence.SCHEMA,
        "state": "GITHUB_PILOT_ARTIFACT_DIGEST_CORRELATED",
        "reviewed_utc": NOW.isoformat(),
        "source": "GITHUB_ACTIONS_REST_AND_SHA256_ARCHIVE",
        "github_workflow_run": {
            "repository": r4.evidence.AGENTORA, "run_id": RUN,
            "run_attempt": 1, "event": "workflow_dispatch",
            "workflow_path": r4.evidence.WORKFLOW_PATH,
        },
        "artifact": {"id": 345, "sha256": "c"*64,
                     "github_digest_matched": True},
        "pilot_repository": r4.pilot.REPOSITORY,
        "pilot_repository_id": r4.pilot.REPOSITORY_ID,
        "pilot_source_sha": SHA,
        "preflight_observed_utc": (NOW + timedelta(seconds=30)).isoformat(),
        "postflight_observed_utc": (NOW + timedelta(seconds=90)).isoformat(),
        "observed_fixed_checks": {
            "dependency_install": "EXIT_0_REPORTED_BY_PILOT",
            "node_tests": "EXIT_0_REPORTED_BY_PILOT",
            "vite_build": "EXIT_0_REPORTED_BY_PILOT",
        },
        "scope": "ONE_MANUALLY_TRIGGERED_PHI_MADA_SHA_ONLY",
        "artifact_integrity_correlated": True,
        "workflow_success_observed": True,
        "signed_attestation": False,
        "independent_reproduction_performed": False,
        "current_pilot_head_rechecked": False,
        "runtime_browser_verified": False,
        "product_verified": False,
        "verified_complete": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "operator_review_required": True,
    }


class CorrelationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.registry = StewardRegistry(root / "stewards.db")
        self.ledger = leases.LeaseLedger(root / "leases.db")
        self.registry.ingest(observations(), now=NOW)
        self.intake = intake()
        claims.claim(self.registry, self.ledger, self.intake, "worker1",
                     root / "private" / "lease.json", ttl=1800, now=NOW, now_ms=MS)
        self.cap = leases.load_capability(root / "private" / "lease.json")

    def correlate(self, payload=None, **overrides):
        payload = evidence_receipt() if payload is None else payload
        observed = {"state": "SOURCE_HEAD_MATCH_OBSERVED",
                    "source_head_observed_match": True}
        with patch.object(r4.evidence, "review", return_value=payload) as reviewer, \
             patch.object(r4.source, "observe", return_value=observed) as head:
            result = r4.correlate(
                self.registry, self.ledger, overrides.pop("intake", self.intake),
                overrides.pop("capability", self.cap),
                overrides.pop("run_id", RUN), b"mock-archive",
                confirmation=overrides.pop("confirmation", r4.CONFIRM),
                now=overrides.pop("now", NOW+timedelta(minutes=2)),
                clock_ms=overrides.pop("clock_ms", MS+120000), **overrides)
        return result, reviewer, head

    def test_valid_fixed_pilot_correlates_real_local_reservation_without_authority(self):
        result, reviewer, head = self.correlate()
        self.assertEqual(result["state"], "SANDBOXED_CHECKS_CORRELATED_WITH_LOCAL_LEASE")
        self.assertEqual(result["lease_generation"], self.cap["generation"])
        self.assertEqual(result["workflow_run_id"], RUN)
        self.assertEqual(result["github_artifact_sha256"], "c"*64)
        self.assertEqual(head.call_count, 2)
        self.assertEqual(reviewer.call_count, 1)
        for flag in ("product_verified", "verified_complete",
                     "dispatch_authorized", "merge_authorized",
                     "signed_attestation", "lease_attested_by_github_runner"):
            self.assertIs(result[flag], False)
        self.assertNotIn(self.cap["token"], json.dumps(result))
        self.assertNotIn(self.cap["request_sha256"], json.dumps(result))

    def test_verified_r07_trace_survives_r4_correlation_without_authority(self):
        confirmed = evidence_receipt()
        request = "r10r5-" + "a" * 40
        confirmed["dispatch_request_id"] = request
        confirmed["dispatch_trace_present"] = True
        confirmed["dispatch_origin_authenticated"] = False
        correlated, _, _ = self.correlate(payload=confirmed)
        self.assertEqual(correlated["dispatch_request_id"], request)
        self.assertTrue(correlated["dispatch_trace_present"])
        self.assertFalse(correlated["dispatch_origin_authenticated"])
        self.assertFalse(correlated["merge_authorized"])

        for change in ({"dispatch_origin_authenticated": True},
                       {"dispatch_trace_present": False},
                       {"dispatch_request_id": "bad/id"}):
            with self.subTest(change=change), self.assertRaises(r4.CorrelationHeld):
                self.correlate(payload={**confirmed, **change})

    def test_only_one_repo_and_confirmed_operator_review(self):
        bad = intake()
        bad["repository"] = "MichaelWave369/BTM"
        with self.assertRaisesRegex(r4.CorrelationHeld, "ONLY_FIXED"):
            self.correlate(intake=bad)
        with self.assertRaisesRegex(r4.CorrelationHeld, "EXPLICIT"):
            self.correlate(confirmation="yes")
        with self.assertRaisesRegex(r4.CorrelationHeld, "RUN_ID"):
            self.correlate(run_id=True)

    def test_reported_workflow_data_forgery_is_rejected(self):
        originals = evidence_receipt()
        mutations = [
            ("pilot_source_sha", "f"*40),
            ("state", "FAILED"),
            ("source", "RAW_LOCAL_JSON"),
            ("merge_authorized", True),
            ("signed_attestation", True),
            ("product_verified", True),
            ("artifact_integrity_correlated", False),
            ("scope", "ANY_REPO"),
        ]
        for field, value in mutations:
            with self.subTest(field=field):
                changed = {**originals, field:value}
                with self.assertRaises(r4.CorrelationHeld):
                    self.correlate(payload=changed)
        altered = evidence_receipt()
        altered["github_workflow_run"]["run_attempt"] = 2
        with self.assertRaisesRegex(r4.CorrelationHeld, "RUN_IDENTITY"):
            self.correlate(payload=altered)

    def test_lease_window_must_cover_real_pilot_execution_times(self):
        prior = evidence_receipt()
        prior["preflight_observed_utc"] = (NOW-timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(r4.CorrelationHeld, "OUTSIDE_LOCAL_LEASE"):
            self.correlate(payload=prior)
        after = evidence_receipt()
        after["postflight_observed_utc"] = (NOW+timedelta(hours=1)).isoformat()
        with self.assertRaisesRegex(r4.CorrelationHeld, "OUTSIDE_LOCAL_LEASE"):
            self.correlate(payload=after)

    def test_expired_lease_rejected(self):
        with self.assertRaisesRegex(r4.CorrelationHeld, "LEASE_NOT_CURRENT"):
            self.correlate(now=NOW+timedelta(hours=2), clock_ms=MS+7200000)

    def test_wrong_source_sha_or_fenced_capability_rejected(self):
        shifted = intake()
        shifted["source_sha"] = "f"*40
        with self.assertRaisesRegex(r4.CorrelationHeld, "LEASE_SOURCE_MISMATCH"):
            self.correlate(intake=shifted)
        false_cap = {**self.cap,"token":"wrong"}
        with self.assertRaisesRegex(r4.CorrelationHeld, "LEASE_NOT_CURRENT"):
            self.correlate(capability=false_cap)

    def test_steward_rename_or_archive_holds(self):
        altered = observations()
        altered["source_scan_id"] = 8
        altered["repositories"][0]["full_name"] = "MichaelWave369/Renamed"
        self.registry.ingest(altered, now=NOW)
        with self.assertRaisesRegex(claims.HandoffHeld, "STEWARD_IDENTITY_CHANGED"):
            self.correlate()

    def test_source_head_drift_is_not_success(self):
        result = evidence_receipt()
        with patch.object(r4.evidence, "review", return_value=result), \
             patch.object(r4.source, "observe", return_value={
                 "state":"HELD_SOURCE_REVISION_MOVED",
                 "source_head_observed_match":False,
             }):
            with self.assertRaisesRegex(r4.CorrelationHeld, "CURRENT_HEAD_NOT_VERIFIED"):
                r4.correlate(self.registry,self.ledger,self.intake,self.cap,RUN,b"archive",
                             confirmation=r4.CONFIRM, now=NOW, clock_ms=MS)


if __name__ == "__main__":
    unittest.main()
