"""Contract vectors shared with PhiOS R4a governed-memory admission tests."""
import copy
import json

import pytest

from app.integrations.writeback_idempotency import (
    PROTOCOL, canonical_envelope, operation_id, operation_identity,
)

FIXED_OPERATION_ID = "056f70f4e94787b3aa2f96e82fd93bd173f1b92582deaec4c2f12e698431ba06"


def _payload():
    return {
        "session_id": "session-1", "task_id": "job-123",
        "raw_payload": {"outcome": {
            "job_id": "job-123", "status": "completed", "summary": "Done",
        }},
    }


def test_fixed_cross_repository_operation_id():
    assert operation_id(_payload()) == FIXED_OPERATION_ID
    assert PROTOCOL == "phios.agentora.writeback.v1"


def test_presentation_only_changes_conflict_under_same_id():
    baseline = _payload()
    updated = copy.deepcopy(baseline)
    updated["operator_notes"] = "reformatted"
    assert operation_id(updated) == operation_id(baseline)
    assert canonical_envelope(updated, created_at_utc="2026-11-21T19:00:00Z") != (
        canonical_envelope(baseline, created_at_utc="2026-11-21T19:00:00Z")
    )


def test_new_outcome_yields_new_operation():
    baseline = _payload()
    updated = copy.deepcopy(baseline)
    updated["raw_payload"]["outcome"]["summary"] = "Something else happened"
    assert operation_id(updated) != operation_id(baseline)


def test_same_envelope_timestamp_normalizes_consistently():
    a = canonical_envelope(_payload(), created_at_utc="2026-11-21T19:00:00Z")
    b = canonical_envelope(_payload(), created_at_utc="2026-11-21T11:00:00-08:00")
    assert a == b
    assert json.loads(a)["created_at_utc"] == "2026-11-21T19:00:00+00:00"


@pytest.mark.parametrize("invalid", [
    {}, {"session_id": "s", "task_id": "t"},
    {"session_id": "s", "task_id": "t", "raw_payload": {"outcome": []}},
    {"session_id": 3, "task_id": "t", "raw_payload": {"outcome": {"ok": True}}},
])
def test_identity_rejects_missing_or_malformed_fields(invalid):
    with pytest.raises(ValueError):
        operation_identity(invalid)


def test_invalid_or_naive_timestamp_rejected():
    with pytest.raises(ValueError, match="timezone"):
        canonical_envelope(_payload(), created_at_utc="2026-11-21T19:00:00")
    with pytest.raises(ValueError, match="invalid"):
        canonical_envelope(_payload(), created_at_utc="not-a-timestamp")


def test_envelope_size_limit_and_stable_validation():
    huge = _payload()
    huge["operator_notes"] = "x" * 40000
    with pytest.raises(ValueError, match="too large"):
        canonical_envelope(huge, created_at_utc="2026-11-21T19:00:00Z")
