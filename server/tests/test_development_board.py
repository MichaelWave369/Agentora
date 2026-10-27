"""Development Board R0 invariant and API tests. No live repo or model calls."""
from copy import deepcopy

from app.services.development_board.contract import (
    demo_board, evaluate_receipt, load_catalog, validate_catalog,
)
from .conftest import make_client


def _receipt():
    return deepcopy(demo_board()["work_items"][0]["receipt"])


def test_exact_nine_role_catalog_is_non_authoritative():
    catalog = load_catalog()
    assert catalog["source_status"] == "DESIGN_RECOVERED_NOT_SOURCE_IMPORTED"
    assert len(catalog["skills"]) == 9
    assert validate_catalog(catalog) == []
    assert all("granted_permissions" not in skill and "allowed_tools" not in skill
               for skill in catalog["skills"])


def test_duplicate_legacy_role_rejected():
    catalog = load_catalog()
    catalog["skills"][1]["legacy_id"] = catalog["skills"][0]["legacy_id"]
    assert "DUPLICATE_SKILL_ID" in validate_catalog(catalog)


def test_skill_cannot_embed_tool_authority():
    catalog = load_catalog()
    catalog["skills"][0]["execution_grant"] = "all"
    assert "SKILL_AUTHORITY_FORBIDDEN" in validate_catalog(catalog)


def test_valid_looking_fixture_is_not_release_eligible():
    result = evaluate_receipt(_receipt())
    assert result["receipt_structure_ok"] is True
    assert result["eligible_for_merge"] is False
    assert "SYNTHETIC_EVIDENCE_NOT_PROOF" in result["reasons"]


def test_self_verification_fails():
    receipt = _receipt()
    receipt["verifier_id"] = receipt["implementer_id"]
    assert "SELF_VERIFICATION" in evaluate_receipt(receipt)["reasons"]


def test_new_commit_invalidates_old_verdict():
    receipt = _receipt()
    receipt["verified_commit_sha"] = "c" * 40
    assert "STALE_OR_MISMATCHED_SHA" in evaluate_receipt(receipt)["reasons"]


def test_changed_approved_spec_invalidates_verdict():
    receipt = _receipt()
    receipt["verified_spec_digest"] = "d" * 64
    assert "CHANGED_SPEC" in evaluate_receipt(receipt)["reasons"]


def test_missing_or_invalid_evidence_fails():
    receipt = _receipt()
    receipt["evidence"] = []
    assert "INVALID_EVIDENCE" in evaluate_receipt(receipt)["reasons"]
    receipt["evidence"] = [{"kind": "test", "reference": ""}]
    assert "INVALID_EVIDENCE" in evaluate_receipt(receipt)["reasons"]


def test_actor_and_gate_validation():
    receipt = _receipt()
    receipt["implementer_id"] = ""
    receipt["gate_outcome"] = "UNKNOWN"
    receipt["operator_spec_approved"] = False
    codes = evaluate_receipt(receipt)["reasons"]
    assert "INVALID_IMPLEMENTER_ID" in codes
    assert "GATE_NOT_PASSING" in codes
    assert "SPEC_APPROVAL_MISSING_OR_UNVERIFIED" in codes


def test_unverified_remote_claim_cannot_become_permission():
    receipt = _receipt()
    receipt["provenance"] = "REMOTE_OBSERVED"
    response = evaluate_receipt(receipt)
    assert response["receipt_structure_ok"] is True
    assert response["status"] == "UNVERIFIED"
    assert response["eligible_for_merge"] is False
    assert "R0_HAS_NO_AUTHENTICATED_VERIFIER_OR_APPROVAL" in response["reasons"]


def test_invalid_payload_fail_closed():
    response = evaluate_receipt(None)
    assert response["status"] == "REJECTED"
    assert response["eligible_for_merge"] is False


def test_api_only_displays_or_evaluates():
    client = make_client()
    skills = client.get("/api/development-board/skills")
    assert skills.status_code == 200
    assert len(skills.json()["skills"]) == 9
    demo = client.get("/api/development-board/demo")
    assert demo.status_code == 200
    assert demo.json()["mode"] == "SYNTHETIC_FIXTURE"
    payload = demo.json()["work_items"][0]["receipt"]
    assessed = client.post("/api/development-board/evaluate", json=payload)
    assert assessed.status_code == 200
    assert assessed.json()["eligible_for_merge"] is False


def test_an_unknown_provenance_is_rejected():
    receipt = _receipt()
    receipt["provenance"] = "TRUST_ME_BRO"
    result = evaluate_receipt(receipt)
    assert result["status"] == "REJECTED"
    assert "UNKNOWN_PROVENANCE" in result["reasons"]
