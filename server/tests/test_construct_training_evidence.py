"""Construct R3 tests: real local fencing, stubbed GitHub GET, never execute code."""
from datetime import datetime, timedelta, timezone
import contextlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "server"))
import construct_training_evidence as evidence
import construct_training_intake as training
import fleet_r04_leases as leases
import fleet_r3_steward_claim as steward
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 7, 21, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
SHA = "a" * 40


def handoff(agent="worker-alpha"):
    raw = {
        "charter": training.CHARTER,
        "schema": training.HANDOFF_SCHEMA,
        "request_id": "training-001",
        "agent_label": agent,
        "agent_identity_verified": False,
        "mode": "code-lab",
        "task": {
            "id": "retry-backoff-code", "version": "0.1.0",
            "digest": "sha256:" + "b" * 64,
        },
        "approved_pack": {
            "id": "core.repo-evidence", "version": "0.1.0",
            "digest": "sha256:" + "c" * 64, "review_status": "approved",
        },
        "knowledge_is_reference_data": True,
        "task_execution_authorized": False,
        "worker_lease_issued": False,
        "source_head_verified": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "independent_evidence_verified": False,
        "handoff_state": "HELD_FOR_AGENTORA_OPERATOR_REVIEW",
    }
    raw["handoff_digest"] = training.fingerprint(raw)
    return raw


def report(request):
    return {
        "charter": training.CHARTER,
        "schema": training.REPORT_SCHEMA,
        "request_id": request["request_id"],
        "handoff_digest": request["handoff_digest"],
        "report_digest": "sha256:" + "d" * 64,
        "mode": request["mode"], "task": request["task"],
        "approved_pack": request["approved_pack"],
        "candidate_claim": "reported_pass",
        "state": "HELD_AWAITING_INDEPENDENT_ATTESTATION",
        "receipt_source_authenticated": False,
        "agent_identity_verified": False,
        "independent_evidence_verified": False,
        "worker_lease_verified": False,
        "current_source_head_verified": False,
        "execution_authorized": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "notes": "JSON structure checked but caller has not been authenticated.",
    }


def source_intake():
    return {
        "schema": leases.INTAKE_SCHEMA,
        "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER,
        "repository": "MichaelWave369/BTM",
        "repository_id": 42,
        "default_branch": "main",
        "source_sha": SHA,
        "request_sha256": "e" * 64,
        "verified_complete": False,
        "operator_approved": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False,
        "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN",
                    "evidence_receipt": None}],
    }


def observation():
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": 1,
        "observed_at": (NOW - timedelta(minutes=2)).isoformat(),
        "public_repo_count": 1,
        "repositories": [{
            "github_id": 42, "full_name": "MichaelWave369/BTM",
            "archived": False, "source_only": True, "verified_complete": False,
        }],
        "recent_events": [],
        "source_only": True, "dispatch_authorized": False,
        "merge_authorized": False, "verified_complete": False,
    }


class GithubFixture:
    """Only responses to the existing R0.5 fixed public repo/branch endpoints."""
    def __init__(self, *, sha=SHA, name="MichaelWave369/BTM",
                 archived=False, change_after=None):
        self.sha = sha
        self.name = name
        self.archived = archived
        self.change_after = change_after
        self.calls = []
    def __call__(self, path, token):
        self.calls.append((path, token))
        if path.endswith("/branches/main"):
            n = sum(x[0].endswith("/branches/main") for x in self.calls)
            current = self.sha if self.change_after is None or n <= self.change_after \
                else "f" * 40
            return {"name": "main", "commit": {"sha": current}}
        assert path == "/repos/MichaelWave369/BTM"
        return {
            "id": 42, "full_name": self.name,
            "owner": {"login": "MichaelWave369"}, "private": False,
            "archived": self.archived, "default_branch": "main",
        }


@pytest.fixture
def setup(tmp_path):
    registry = StewardRegistry(tmp_path / "stewards.sqlite3")
    registry.ingest(observation(), now=NOW)
    ledger = leases.LeaseLedger(tmp_path / "leases.sqlite3")
    target = tmp_path / "secret.lease"
    steward.claim(registry, ledger, source_intake(), "worker-alpha", target,
                  ttl=300, now=NOW, now_ms=MS)
    return registry, ledger, leases.load_capability(target), target


def assess(setup, *, gh=None, request=None, claimed=None, now=NOW, clock=None):
    registry, ledger, cap, _ = setup
    request = request if request is not None else handoff()
    return evidence.correlate(
        request, source_intake(), registry, ledger, cap,
        confirm=evidence.CONFIRM, report=claimed,
        source_get=gh or GithubFixture(), token="not-exported",
        now=now, clock=clock or (lambda: MS),
    )


def test_verified_source_and_lease_still_hold_training_outcome(setup):
    gh = GithubFixture()
    result = assess(setup, gh=gh, claimed=report(handoff()))
    assert result["state"] == "SOURCE_HEAD_AND_LOCAL_LEASE_CORRELATED_TRAINING_UNATTESTED"
    assert result["source_head_independently_observed"] is True
    assert result["repository_identity_independently_observed"] is True
    assert result["local_lease_valid_at_review"] is True
    assert result["candidate_training_result_claim"] == "reported_pass"
    assert result["welcome_charter_version"] == "0.1.0"
    assert result["lease_generation"] == 1
    assert len(result["source_observations"]) == 2
    assert len(gh.calls) == 6
    assert all(x[1] == "not-exported" for x in gh.calls)
    assert "not-exported" not in json.dumps(result)
    assert "token" not in json.dumps(result)
    for name in ("training_result_independently_verified",
                 "training_executor_authenticated", "agent_identity_authenticated",
                 "remote_runner_attested_local_lease",
                 "pack_approval_independently_verified",
                 "capability_verified", "execution_authorized",
                 "merge_authorized", "deployment_authorized", "dispatch_authorized"):
        assert result[name] is False


