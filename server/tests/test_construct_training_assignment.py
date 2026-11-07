"""Agentora ΦConstruct R2: real local steward and R3 lease, no agent execution."""
from datetime import datetime, timedelta, timezone
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "server"))
import construct_training_assignment as assign
import construct_training_intake as training
import fleet_r04_leases as r4
import fleet_r3_steward_claim as r3
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 7, 20, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
SHA = "a" * 40


def handoff(agent="worker-alpha"):
    request = {
        "charter": training.CHARTER, "schema": training.HANDOFF_SCHEMA,
        "request_id": "training-001", "agent_label": agent,
        "agent_identity_verified": False, "mode": "code-lab",
        "task": {"id": "retry-backoff-code", "version": "0.1.0",
                 "digest": "sha256:" + "a" * 64},
        "approved_pack": {"id": "core.repo-evidence", "version": "0.1.0",
                          "digest": "sha256:" + "b" * 64,
                          "review_status": "approved"},
        "knowledge_is_reference_data": True,
        "task_execution_authorized": False, "worker_lease_issued": False,
        "source_head_verified": False, "dispatch_authorized": False,
        "merge_authorized": False, "deployment_authorized": False,
        "independent_evidence_verified": False,
        "handoff_state": "HELD_FOR_AGENTORA_OPERATOR_REVIEW",
    }
    request["handoff_digest"] = training.fingerprint(request)
    return request


def source_intake(name="BTM", rid=42, sha=SHA):
    return {
        "schema": r4.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": r4.OWNER, "repository": r4.OWNER + "/" + name,
        "repository_id": rid, "source_sha": sha,
        "request_sha256": "b" * 64, "verified_complete": False,
        "operator_approved": False, "dispatch_authorized": False,
        "merge_authorized": False, "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN", "evidence_receipt": None}],
    }


def public_observation(rows=None, scan=1):
    rows = rows if rows is not None else [(42, "BTM", False)]
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": scan,
        "observed_at": (NOW - timedelta(minutes=2)).isoformat(),
        "public_repo_count": len(rows),
        "repositories": [
            {"github_id": rid, "full_name": "MichaelWave369/" + name,
             "archived": archived, "source_only": True, "verified_complete": False}
            for rid, name, archived in rows
        ],
        "recent_events": [],
        "source_only": True, "dispatch_authorized": False,
        "merge_authorized": False, "verified_complete": False,
    }


@pytest.fixture
def setup(tmp_path):
    registry = StewardRegistry(tmp_path / "stewards.sqlite3")
    registry.ingest(public_observation(), now=NOW)
    ledger = r4.LeaseLedger(tmp_path / "leases.sqlite3")
    secret_file = tmp_path / "private" / "worker.lease"
    return registry, ledger, secret_file


def claim(setup, *, worker="worker-alpha", ttl=300):
    registry, ledger, secret_file = setup
    r3.claim(registry, ledger, source_intake(), worker,
             secret_file, now=NOW, now_ms=MS, ttl=ttl)
    return r4.load_capability(secret_file)


def test_preview_checks_steward_but_never_creates_lease(setup):
    registry, ledger, path = setup
    result = assign.review_binding(
        handoff(), source_intake(), registry, now=NOW, now_ms=MS
    )
    assert result["state"] == "HELD_TRAINING_BINDING_PREVIEW"
    assert result["repository"] == "MichaelWave369/BTM"
    assert result["github_id"] == 42
    assert result["lease_generation"] is None
    assert result["operator_confirmation_recorded"] is False
    assert not result["worker_started"]
    assert not result["execution_authorized"]
    assert ledger.status(MS)["active_reservations"] == 0


