"""Agentora Fleet R0.3: OFFLINE intake of PhiMada verification requests.

This is a validation and lineage receipt only. It does not fetch repository code,
run checks, approve, schedule agents, call GitHub, or grant merge privileges.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

REQUEST_SCHEMA = "phimada.verification-request.v0.8"
INTAKE_SCHEMA = "agentora.fleet.verification-intake.v0.3"
OWNER = "MichaelWave369"
MAX_BYTES = 65536
MAX_AGE = timedelta(hours=24)
MAX_HEAD_AGE_AT_PREPARATION = timedelta(minutes=15)
HEX40 = re.compile(r"^[a-f0-9]{40}$")
NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
BRANCH = re.compile(r"^[A-Za-z0-9_./-]{1,128}$")

# Keep this explicit matrix synchronized with PhiMada src/contracts.mjs.
SURFACE_CHECKS = {
    "web_app": ("production_build", "automated_tests", "browser_interaction",
                "accessibility", "deployed_revision"),
    "webxr": ("production_build", "automated_tests", "browser_interaction",
               "headset_input", "comfort_acceptance"),
    "static_site": ("asset_validation", "navigation", "accessibility",
                    "deployed_revision"),
    "python_package": ("package_build", "automated_tests", "clean_install_import",
                       "versioned_artifact"),
    "node_service": ("production_build", "automated_tests", "api_smoke",
                     "recovery_rollback"),
    "android": ("installable_apk", "automated_tests", "device_smoke",
                "recovery_rollback"),
    "desktop": ("native_build", "automated_tests", "clean_install_launch",
                "recovery_rollback"),
    "os_image": ("reproducible_image", "vm_boot", "recovery_rollback",
                 "hardware_acceptance"),
    "research": ("methodology", "reproducible_results",
                 "negative_controls", "limitations_review"),
    "manual_review": ("scope_and_surface_classification",),
}
MANUAL_OR_DEVICE = frozenset((
    "browser_interaction", "accessibility", "headset_input",
    "comfort_acceptance", "navigation", "clean_install_import",
    "recovery_rollback", "device_smoke", "clean_install_launch",
    "vm_boot", "hardware_acceptance", "methodology",
    "reproducible_results", "negative_controls", "limitations_review",
    "scope_and_surface_classification", "deployed_revision",
    "versioned_artifact"
))
EXPECTED_FIELDS = frozenset((
    "schema", "owner", "repository", "repository_id",
    "default_branch", "source_sha", "source_observed_utc", "prepared_utc",
    "surface_types", "required_checks", "operator_notes_included",
    "operator_review_required", "independent_verification", "execution_state",
    "approved_for_execution", "merge_authorized", "job_dispatch_authorized",
))


class IntakeHeld(Exception):
    """Fail-closed input. Nothing is scheduled or verified."""


def parse_utc(value):
    if not isinstance(value, str) or len(value) > 64:
        raise IntakeHeld("TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise IntakeHeld("TIMESTAMP_INVALID") from None
    if parsed.tzinfo is None:
        raise IntakeHeld("TIMESTAMP_UNZONED")
    return parsed.astimezone(timezone.utc)


def required_checks(types):
    if not isinstance(types, list) or not 1 <= len(types) <= 10:
        raise IntakeHeld("SURFACES_INVALID")
    if any(not isinstance(x, str) or x not in SURFACE_CHECKS for x in types):
        raise IntakeHeld("SURFACE_UNKNOWN")
    if len(types) != len(set(types)):
        raise IntakeHeld("SURFACE_DUPLICATE")
    checks = []
    for kind in types:
        for check in SURFACE_CHECKS[kind]:
            if check not in checks:
                checks.append(check)
    return checks


def accept(raw, now=None):
    """Validate a public single-repo handoff, return a HOLD receipt not a job."""
    now = now or datetime.now(timezone.utc)
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise IntakeHeld("FILE_TOO_LARGE_OR_EMPTY")
    try:
        request = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise IntakeHeld("INVALID_REQUEST_JSON") from None
    if not isinstance(request, dict) or set(request) != EXPECTED_FIELDS:
        raise IntakeHeld("REQUEST_FIELDS_INVALID")
    if request["schema"] != REQUEST_SCHEMA or request["owner"] != OWNER:
        raise IntakeHeld("REQUEST_SCHEMA_OR_OWNER_INVALID")
    name = request["repository"]
    if not isinstance(name, str) or not name.startswith(OWNER + "/"):
        raise IntakeHeld("REPOSITORY_NOT_ALLOWED")
    short = name[len(OWNER) + 1:]
    if not NAME.fullmatch(short) or short in (".", ".."):
        raise IntakeHeld("REPOSITORY_NOT_ALLOWED")
    repo_id = request["repository_id"]
    if not isinstance(repo_id, int) or isinstance(repo_id, bool) or \
            not 0 < repo_id <= 9007199254740991:
        raise IntakeHeld("REPOSITORY_ID_INVALID")
    if not isinstance(request["default_branch"], str) or \
            not BRANCH.fullmatch(request["default_branch"]):
        raise IntakeHeld("BRANCH_INVALID")
    sha = request["source_sha"]
    if not isinstance(sha, str) or not HEX40.fullmatch(sha):
        raise IntakeHeld("IMMUTABLE_SOURCE_REQUIRED")
    observed = parse_utc(request["source_observed_utc"])
    prepared = parse_utc(request["prepared_utc"])
    if prepared - observed > MAX_HEAD_AGE_AT_PREPARATION or \
            observed - prepared > timedelta(minutes=5) or \
            now - prepared > MAX_AGE or prepared - now > timedelta(minutes=5):
        raise IntakeHeld("REQUEST_STALE_OR_HEAD_NOT_FRESH")
    for field, wanted in (
        ("operator_notes_included", False),
        ("operator_review_required", True),
        ("independent_verification", "NOT_RUN"),
        ("execution_state", "NOT_DISPATCHED"),
        ("approved_for_execution", False),
        ("merge_authorized", False),
        ("job_dispatch_authorized", False),
    ):
        if request[field] is not wanted and request[field] != wanted:
            raise IntakeHeld("AUTHORITY_OR_VERIFICATION_CLAIM_REJECTED")
        # Bool/int comparison is not sufficient: reject numeric truthy substitutes.
        if isinstance(wanted, bool) and type(request[field]) is not bool:
            raise IntakeHeld("AUTHORITY_FIELD_TYPE_INVALID")
    check_ids = required_checks(request["surface_types"])
    observed_checks = request["required_checks"]
    if not isinstance(observed_checks, list) or len(observed_checks) != len(check_ids):
        raise IntakeHeld("CHECKLIST_MISMATCH")
    for item, expected_id in zip(observed_checks, check_ids):
        if (not isinstance(item, dict) or set(item) != {"id", "locally_reviewed"} or
            item.get("id") != expected_id or
            type(item.get("locally_reviewed")) is not bool):
            raise IntakeHeld("CHECKLIST_MISMATCH")
    digest = hashlib.sha256(raw).hexdigest()
    checks = [{
        "check_id": item["id"],
        "operator_reviewed_claim": item["locally_reviewed"],
        "lane": "HUMAN_OR_DEVICE_REQUIRED"
        if item["id"] in MANUAL_OR_DEVICE else "AUTOMATION_CANDIDATE_ONLY",
        "verification_state": "NOT_RUN",
        "evidence_receipt": None
    } for item in observed_checks]
    return {
        "schema": INTAKE_SCHEMA,
        "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": OWNER,
        "repository": name,
        "repository_id": repo_id,
        "default_branch": request["default_branch"],
        "source_sha": sha,
        "source_observed_utc": request["source_observed_utc"],
        "prepared_utc": request["prepared_utc"],
        "received_utc": now.isoformat(),
        "request_sha256": digest,
        "digest_is_authentication": False,
        "surface_types": list(request["surface_types"]),
        "checks": checks,
        "head_revalidated_by_agentora": False,
        "independent_checks_run": 0,
        "verified_complete": False,
        "operator_approved": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "next_steps": [
            "Operator reviews requested repo and the acceptance surfaces.",
            "Re-fetch current repository public HEAD and compare exact immutable SHA.",
            "Obtain explicit scoped authorization before any independent check runs.",
            "Run relevant checks in isolated execution with bounded privileges.",
            "Collect per-check, exact-SHA evidence receipts; verify independently.",
            "Use a separate governed review gate for any PR merge decision."
        ]
    }


def consume_file(input_path, output_dir, now=None):
    """Output one review-only receipt only after every check passes."""
    if not input_path.is_file() or input_path.stat().st_size > MAX_BYTES:
        raise IntakeHeld("INPUT_NOT_FOUND_OR_OVERSIZE")
    receipt = accept(input_path.read_bytes(), now=now)
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / "verification-intake.json"
    content = (json.dumps(receipt, sort_keys=True, indent=2) + "\n").encode("utf-8")
    # No untrusted file names or shell commands; replace receipt atomically.
    with tempfile.NamedTemporaryFile(dir=output_dir, prefix=".intake-",
                                     suffix=".tmp", delete=False) as tmp:
        tmp.write(content)
        temporary = Path(tmp.name)
    try:
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        item = consume_file(args.input, args.output_dir)
    except (IntakeHeld, OSError) as exc:
        print("FLEET_R03_HELD " + str(exc), file=sys.stderr)
        return 1
    print("FLEET_R03_REVIEW_ONLY repo=" + item["repository"] +
          " checks=" + str(len(item["checks"])) +
          " independent_runs=0 merged=0 verified_complete=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
