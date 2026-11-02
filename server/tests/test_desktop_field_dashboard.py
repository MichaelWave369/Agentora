"""R9 read-only dashboard checks. No UI, network, desktop, or approvals."""
from datetime import datetime, timezone
import json
import os
import sqlite3

import pytest

from app.services.desktop_field_dashboard import (
    FieldReadinessDashboard, _redacted_entry, render_readiness,
)
from app.services.desktop_field_ledger import FieldLedger
from app.services.desktop_operator_desk import OperatorDeskModel, OperatorPolicy


def receipt():
    return {
        "schema": 1, "receipt_id": "a" * 24,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "probe": "r6_user_restricted_read_only_pipe",
        "broker_reports_click_disabled": True,
        "r6_transport_marker_observed": True,
        "transport_identity_cryptographically_attested": False,
        "labels_redacted": True,
        "observation_metadata_valid": True,
        "observations_checked": 2, "distinct_snapshot_ids": True,
        "first_observation_target_count": 1, "truncated": False,
        "user_task_verified": False,
        "cross_user_dacl_negative_test": "NOT_PERFORMED",
        "real_windows_desktop_compatibility": "NOT_VERIFIED_BY_THIS_RECEIPT",
        "independent_security_review": "NOT_PERFORMED",
        "autonomous_execution_authorized": False,
        "mutating_action_requested": False,
    }


def test_missing_journal_is_not_created(tmp_path):
    path = tmp_path / "missing" / "field.db"
    view = FieldReadinessDashboard(path).snapshot()
    assert view["availability"] == "not_recorded"
    assert view["total_self_reports"] == 0
    assert not path.parent.exists()
    assert view["autonomous_desktop_ready"] is False


def test_operator_report_is_not_security_certification(tmp_path):
    path = tmp_path / "private" / "field.db"
    FieldLedger(path).record(receipt(), status="observed", issue="none")
    view = FieldReadinessDashboard(path).snapshot()
    assert view["availability"] == "available"
    assert view["total_self_reports"] == 1
    assert view["recent_self_reports"][0]["reported_outcome"] == "observed"
    for key in ("execution_authorized", "task_verified",
                "source_integrity_verified", "windows_file_acl_verified",
                "autonomous_desktop_ready"):
        assert view[key] is False
    text = render_readiness(view)
    assert "NOT AUTHORIZED" in text
    assert "NOT VERIFIED" in text


def test_only_known_data_can_be_displayed(tmp_path):
    path = tmp_path / "private" / "field.db"
    ledger = FieldLedger(path)
    saved = ledger.record(receipt(), status="observed", issue="none")
    with sqlite3.connect(path) as conn:
        raw = json.loads(conn.execute(
            "SELECT record_json FROM field_reports WHERE id=?", (saved["entry_id"],)
        ).fetchone()[0])
        raw["arbitrary_app_content"] = "SECRET DESKTOP DATA"
        conn.execute(
            "UPDATE field_reports SET record_json=? WHERE id=?",
            (json.dumps(raw), saved["entry_id"]),
        )
        conn.commit()
    snapshot = FieldReadinessDashboard(path).snapshot()
    assert "SECRET DESKTOP DATA" not in json.dumps(snapshot)
    assert "SECRET DESKTOP DATA" not in render_readiness(snapshot)


def test_tampered_execution_flag_not_rendered_as_success():
    entry = {
        "schema": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "operator_reported_status": "observed",
        "operator_issue_category": "none",
        "receipt": {"observations_checked": 2},
        "execution_authorization": True, "autonomous_readiness": False,
        "operator_statement_independently_verified": False,
        "source_signature_validated": False,
    }
    assert _redacted_entry(json.dumps(entry)) is None
    entry["execution_authorization"] = False
    assert _redacted_entry(json.dumps(entry)) is not None
    entry["operator_reported_status"] = {"invalid": 1}
    assert _redacted_entry(json.dumps(entry)) is None


def test_does_not_change_journal_file(tmp_path):
    path = tmp_path / "private" / "field.db"
    FieldLedger(path).record(receipt(), status="issue", issue="other")
    size = path.stat().st_size
    result = FieldReadinessDashboard(path).snapshot()
    assert result["recent_self_reports"][0]["issue_category"] == "other"
    assert path.stat().st_size == size


def test_corrupt_database_fails_closed(tmp_path):
    folder = tmp_path / "private"
    folder.mkdir(mode=0o700)
    path = folder / "field.db"
    path.write_text("not SQLite", encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
    state = FieldReadinessDashboard(path).snapshot()
    assert state["availability"] == "unavailable_or_insecure"
    assert state["autonomous_desktop_ready"] is False


def test_symlinked_journal_denied(tmp_path):
    path = tmp_path / "private" / "field.db"
    FieldLedger(path)
    link = path.parent / "other.db"
    try:
        link.symlink_to(path)
    except OSError:
        pytest.skip("symlink unavailable")
    assert FieldReadinessDashboard(link).snapshot()["availability"] == "unavailable_or_insecure"


def test_posix_insecure_storage_denied(tmp_path):
    if os.name != "posix":
        pytest.skip("POSIX-only permission check")
    path = tmp_path / "private" / "field.db"
    FieldLedger(path)
    path.parent.chmod(0o755)
    try:
        assert FieldReadinessDashboard(path).snapshot()["availability"] == "unavailable_or_insecure"
    finally:
        path.parent.chmod(0o700)


def test_view_does_not_touch_proposal_inbox(tmp_path):
    class NoInboxCalls:
        def __getattr__(self, _):
            raise AssertionError("Field panel must not access proposals")
    model = OperatorDeskModel(
        NoInboxCalls(), OperatorPolicy({}),
        field_db=tmp_path / "none" / "journal.db",
    )
    assert model.field_readiness()["availability"] == "not_recorded"
    assert model.field_readiness()["execution_authorized"] is False


def test_self_report_never_changes_review_policy(tmp_path):
    path = tmp_path / "private" / "field.db"
    FieldLedger(path).record(receipt(), status="observed", issue="none")
    policy = OperatorPolicy({"Calculator": frozenset({"observe"})})
    model = OperatorDeskModel(None, policy, field_db=path)
    assert model.field_readiness()["total_self_reports"] == 1
    assert policy.permits("Calculator", "click") is False
    assert "NOT AUTHORIZED" in model.field_readiness_text()