def test_operator_confirms_existing_fenced_worker_without_exposing_capability(setup):
    registry, ledger, path = setup
    cap = claim(setup)
    result = assign.review_binding(
        handoff(), source_intake(), registry, ledger, cap,
        confirm=assign.CONFIRM, now=NOW, now_ms=MS
    )
    assert result["state"] == "LOCAL_TRAINING_BINDING_REVIEWED_NO_EXECUTION"
    assert result["operator_confirmation_recorded"] is True
    assert result["lease_worker"] == "worker-alpha"
    assert result["lease_generation"] == cap["generation"]
    assert result["lease_expires_ms"] == cap["expires_ms"]
    assert result["source_sha"] == SHA
    assert result["current_github_head_independently_verified"] is False
    assert result["pack_approval_independently_verified"] is False
    assert result["agent_identity_authenticated"] is False
    for key in ("worker_started", "execution_authorized", "dispatch_authorized",
                "merge_authorized", "deployment_authorized", "training_executed",
                "training_result_verified", "general_competence_verified"):
        assert result[key] is False
    assert "token" not in json.dumps(result)
    assert cap["token"] not in json.dumps(result)


@pytest.mark.parametrize("field,new", [
    ("merge_authorized", True), ("worker_lease_issued", True),
    ("agent_identity_verified", True), ("deployment_authorized", True),
])
def test_forged_authority_refused_before_bind(setup, field, new):
    registry, ledger, path = setup
    cap = claim(setup)
    forged = handoff()
    forged[field] = new
    forged["handoff_digest"] = training.fingerprint({
        k: v for k, v in forged.items() if k != "handoff_digest"
    })
    with pytest.raises(assign.AssignmentHeld):
        assign.review_binding(
            forged, source_intake(), registry, ledger, cap,
            confirm=assign.CONFIRM, now=NOW, now_ms=MS
        )


def test_mismatched_worker_and_modified_lease_rejected(setup):
    registry, ledger, path = setup
    cap = claim(setup)
    with pytest.raises(assign.AssignmentHeld, match="WORKER_LABEL_MISMATCH"):
        assign.review_binding(
            handoff(agent="worker-other"), source_intake(), registry, ledger, cap,
            confirm=assign.CONFIRM, now=NOW, now_ms=MS
        )
    with pytest.raises(assign.AssignmentHeld, match="LEASE_OR_STEWARD_NOT_CURRENT"):
        assign.review_binding(
            handoff(), source_intake(), registry, ledger,
            {**cap, "token": "forged"},
            confirm=assign.CONFIRM, now=NOW, now_ms=MS
        )


def test_expired_lease_and_short_remaining_time_rejected(setup):
    registry, ledger, path = setup
    cap = claim(setup, ttl=90)
    with pytest.raises(assign.AssignmentHeld, match="LEASE_RENEWAL_REQUIRED"):
        assign.review_binding(
            handoff(), source_intake(), registry, ledger, cap,
            confirm=assign.CONFIRM, now=NOW, now_ms=MS + 40000
        )
    with pytest.raises(assign.AssignmentHeld, match="LEASE_OR_STEWARD_NOT_CURRENT"):
        assign.review_binding(
            handoff(), source_intake(), registry, ledger, cap,
            confirm=assign.CONFIRM, now=NOW, now_ms=MS + 90000
        )


def test_stale_or_archived_steward_rejected(setup):
    registry, ledger, path = setup
    with pytest.raises(assign.AssignmentHeld):
        assign.review_binding(
            handoff(), source_intake(), registry,
            now=NOW + timedelta(days=3), now_ms=MS
        )
    registry.ingest(public_observation([(42, "BTM", True)], scan=2), now=NOW)
    with pytest.raises(assign.AssignmentHeld):
        assign.review_binding(handoff(), source_intake(), registry,
                              now=NOW, now_ms=MS)


