"""Fleet R0.3 local-only verification intake, trust boundary and lineage tests."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "fleet_r03_acceptance_intake.py"
SPEC = importlib.util.spec_from_file_location("fleet_r03_acceptance_intake", SCRIPT)
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)

NOW = datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def request(types=("webxr",), checks=None):
    checked = intake.required_checks(list(types)) if checks is None else list(checks)
    return {
        "schema": intake.REQUEST_SCHEMA,
        "owner": "MichaelWave369",
        "repository": "MichaelWave369/BTM",
        "repository_id": 42,
        "default_branch": "main",
        "source_sha": SHA,
        "source_observed_utc": (NOW - timedelta(minutes=3)).isoformat(),
        "prepared_utc": (NOW - timedelta(minutes=1)).isoformat(),
        "surface_types": list(types),
        "required_checks": [{"id": x, "locally_reviewed": i == 0}
                            for i, x in enumerate(checked)],
        "operator_notes_included": False,
        "operator_review_required": True,
        "independent_verification": "NOT_RUN",
        "execution_state": "NOT_DISPATCHED",
        "approved_for_execution": False,
        "merge_authorized": False,
        "job_dispatch_authorized": False
    }


def as_bytes(value):
    return (json.dumps(value, separators=(",", ":")) + "\n").encode("utf-8")


class IntakeTests(unittest.TestCase):
    def test_valid_webxr_request_produces_hold_receipt_not_verified(self):
        raw = as_bytes(request())
        receipt = intake.accept(raw, now=NOW)
        self.assertEqual(receipt["schema"], intake.INTAKE_SCHEMA)
        self.assertEqual(receipt["state"], "HELD_FOR_OPERATOR_REVIEW")
        self.assertEqual(receipt["request_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(len(receipt["checks"]), 5)
        self.assertEqual(receipt["independent_checks_run"], 0)
        self.assertFalse(receipt["head_revalidated_by_agentora"])
        self.assertFalse(receipt["verified_complete"])
        self.assertFalse(receipt["dispatch_authorized"])
        self.assertFalse(receipt["merge_authorized"])
        self.assertFalse(receipt["digest_is_authentication"])
        self.assertEqual(receipt["checks"][0]["verification_state"], "NOT_RUN")

    def test_multi_surface_contract_produces_deduplicated_check_list(self):
        types = ["web_app", "webxr"]
        expected = intake.required_checks(types)
        self.assertEqual(expected.count("production_build"), 1)
        receipt = intake.accept(as_bytes(request(types)), now=NOW)
        self.assertEqual([x["check_id"] for x in receipt["checks"]], expected)
        self.assertIn("HUMAN_OR_DEVICE_REQUIRED",
                      [x["lane"] for x in receipt["checks"]])
        self.assertIn("AUTOMATION_CANDIDATE_ONLY",
                      [x["lane"] for x in receipt["checks"]])

    def test_reject_private_notes_and_extra_fields_in_payload(self):
        original = request()
        original["operator_notes"] = "private work notes"
        with self.assertRaisesRegex(intake.IntakeHeld, "REQUEST_FIELDS_INVALID"):
            intake.accept(as_bytes(original), now=NOW)
        original = request()
        original["operator_notes_included"] = True
        with self.assertRaisesRegex(intake.IntakeHeld, "AUTHORITY"):
            intake.accept(as_bytes(original), now=NOW)

    def test_reject_foreign_repo_and_unbounded_id(self):
        original = request()
        original["repository"] = "AnotherUser/Private"
        with self.assertRaisesRegex(intake.IntakeHeld, "REPOSITORY_NOT_ALLOWED"):
            intake.accept(as_bytes(original), now=NOW)
        original = request()
        original["repository_id"] = True
        with self.assertRaisesRegex(intake.IntakeHeld, "REPOSITORY_ID_INVALID"):
            intake.accept(as_bytes(original), now=NOW)

    def test_source_sha_mandatory_and_timestamp_fresh_at_export(self):
        original = request()
        original["source_sha"] = "main"
        with self.assertRaisesRegex(intake.IntakeHeld, "IMMUTABLE_SOURCE_REQUIRED"):
            intake.accept(as_bytes(original), now=NOW)
        original = request()
        original["source_observed_utc"] = (NOW - timedelta(minutes=33)).isoformat()
        with self.assertRaisesRegex(intake.IntakeHeld, "REQUEST_STALE_OR_HEAD_NOT_FRESH"):
            intake.accept(as_bytes(original), now=NOW)
        original = request()
        original["prepared_utc"] = (NOW - timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(intake.IntakeHeld, "REQUEST_STALE_OR_HEAD_NOT_FRESH"):
            intake.accept(as_bytes(original), now=NOW)

    def test_execution_and_forged_results_fail_closed(self):
        for field, value in (
            ("approved_for_execution", True),
            ("merge_authorized", True),
            ("job_dispatch_authorized", True),
            ("execution_state", "DISPATCHED"),
            ("independent_verification", "PASSED"),
            ("operator_review_required", False),
            ("approved_for_execution", 0)
        ):
            original = request()
            original[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(intake.IntakeHeld):
                    intake.accept(as_bytes(original), now=NOW)

    def test_check_ids_cannot_be_omitted_forged_or_marked_passed(self):
        original = request()
        original["required_checks"] = original["required_checks"][:-1]
        with self.assertRaisesRegex(intake.IntakeHeld, "CHECKLIST_MISMATCH"):
            intake.accept(as_bytes(original), now=NOW)
        original = request()
        original["required_checks"][0]["passed"] = True
        with self.assertRaisesRegex(intake.IntakeHeld, "CHECKLIST_MISMATCH"):
            intake.accept(as_bytes(original), now=NOW)
        original = request()
        original["required_checks"][0]["locally_reviewed"] = 1
        with self.assertRaisesRegex(intake.IntakeHeld, "CHECKLIST_MISMATCH"):
            intake.accept(as_bytes(original), now=NOW)

    def test_unknown_or_duplicate_surface_rejected(self):
        for types in (["__proto__"], ["webxr", "webxr"], [], ["unknown_type"]):
            original = request()
            original["surface_types"] = types
            with self.subTest(types=types):
                with self.assertRaises(intake.IntakeHeld):
                    intake.accept(as_bytes(original), now=NOW)

    def test_receipt_is_emitted_only_after_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "request.json"
            output = Path(temp) / "receipts"
            source.write_bytes(as_bytes(request()))
            receipt = intake.consume_file(source, output, now=NOW)
            saved = json.loads((output / "verification-intake.json").read_text())
            self.assertEqual(saved, receipt)
            self.assertEqual(saved["state"], "HELD_FOR_OPERATOR_REVIEW")
            source.write_bytes(as_bytes({**request(), "merge_authorized": True}))
            with self.assertRaises(intake.IntakeHeld):
                intake.consume_file(source, output, now=NOW)
            self.assertEqual(
                json.loads((output / "verification-intake.json").read_text()),
                receipt, "Invalid input must not overwrite an already valid intake"
            )

    def test_oversized_or_unzoned_request_rejected(self):
        with self.assertRaisesRegex(intake.IntakeHeld, "FILE_TOO_LARGE"):
            intake.accept(b" " * (intake.MAX_BYTES + 1), now=NOW)
        original = request()
        original["prepared_utc"] = "2026-11-03T07:59:00"
        with self.assertRaisesRegex(intake.IntakeHeld, "TIMESTAMP_UNZONED"):
            intake.accept(as_bytes(original), now=NOW)


if __name__ == "__main__":
    unittest.main()
