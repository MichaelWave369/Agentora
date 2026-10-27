"""R0 Development Board: pure, read-only contracts. No execution or merge authority."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("skill_catalog.json")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DENIED_SKILL_KEYS = frozenset({"granted_permissions", "access_token", "api_key", "execution_grant", "allowed_tools", "write_access"})
REQUIRED_RECEIPT = (
    "schema_version", "provenance", "work_item_id", "implementer_id",
    "verifier_id", "commit_sha", "verified_commit_sha",
    "frozen_spec_digest", "verified_spec_digest", "gate_outcome",
    "operator_spec_approved", "evidence",
)
PROVENANCE = frozenset({"SYNTHETIC_FIXTURE", "LOCAL_OBSERVED", "REMOTE_OBSERVED"})


def load_catalog() -> dict[str, Any]:
    """Read packaged metadata only. IDs are design-recovered, not imported skill code."""
    with CATALOG_PATH.open(encoding="utf-8") as stream:
        catalog = json.load(stream)
    problems = validate_catalog(catalog)
    if problems:
        raise ValueError("Invalid Development Board catalog: " + ", ".join(problems))
    return catalog


def validate_catalog(catalog: Any) -> list[str]:
    if not isinstance(catalog, dict) or not isinstance(catalog.get("skills"), list):
        return ["INVALID_CATALOG"]
    skills = catalog["skills"]
    problems: list[str] = []
    if len(skills) != 9:
        problems.append("EXPECTED_NINE_SKILLS")
    if catalog.get("authority_model") != "ROLES_NOT_GRANTS":
        problems.append("CATALOG_CANNOT_GRANT_AUTHORITY")
    if catalog.get("source_status") != "DESIGN_RECOVERED_NOT_SOURCE_IMPORTED":
        problems.append("SOURCE_STATUS_MUST_BE_EXPLICIT")
    if any(not isinstance(skill, dict) for skill in skills):
        problems.append("INVALID_SKILL_RECORD")
        return problems
    ids = [s.get("id") for s in skills]
    legacy = [s.get("legacy_id") for s in skills]
    if any(not isinstance(value, str) or not value.strip() for value in ids + legacy):
        problems.append("MISSING_SKILL_ID")
    if len(set(ids)) != len(ids) or len(set(legacy)) != len(legacy):
        problems.append("DUPLICATE_SKILL_ID")
    for skill in skills:
        if not all(isinstance(skill.get(k), str) and skill[k].strip()
                   for k in ("id", "legacy_id", "name", "stage", "description")):
            problems.append("INCOMPLETE_SKILL")
        if not isinstance(skill.get("requires"), list) or not skill["requires"]:
            problems.append("MISSING_SKILL_EVIDENCE")
        if DENIED_SKILL_KEYS.intersection(skill):
            problems.append("SKILL_AUTHORITY_FORBIDDEN")
    return sorted(set(problems))


def evaluate_receipt(receipt: Any) -> dict[str, Any]:
    """Only evaluates shape/consistency. R0 never authenticates evidence or approvals."""
    reasons: list[str] = []
    if not isinstance(receipt, dict):
        return {
            "receipt_structure_ok": False,
            "status": "REJECTED",
            "eligible_for_merge": False,
            "reasons": ["INVALID_RECEIPT", "R0_HAS_NO_AUTHORITY"],
        }

    def issue(reason: str) -> None:
        if reason not in reasons:
            reasons.append(reason)

    for field in REQUIRED_RECEIPT:
        if field not in receipt:
            issue("MISSING_" + field.upper())

    if receipt.get("schema_version") != "0.1":
        issue("UNSUPPORTED_SCHEMA")
    if receipt.get("provenance") not in PROVENANCE:
        issue("UNKNOWN_PROVENANCE")
    for field in ("work_item_id", "implementer_id", "verifier_id"):
        if not isinstance(receipt.get(field), str) or not receipt[field].strip():
            issue("INVALID_" + field.upper())
    if receipt.get("implementer_id") == receipt.get("verifier_id"):
        issue("SELF_VERIFICATION")

    for field in ("commit_sha", "verified_commit_sha"):
        if not isinstance(receipt.get(field), str) or not HEX40.fullmatch(receipt[field]):
            issue("INVALID_COMMIT_SHA")
    if ("INVALID_COMMIT_SHA" not in reasons and
            receipt["commit_sha"] != receipt["verified_commit_sha"]):
        issue("STALE_OR_MISMATCHED_SHA")

    for field in ("frozen_spec_digest", "verified_spec_digest"):
        if not isinstance(receipt.get(field), str) or not HEX64.fullmatch(receipt[field]):
            issue("INVALID_SPEC_DIGEST")
    if ("INVALID_SPEC_DIGEST" not in reasons and
            receipt["frozen_spec_digest"] != receipt["verified_spec_digest"]):
        issue("CHANGED_SPEC")

    if receipt.get("gate_outcome") != "PASS":
        issue("GATE_NOT_PASSING")
    if receipt.get("operator_spec_approved") is not True:
        issue("SPEC_APPROVAL_MISSING_OR_UNVERIFIED")

    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence or len(evidence) > 30:
        issue("INVALID_EVIDENCE")
    elif any(not isinstance(entry, dict) or
             not all(isinstance(entry.get(k), str) and entry[k].strip()
                     for k in ("kind", "reference"))
             for entry in evidence):
        issue("INVALID_EVIDENCE")

    structure_ok = not reasons
    # Even a structurally valid LOCAL_OBSERVED / REMOTE_OBSERVED claim is unauthenticated.
    if receipt.get("provenance") == "SYNTHETIC_FIXTURE":
        issue("SYNTHETIC_EVIDENCE_NOT_PROOF")
    issue("R0_HAS_NO_AUTHENTICATED_VERIFIER_OR_APPROVAL")
    return {
        "receipt_structure_ok": structure_ok,
        "status": "UNVERIFIED" if structure_ok else "REJECTED",
        "eligible_for_merge": False,
        "reasons": reasons,
    }


def demo_board() -> dict[str, Any]:
    """Clearly fictional display fixture, never drawn from connected repos."""
    sha = "a" * 40
    digest = "b" * 64
    receipt = {
        "schema_version": "0.1",
        "provenance": "SYNTHETIC_FIXTURE",
        "work_item_id": "DEMO-001",
        "implementer_id": "fictional-builder",
        "verifier_id": "fictional-verifier",
        "commit_sha": sha,
        "verified_commit_sha": sha,
        "frozen_spec_digest": digest,
        "verified_spec_digest": digest,
        "gate_outcome": "PASS",
        "operator_spec_approved": True,
        "evidence": [{"kind": "synthetic_test", "reference": "fixture:DEMO-001"}],
    }
    return {
        "mode": "SYNTHETIC_FIXTURE",
        "production_integrations": "NOT_CONNECTED",
        "work_items": [{
            "id": "DEMO-001",
            "title": "Fictional example: accessible navigation",
            "repo": "fictional/example",
            "status": "SUBMITTED_FOR_REVIEW",
            "spec_approval": "SIMULATED_ONLY",
            "submitted_commit_sha": sha,
            "frozen_spec_digest": digest,
            "pending_human_decisions": ["Approve a real specification", "Approve any real merge"],
            "receipt": receipt,
            "receipt_assessment": evaluate_receipt(receipt),
        }],
    }