def test_without_candidate_report_no_success_claim(setup):
    result = assess(setup)
    assert result["candidate_training_result_claim"] is None
    assert result["training_result_independently_verified"] is False


@pytest.mark.parametrize("bad", [
    GithubFixture(sha="f" * 40),
    GithubFixture(name="MichaelWave369/Renamed"),
    GithubFixture(archived=True),
    GithubFixture(change_after=2),
])
def test_wrong_current_head_or_repo_identity_held(setup, bad):
    with pytest.raises(evidence.CorrelationHeld):
        assess(setup, gh=bad)


def test_no_github_call_when_handoff_or_result_claims_forbidden_authority(setup):
    bad = handoff()
    bad["merge_authorized"] = True
    bad["handoff_digest"] = training.fingerprint({
        k: v for k, v in bad.items() if k != "handoff_digest"
    })
    gh = GithubFixture()
    with pytest.raises(evidence.CorrelationHeld):
        assess(setup, gh=gh, request=bad)
    assert gh.calls == []
    gh = GithubFixture()
    claimed = report(handoff())
    claimed["independent_evidence_verified"] = True
    with pytest.raises(evidence.CorrelationHeld):
        assess(setup, gh=gh, claimed=claimed)
    assert gh.calls == []


def test_mismatched_claimed_report_held(setup):
    gh = GithubFixture()
    claimed = report(handoff())
    claimed["task"]["digest"] = "sha256:" + "f" * 64
    with pytest.raises(evidence.CorrelationHeld):
        assess(setup, gh=gh, claimed=claimed)
    assert gh.calls == []


def test_invalid_or_expired_lease_fails_before_github(setup):
    registry, ledger, cap, _ = setup
    gh = GithubFixture()
    with pytest.raises(evidence.CorrelationHeld):
        evidence.correlate(handoff(), source_intake(), registry, ledger,
                           {**cap, "token": "forged"},
                           confirm=evidence.CONFIRM, source_get=gh,
                           now=NOW, clock=lambda: MS)
    assert gh.calls == []
    with pytest.raises(evidence.CorrelationHeld):
        assess(setup, gh=gh, clock=lambda: MS + 300001)
    assert gh.calls == []


def test_stale_or_archived_steward_fails_before_github(setup):
    registry, ledger, cap, _ = setup
    gh = GithubFixture()
    with pytest.raises(evidence.CorrelationHeld):
        assess(setup, gh=gh, now=NOW + timedelta(days=3))
    assert gh.calls == []
    registry.ingest({**observation(),
                     "repositories": [{
                         "github_id": 42, "full_name": "MichaelWave369/BTM",
                         "archived": True, "source_only": True,
                         "verified_complete": False,
                     }]}, now=NOW)
    with pytest.raises(evidence.CorrelationHeld):
        assess(setup, gh=gh)
    assert gh.calls == []


def test_confirmation_required_and_cannot_self_authorize(setup):
    registry, ledger, cap, _ = setup
    gh = GithubFixture()
    with pytest.raises(evidence.CorrelationHeld, match="EXPLICIT_REVIEW"):
        evidence.correlate(handoff(), source_intake(), registry, ledger, cap,
                           confirm="RUN_ALL_AGENTS", source_get=gh, now=NOW,
                           clock=lambda: MS)
    assert gh.calls == []


def test_lease_change_between_reads_fails_closed(setup):
    registry, ledger, cap, _ = setup
    counter = [0]
    def clock():
        counter[0] += 1
        # Preflight initially valid; change to an expired instant at final check.
        return MS if counter[0] < 5 else MS + 300001
    with pytest.raises(evidence.CorrelationHeld):
        evidence.correlate(handoff(), source_intake(), registry, ledger, cap,
                           confirm=evidence.CONFIRM,
                           source_get=GithubFixture(), now=NOW, clock=clock)


def test_cli_readonly_writes_no_reports_or_authority(tmp_path, setup, monkeypatch):
    registry, ledger, cap, lease_path = setup
    request_path = tmp_path / "request.json"
    source_path = tmp_path / "source.json"
    report_path = tmp_path / "report.json"
    request_path.write_text(json.dumps(handoff()), encoding="utf-8")
    source_path.write_text(json.dumps(source_intake()), encoding="utf-8")
    report_path.write_text(json.dumps(report(handoff())), encoding="utf-8")
    raw_correlate = evidence.correlate
    def mocked(*args, **kwargs):
        return raw_correlate(
            *args, **{**kwargs, "source_get": GithubFixture(), "now": NOW,
                      "clock": lambda: MS}
        )
    monkeypatch.setattr(evidence, "correlate", mocked)
    argv = [
        "--handoff", str(request_path), "--intake", str(source_path),
        "--report", str(report_path),
        "--steward-db", str(registry.path),
        "--lease-db", str(ledger.path),
        "--lease-file", str(lease_path), "--confirm", evidence.CONFIRM,
    ]
    with contextlib.redirect_stdout(io.StringIO()) as stdout:
        assert evidence.main(argv) == 0
    result = json.loads(stdout.getvalue())
    assert result["training_result_independently_verified"] is False
    assert result["state"].endswith("UNATTESTED")
    assert not (tmp_path / "new-lease.json").exists()
    assert ledger.status(MS)["active_reservations"] == 1