def test_source_sha_and_intake_identity_have_to_match_lease(setup):
    registry, ledger, path = setup
    cap = claim(setup)
    with pytest.raises(assign.AssignmentHeld, match="LEASE_INTAKE_MISMATCH"):
        assign.review_binding(
            handoff(), source_intake(sha="f" * 40), registry, ledger, cap,
            confirm=assign.CONFIRM, now=NOW, now_ms=MS
        )
    with pytest.raises(assign.AssignmentHeld):
        assign.review_binding(
            handoff(), source_intake(rid=99), registry, ledger, cap,
            confirm=assign.CONFIRM, now=NOW, now_ms=MS
        )


def test_operator_confirmation_is_explicit_and_never_claims_execution(setup):
    registry, ledger, path = setup
    cap = claim(setup)
    with pytest.raises(assign.AssignmentHeld, match="UNRECOGNIZED_OPERATOR_CONFIRMATION"):
        assign.review_binding(
            handoff(), source_intake(), registry, ledger, cap,
            confirm="EXECUTE", now=NOW, now_ms=MS
        )
    with pytest.raises(assign.AssignmentHeld, match="EXISTING_R3_LEASE_REQUIRED"):
        assign.review_binding(
            handoff(), source_intake(), registry,
            confirm=assign.CONFIRM, now=NOW, now_ms=MS
        )


def test_steward_change_between_lease_checks_refuses_binding(setup):
    registry, ledger, path = setup
    cap = claim(setup)
    valid = r3.eligible(registry, source_intake(), now=NOW)
    altered = dict(valid)
    altered["source_scan_id"] += 1
    with patch.object(assign.steward, "eligible", side_effect=[valid, altered]):
        with pytest.raises(assign.AssignmentHeld, match="STEWARD_CHANGED"):
            assign.review_binding(
                handoff(), source_intake(), registry, ledger, cap,
                confirm=assign.CONFIRM, now=NOW, now_ms=MS
            )


def test_cli_preview_and_confirm_are_read_only(setup, tmp_path, monkeypatch):
    registry, ledger, lease_path = setup
    cap = claim(setup)
    handoff_file, intake_file = tmp_path / "handoff.json", tmp_path / "intake.json"
    handoff_file.write_text(json.dumps(handoff()), encoding="utf-8")
    intake_file.write_text(json.dumps(source_intake()), encoding="utf-8")
    common = [
        "--handoff", str(handoff_file), "--intake", str(intake_file),
        "--steward-db", str(registry.path), "--lease-db", str(ledger.path),
    ]
    real_review = assign.review_binding
    def fixed_clock_review(*args, **kwargs):
        return real_review(*args, now=NOW, now_ms=MS, **kwargs)
    monkeypatch.setattr(assign, "review_binding", fixed_clock_review)
    with contextlib.redirect_stdout(io.StringIO()) as output:
        assert assign.main(common) == 0
    preview = json.loads(output.getvalue())
    assert preview["state"] == "HELD_TRAINING_BINDING_PREVIEW"
    with contextlib.redirect_stdout(io.StringIO()) as output:
        assert assign.main(common + [
            "--lease-file", str(lease_path), "--confirm", assign.CONFIRM
        ]) == 0
    binding = json.loads(output.getvalue())
    assert binding["lease_generation"] == cap["generation"]
    assert binding["operator_confirmation_recorded"] is True
    assert ledger.status(MS)["active_reservations"] == 1


def test_cli_rejects_capability_file_without_confirmation(setup, tmp_path):
    registry, ledger, lease_path = setup
    claim(setup)
    handoff_file, intake_file = tmp_path / "handoff.json", tmp_path / "intake.json"
    handoff_file.write_text(json.dumps(handoff()), encoding="utf-8")
    intake_file.write_text(json.dumps(source_intake()), encoding="utf-8")
    with contextlib.redirect_stderr(io.StringIO()) as errs:
        result = assign.main([
            "--handoff", str(handoff_file), "--intake", str(intake_file),
            "--steward-db", str(registry.path), "--lease-db", str(ledger.path),
            "--lease-file", str(lease_path)
        ])
    assert result == 3
    assert "LEASE_FILE_REQUIRES_CONFIRMATION" in errs.getvalue()
