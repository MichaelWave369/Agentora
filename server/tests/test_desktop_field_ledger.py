"""R8 ledger tests: only local, redacted, self-reported field evidence."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import sys

import pytest

from app.services.desktop_bridge import DesktopBridgeError
from app.services.desktop_field_ledger import (
    FieldLedger, load_receipt, main, validate_receipt,
)


def sample_receipt(receipt_id="a" * 24):
    return {
        "schema": 1,
        "receipt_id": receipt_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probe": "r6_user_restricted_read_only_pipe",
        "broker_reports_click_disabled": True,
        "r6_transport_marker_observed": True,
        "transport_identity_cryptographically_attested": False,
        "labels_redacted": True,
        "observation_metadata_valid": True,
        "observations_checked": 2,
        "distinct_snapshot_ids": True,
        "first_observation_target_count": 3,
        "truncated": False,
        "user_task_verified": False,
        "cross_user_dacl_negative_test": "NOT_PERFORMED",
        "real_windows_desktop_compatibility": "NOT_VERIFIED_BY_THIS_RECEIPT",
        "independent_security_review": "NOT_PERFORMED",
        "autonomous_execution_authorized": False,
        "mutating_action_requested": False,
    }


def fails(code, callback):
    with pytest.raises(DesktopBridgeError) as exc:
        callback()
    assert exc.value.code == code


def test_ledger_records_operator_self_report_never_grants_execution(tmp_path):
    ledger = FieldLedger(tmp_path / "private" / "journal.db")
    receipt = sample_receipt()
    entry = ledger.record(receipt, status="observed", issue="none")
    assert entry["operator_reported_status"] == "observed"
    assert entry["operator_statement_independently_verified"] is False
    assert entry["cross_account_denial_verified"] is False
    assert entry["execution_authorization"] is False
    assert entry["source_signature_validated"] is False
    assert entry["autonomous_readiness"] is False
    assert ledger.reports()[0]["entry_id"] == entry["entry_id"]
    result = ledger.readiness()
    assert result["local_operator_entries"] == 1
    assert result["reported_outcomes"]["observed"] == 1
    assert result["ready_for_autonomous_desktop_actions"] is False
    assert result["ledger_cryptographically_attested"] is False


def test_receipt_has_no_ability_to_inject_unredacted_fields():
    receipt = sample_receipt()
    receipt["password"] = "do-not-record"
    fails("field_receipt_schema_denied", lambda: validate_receipt(receipt))


@pytest.mark.parametrize("key,value", [
    ("broker_reports_click_disabled", False),
    ("broker_reports_click_disabled", 1),
    ("labels_redacted", False),
    ("r6_transport_marker_observed", False),
    ("transport_identity_cryptographically_attested", True),
    ("autonomous_execution_authorized", True),
    ("mutating_action_requested", True),
    ("user_task_verified", True),
    ("cross_user_dacl_negative_test", "PASSED"),
    ("real_windows_desktop_compatibility", "VERIFIED"),
    ("independent_security_review", "PASSED"),
])
def test_unsafe_or_unsupported_receipt_claim_rejected(key, value):
    receipt = sample_receipt()
    receipt[key] = value
    fails("field_receipt_claim_denied", lambda: validate_receipt(receipt))


@pytest.mark.parametrize("key,value", [
    ("schema", True),
    ("receipt_id", "not-valid"),
    ("created_at", "2026-11-01"),
    ("observations_checked", True),
    ("observations_checked", 3),
    ("distinct_snapshot_ids", False),
    ("first_observation_target_count", -1),
    ("first_observation_target_count", 100001),
    ("truncated", 0),
])
def test_invalid_shape_rejected(key, value):
    receipt = sample_receipt()
    receipt[key] = value
    fails("field_receipt_schema_denied", lambda: validate_receipt(receipt))


def test_one_observation_receipt_has_no_second_snapshot_assertion():
    receipt = sample_receipt()
    receipt["observations_checked"] = 1
    receipt["distinct_snapshot_ids"] = None
    safe = validate_receipt(receipt)
    assert safe["observations_checked"] == 1


def test_stale_duplicate_receipt_cannot_be_recorded_twice(tmp_path):
    ledger = FieldLedger(tmp_path / "private" / "journal.db")
    receipt = sample_receipt()
    ledger.record(receipt, status="observed", issue="none")
    fails("field_duplicate_receipt",
          lambda: ledger.record(receipt, status="observed", issue="none"))
    assert ledger.readiness()["local_operator_entries"] == 1


def test_issue_requires_a_reported_reason(tmp_path):
    ledger = FieldLedger(tmp_path / "private" / "journal.db")
    receipt = sample_receipt()
    fails("field_invalid_operator_status",
          lambda: ledger.record(receipt, status="issue", issue="none"))
    fails("field_invalid_operator_status",
          lambda: ledger.record(receipt, status="observed", issue="other"))
    fails("field_invalid_operator_status",
          lambda: ledger.record(receipt, status="approved", issue="none"))
    saved = ledger.record(receipt, status="inconclusive", issue="transport-failure")
    assert saved["operator_issue_category"] == "transport-failure"


def test_file_load_is_bounded_and_removes_unknown_context(tmp_path):
    path = tmp_path / "redacted.json"
    path.write_text(json.dumps(sample_receipt()), encoding="utf-8")
    compact = load_receipt(path)
    assert set(compact) == {
        "receipt_id", "receipt_created_at", "observations_checked",
        "first_observation_target_count", "truncated",
    }
    too_big = tmp_path / "large.json"
    too_big.write_text("a" * 4097)
    fails("field_receipt_file_denied", lambda: load_receipt(too_big))


def test_symlinked_receipt_denied(tmp_path):
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(sample_receipt()))
    link = tmp_path / "link.json"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlinks unsupported")
    fails("field_receipt_file_denied", lambda: load_receipt(link))


def test_private_storage_permissions_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX-only mode checks")
    path = tmp_path / "private" / "journal.db"
    ledger = FieldLedger(path)
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    ledger.record(sample_receipt(), status="observed", issue="none")


def test_insecure_existing_directory_denied_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX permissions")
    folder = tmp_path / "public"
    folder.mkdir(mode=0o777)
    folder.chmod(0o755)
    fails("field_insecure_directory", lambda: FieldLedger(folder / "ledger.db"))


def test_sqlite_file_symlink_denied(tmp_path):
    real = tmp_path / "real.db"
    target = tmp_path / "private"
    target.mkdir(mode=0o700)
    link = target / "ledger.db"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("symlinks unsupported")
    fails("field_ledger_symlink_denied", lambda: FieldLedger(link))


def test_readiness_cli_is_offline(tmp_path, capsys):
    code = main(["--db", str(tmp_path / "private" / "ledger.db"), "readiness"])
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ready_for_autonomous_desktop_actions"] is False
    assert summary["local_operator_entries"] == 0


def test_ci_noninteractive_cannot_record(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    code = main(["--db", str(tmp_path / "private" / "ledger.db"),
                 "record", "--receipt", "test.json", "--status", "observed"])
    assert code == 2
    assert not (tmp_path / "private" / "ledger.db").exists()


def test_entry_never_copies_upstream_labels_or_secrets(tmp_path):
    ledger = FieldLedger(tmp_path / "private" / "journal.db")
    entry = ledger.record(sample_receipt(), status="observed", issue="none")
    serialized = json.dumps(entry)
    for forbidden in ("pipe\\\\", "password", "snapshot_id", "element_ref",
                      "session_key", "source_name", "raw_tree"):
        assert forbidden not in serialized


def test_r7_sanitized_receipt_saving_is_opt_in_and_non_overwriting(tmp_path, monkeypatch):
    from app.services import desktop_windows_field_validation as field
    profile_key = "USERPROFILE" if os.name == "nt" else "HOME"
    monkeypatch.setenv(profile_key, str(tmp_path))
    report = sample_receipt()
    dest = field.save_local_receipt(report, "calculator-field.json")
    assert dest.name == "calculator-field.json"
    assert dest.parent.name == "field-trials"
    assert load_receipt(dest)["receipt_id"] == report["receipt_id"]
    fails("field_receipt_exists",
          lambda: field.save_local_receipt(report, "calculator-field.json"))
    fails("field_receipt_filename_denied",
          lambda: field.save_local_receipt(report, "../outside.json"))
    fails("field_receipt_filename_denied",
          lambda: field.save_local_receipt(report, "nested/file.json"))


def test_r7_saving_refuses_receipt_with_sensitive_extra_fields(tmp_path, monkeypatch):
    from app.services import desktop_windows_field_validation as field
    profile_key = "USERPROFILE" if os.name == "nt" else "HOME"
    monkeypatch.setenv(profile_key, str(tmp_path))
    receipt = sample_receipt()
    receipt["screen_contents"] = "sensitive text"
    fails("field_receipt_schema_denied",
          lambda: field.save_local_receipt(receipt, "safe.json"))
    assert not (tmp_path / ".agentora" / "field-trials" / "safe.json").exists()


def test_r7_interactive_default_uses_pipe_rebind_readiness():
    from app.services import desktop_windows_field_validation as field
    assert field.run_supervised.__kwdefaults__["requester"] is field._request_when_pipe_ready


def test_local_receipt_is_not_an_execution_approval(tmp_path, monkeypatch):
    from app.services import desktop_windows_field_validation as field
    profile_key = "USERPROFILE" if os.name == "nt" else "HOME"
    monkeypatch.setenv(profile_key, str(tmp_path))
    receipt = sample_receipt()
    dest = field.save_local_receipt(receipt, "observation.json")
    ledger = FieldLedger(dest.parent / "journal.db")
    entry = ledger.record(receipt, status="observed", issue="none")
    assert entry["receipt"]["receipt_id"] == load_receipt(dest)["receipt_id"]
    assert ledger.readiness()["ready_for_autonomous_desktop_actions"] is False
    assert ledger.readiness()["external_security_review_verified"] is False
