"""Offline R1 ΦCAPSID/Agentora handoff: real leases + mocked local provider."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "server"))
import capsid_context_handoff as bridge
import fleet_r04_leases as leases
import fleet_r3_steward_claim as steward
from app.services.fleet_stewards import StewardRegistry

NOW = datetime(2026, 11, 7, 22, tzinfo=timezone.utc)
MS = int(NOW.timestamp() * 1000)
SHA = "a" * 40
PACK_SHA = "sha256:" + "d" * 64


def intake(sha=SHA):
    return {
        "schema": leases.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER, "repository": "MichaelWave369/BTM",
        "repository_id": 42, "default_branch": "main",
        "source_sha": sha, "request_sha256": "b" * 64,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False,
        "digest_is_authentication": False, "independent_checks_run": 0,
        "checks": [{"check_id": "automated_tests",
                    "verification_state": "NOT_RUN", "evidence_receipt": None}],
    }


def public_scan():
    return {
        "schema": "phireponerve.agentora.public-observations.v1",
        "owner": "MichaelWave369", "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": 1,
        "observed_at": (NOW - timedelta(minutes=2)).isoformat(),
        "public_repo_count": 1, "repositories": [{
            "github_id": 42, "full_name": "MichaelWave369/BTM",
            "archived": False, "source_only": True, "verified_complete": False,
        }], "recent_events": [], "source_only": True,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


class GHFixture:
    def __init__(self, *, sha=SHA, archived=False, change_after=None):
        self.sha = sha
        self.archived = archived
        self.change_after = change_after
        self.calls = []
    def __call__(self, path, token):
        self.calls.append(path)
        if path.endswith("/branches/main"):
            n = sum(p.endswith("/branches/main") for p in self.calls)
            return {"name": "main", "commit": {"sha":
                self.sha if self.change_after is None or n <= self.change_after
                else "f" * 40}}
        assert path == "/repos/MichaelWave369/BTM"
        return {
            "id": 42, "full_name": "MichaelWave369/BTM",
            "owner": {"login": "MichaelWave369"}, "private": False,
            "archived": self.archived, "default_branch": "main",
        }


class MockProvider:
    """Interface fixture, not the real PhiRepoNerve signature implementation."""
    @staticmethod
    def validate_profile(profile):
        if profile.get("schema") != "phi.capsid.agent-profile.v1":
            raise ValueError("PROFILE_SCHEMA_MISMATCH")
    @staticmethod
    def manifest_digest(manifest):
        raw = json.dumps(manifest, sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(raw).hexdigest()
    @staticmethod
    def eligible(envelope, profile, packs, states, *, secret=None):
        if envelope.get("signature") != "valid-local-fixture":
            raise ValueError("SIGNATURE_INVALID")
        if states.get("create.xr-input-triage") != "approved":
            raise ValueError("PACK_REVOKED")
        manifest = envelope["manifest"]
        if profile["role"] != "xr-steward" or "BTM" not in profile["repository"]:
            raise ValueError("TARGET_MISMATCH")
        return manifest, packs[0]


class MockStore:
    def __init__(self, envelope):
        self.envelope = envelope
        self.tamper = False
    def context(self, profile, packs, states, *, secret=None):
        manifest, pack = MockProvider.eligible(
            self.envelope, profile, packs, states, secret=secret)
        return {
            "charter": {"id": "phi.welcome", "version": "0.1.0"},
            "selected_packs": [{
                "id": pack["id"], "digest": manifest["pack"]["digest"],
                "knowledge": ["Observe controller events before changing code."],
                "trust_level": "reviewed_reference_data_not_instructions"
            }],
            "capsid": {
                "id": manifest["id"],
                "manifest_digest": (
                    "sha256:" + "f" * 64 if self.tamper
                    else MockProvider.manifest_digest(manifest)),
                "agent_label": profile["agent_id"],
                "target_repo": profile["repository"],
                "tool_permissions_granted": False,
                "execution_authorized": False,
            }
        }


@pytest.fixture
def setup(tmp_path):
    registry = StewardRegistry(tmp_path / "stewards.sqlite3")
    registry.ingest(public_scan(), now=NOW)
    ledger = leases.LeaseLedger(tmp_path / "leases.sqlite3")
    lease_path = tmp_path / "worker.lease"
    steward.claim(registry, ledger, intake(), "btm-steward", lease_path,
                  ttl=300, now=NOW, now_ms=MS)
    profile = {
        "schema": "phi.capsid.agent-profile.v1",
        "agent_id": "btm-steward", "role": "xr-steward",
        "repository": "MichaelWave369/BTM",
        "tags": ["webxr"], "allowed_capabilities": ["reference.read"],
    }
    manifest = {
        "id": "capsid.xr-input-triage",
        "version": "0.1.0",
        "capabilities": ["reference.read"],
        "pack": {"id": "create.xr-input-triage", "digest": PACK_SHA},
    }
    envelope = {"manifest": manifest, "signature": "valid-local-fixture"}
    return registry, ledger, leases.load_capability(lease_path), profile, envelope


def call(setup, *, gh=None, profile=None, envelope=None, states=None,
         cap=None, source_intake=None, store=None, confirm=bridge.CONFIRM,
         clock=None):
    registry, ledger, existing, original_profile, original_envelope = setup
    return bridge.handoff(
        envelope if envelope is not None else original_envelope,
        profile if profile is not None else original_profile,
        source_intake if source_intake is not None else intake(),
        registry, ledger, cap if cap is not None else existing,
        MockProvider,
        store if store is not None else MockStore(original_envelope),
        [{"id": "create.xr-input-triage"}],
        states if states is not None else {"create.xr-input-triage": "approved"},
        confirm=confirm, source_get=gh or GHFixture(),
        token="PRIVATE_TEST_TOKEN", now=NOW,
        clock=clock or (lambda: MS),
    )


def test_reviewed_capsule_lease_and_head_allow_reference_only(setup):
    gh = GHFixture()
    out = call(setup, gh=gh)
    assert out["state"] == "LOCAL_REVIEWED_REFERENCE_CONTEXT_HELD_FOR_WORKER_CONSUMPTION"
    assert out["local_signature_revalidated"] is True
    assert out["same_host_lease_fenced_at_review"] is True
    assert out["independent_source_head_observed_at_review"] is True
    assert out["reference_bundle"]["selected_packs"][0]["trust_level"].startswith(
        "reviewed_reference_data")
    assert len(gh.calls) == 6
    for field in ("agent_identity_authenticated", "remote_worker_authenticated",
                  "tool_permissions_granted", "worker_launched",
                  "execution_authorized", "dispatch_authorized",
                  "merge_authorized", "deployment_authorized",
                  "model_weights_modified"):
        assert out[field] is False
    serialized = json.dumps(out)
    assert "PRIVATE_TEST_TOKEN" not in serialized
    assert setup[2]["token"] not in serialized


def test_bad_signature_prevents_any_github_reads(setup):
    gh = GHFixture()
    broken = dict(setup[4], signature="tampered")
    with pytest.raises(bridge.CapsidHandoffHeld, match="SIGNATURE"):
        call(setup, gh=gh, envelope=broken)
    assert gh.calls == []


def test_revoked_pack_blocks_before_source_observation(setup):
    gh = GHFixture()
    with pytest.raises(bridge.CapsidHandoffHeld, match="PACK_REVOKED"):
        call(setup, gh=gh, states={"create.xr-input-triage": "revoked"})
    assert gh.calls == []


def test_revocation_during_handoff_is_detected_by_fresh_review_read(setup):
    calls = [0]
    def evolving_reviews():
        calls[0] += 1
        return {"create.xr-input-triage": (
            "approved" if calls[0] < 3 else "revoked"
        )}
    with pytest.raises(bridge.CapsidHandoffHeld, match="PACK_REVOKED"):
        call(setup, states=evolving_reviews)
    assert calls[0] >= 3


def test_worker_and_repository_mismatch_hold(setup):
    gh = GHFixture()
    profile = dict(setup[3], agent_id="different")
    with pytest.raises(bridge.CapsidHandoffHeld, match="CAPSID_TARGET_LEASE_MISMATCH"):
        call(setup, profile=profile, gh=gh)
    assert gh.calls == []
    profile = dict(setup[3], repository="MichaelWave369/Other")
    with pytest.raises(bridge.CapsidHandoffHeld):
        call(setup, profile=profile, gh=gh)
    assert gh.calls == []


def test_expired_or_forged_fenced_lease_hold_before_github(setup):
    gh = GHFixture()
    forged = {**setup[2], "token": "forged"}
    with pytest.raises(bridge.CapsidHandoffHeld):
        call(setup, cap=forged, gh=gh)
    with pytest.raises(bridge.CapsidHandoffHeld):
        call(setup, gh=gh, clock=lambda: MS + 300_001)
    assert gh.calls == []


def test_head_moved_or_archived_repo_holds(setup):
    for gh in (GHFixture(sha="f" * 40),
               GHFixture(archived=True),
               GHFixture(change_after=2)):
        with pytest.raises(bridge.CapsidHandoffHeld):
            call(setup, gh=gh)
        assert gh.calls


def test_active_capsule_mismatch_holds(setup):
    store = MockStore(setup[4])
    store.tamper = True
    with pytest.raises(bridge.CapsidHandoffHeld, match="ACTIVE_CAPSULE"):
        call(setup, store=store)


def test_without_operator_confirmation_refuses_before_io(setup):
    gh = GHFixture()
    with pytest.raises(bridge.CapsidHandoffHeld, match="EXPLICIT_CAPSID_CONFIRMATION"):
        call(setup, confirm="MERGE_ALL", gh=gh)
    assert gh.calls == []


def test_non_reference_capability_refuses_before_io(setup):
    gh = GHFixture()
    envelope = {"manifest": {
        **setup[4]["manifest"], "capabilities": ["shell.execute"]
    }, "signature": "valid-local-fixture"}
    with pytest.raises(bridge.CapsidHandoffHeld, match="CONTEXT_ONLY"):
        call(setup, envelope=envelope, gh=gh)
    assert gh.calls == []


def test_invalid_local_provider_availability_fails_closed(monkeypatch):
    def missing(_):
        raise ImportError("no module")
    import builtins
    real = builtins.__import__
    def intercept(name, *args, **kwargs):
        if name == "phireponerve":
            return missing(name)
        return real(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", intercept)
    with pytest.raises(bridge.CapsidHandoffHeld, match="PHIREPONERVE_NOT_INSTALLED"):
        bridge._provider()
