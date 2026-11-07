"""Fleet R4: independently correlate one *existing* sandboxed pilot with a local steward lease.

The R0.6 GitHub workflow executes fixed, operator-triggered PhiMadaPrime
tests/builds. R0.7 checks GitHub-hosted artifacts. This R4 bridge checks those
results against R2 stewardship, R0.4 fencing and R0.5 live source HEAD.

No subprocess, workflow dispatch, GitHub write, agent execution, production
deployment, completion certification or merge authority is introduced here.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))
from app.services.fleet_stewards import StewardRegistry, StewardHeld
import fleet_r04_leases as leases
import fleet_r05_source_observe as source
import fleet_r06_pilot as pilot
import fleet_r07_evidence_review as evidence
import fleet_r3_steward_claim as claim_bridge

SCHEMA = "agentora.fleet.steward-evidence-correlation.v0.4"
CONFIRM = "REVIEW_PHI_MADA_EVIDENCE"
HEX64 = re.compile(r"[0-9a-f]{64}\Z")


class CorrelationHeld(ValueError):
    """Missing or unverifiable evidence does not become a success assertion."""


def require(value, code):
    if not value:
        raise CorrelationHeld(code)


def _stamp(value):
    require(type(value) is str and len(value) <= 64, "TIMESTAMP_INVALID")
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise CorrelationHeld("TIMESTAMP_INVALID") from None
    require(ts.tzinfo is not None, "TIMESTAMP_ZONE_REQUIRED")
    return int(ts.timestamp() * 1000)


def _owned(ledger, capability, now_ms):
    try:
        with ledger._connection() as db:
            row = ledger._check_owned(db, capability, now_ms)
            return dict(row)
    except leases.LeaseHeld as exc:
        raise CorrelationHeld("LEASE_NOT_CURRENT_" + str(exc)) from None


def _reviewed_receipt(result, intake, capability, run_id, lease_row, now_ms):
    """Validate a fresh R0.7 read of GitHub's SHA-256-correlated run artifact."""
    require(type(result) is dict and result.get("schema") == evidence.SCHEMA
            and result.get("state") == "GITHUB_PILOT_ARTIFACT_DIGEST_CORRELATED",
            "GITHUB_EVIDENCE_UNTRUSTED")
    require(result.get("source") == "GITHUB_ACTIONS_REST_AND_SHA256_ARCHIVE"
            and result.get("pilot_repository") == pilot.REPOSITORY
            and result.get("pilot_repository_id") == pilot.REPOSITORY_ID
            and result.get("pilot_source_sha") == intake["source_sha"],
            "PILOT_SOURCE_MISMATCH")
    run = result.get("github_workflow_run")
    require(type(run) is dict and run.get("repository") == evidence.AGENTORA
            and run.get("run_id") == run_id and run.get("run_attempt") == 1
            and run.get("event") == "workflow_dispatch"
            and run.get("workflow_path") == evidence.WORKFLOW_PATH,
            "GITHUB_RUN_IDENTITY_INVALID")
    artifact = result.get("artifact")
    require(type(artifact) is dict and type(artifact.get("id")) is int
            and artifact["id"] > 0 and artifact.get("github_digest_matched") is True
            and type(artifact.get("sha256")) is str
            and HEX64.fullmatch(artifact["sha256"]) is not None,
            "ARTIFACT_PROVENANCE_INVALID")
    require(result.get("observed_fixed_checks") == {
        "dependency_install": "EXIT_0_REPORTED_BY_PILOT",
        "node_tests": "EXIT_0_REPORTED_BY_PILOT",
        "vite_build": "EXIT_0_REPORTED_BY_PILOT",
    } and result.get("artifact_integrity_correlated") is True
            and result.get("workflow_success_observed") is True
            and result.get("scope") == "ONE_MANUALLY_TRIGGERED_PHI_MADA_SHA_ONLY",
            "FIXED_CHECKS_NOT_CORROBORATED")
    for flag in ("signed_attestation", "independent_reproduction_performed",
                 "current_pilot_head_rechecked", "runtime_browser_verified",
                 "product_verified", "verified_complete", "dispatch_authorized",
                 "merge_authorized"):
        require(result.get(flag) is False, "FORGED_VERIFICATION_AUTHORITY")
    require(result.get("operator_review_required") is True,
            "REVIEW_REQUIRED_FLAG_MISSING")
    pre = _stamp(result.get("preflight_observed_utc"))
    post = _stamp(result.get("postflight_observed_utc"))
    # Correlation of an earlier result with a later reservation is forbidden.
    # This is only temporal consistency, NOT a GitHub-runner lease attestation.
    require(lease_row["created_ms"] <= pre <= post <= lease_row["expires_ms"]
            and post <= now_ms + 300000,
            "PILOT_RUN_OUTSIDE_LOCAL_LEASE_WINDOW")
    return artifact["id"], artifact["sha256"], pre, post


def correlate(registry, ledger, intake, capability, run_id, archive_bytes, *,
              confirmation, now=None, clock_ms=None,
              github_get=evidence.fixed_github_get,
              source_get=source.github_get, token=None):
    """Use GitHub GET and the existing fixed sandbox pilot's independent R0.7 review.

    The local lease is checked before and after both network reads. No action
    is enabled by the returned observation.
    """
    require(confirmation == CONFIRM, "EXPLICIT_OPERATOR_REVIEW_REQUIRED")
    require(type(run_id) is int and 0 < run_id < 10**20, "RUN_ID_INVALID")
    require(type(archive_bytes) is bytes
            and 0 < len(archive_bytes) <= evidence.MAX_ARCHIVE_BYTES,
            "PILOT_ARCHIVE_INVALID")
    require(type(intake) is dict and type(capability) is dict,
            "CLAIM_INPUT_INVALID")
    info = leases.validate_intake(intake)
    require(info["repository"] == pilot.REPOSITORY
            and info["repository_id"] == pilot.REPOSITORY_ID
            and intake.get("default_branch") == pilot.BRANCH,
            "ONLY_FIXED_PHI_MADA_PILOT_ALLOWED")
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None, "CLOCK_ZONE_REQUIRED")
    now_ms = int(now.timestamp() * 1000) if clock_ms is None else clock_ms
    require(type(now_ms) is int and now_ms >= 0, "CLOCK_INVALID")
    first = claim_bridge.eligible(registry, intake, now=now)
    row = _owned(ledger, capability, now_ms)
    require(row["repository_id"] == info["repository_id"]
            and row["repository"] == info["repository"]
            and row["source_sha"] == info["source_sha"]
            and row["request_sha256"] == info["request_sha256"],
            "LEASE_SOURCE_MISMATCH")
    # Independently check the *current* repo identity and exact default HEAD.
    def millis():
        return now_ms
    before = source.observe(intake, capability, ledger,
                            get=source_get, token=token, clock=millis)
    require(before["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and before["source_head_observed_match"] is True,
            "CURRENT_HEAD_NOT_VERIFIED_BEFORE_REVIEW")
    # GitHub metadata and artifact SHA256 checked again in R0.7; raw user JSON
    # is never accepted as the provenance of a successful workflow.
    corroborated = evidence.review(run_id, archive_bytes, github_get=github_get,
                                   token=token, clock=lambda: now)
    artifact_id, digest, pre, post = _reviewed_receipt(
        corroborated, intake, capability, run_id, row, now_ms)
    after = source.observe(intake, capability, ledger,
                           get=source_get, token=token, clock=millis)
    require(after["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and after["source_head_observed_match"] is True,
            "CURRENT_HEAD_NOT_VERIFIED_AFTER_REVIEW")
    require(first == claim_bridge.eligible(registry, intake, now=now),
            "STEWARD_CHANGED_DURING_REVIEW")
    _owned(ledger, capability, now_ms)
    return {
        "schema": SCHEMA,
        "state": "SANDBOXED_CHECKS_CORRELATED_WITH_LOCAL_LEASE",
        "repository": pilot.REPOSITORY,
        "repository_id": pilot.REPOSITORY_ID,
        "steward_key": first["steward_key"],
        "source_sha": info["source_sha"],
        "lease_generation": capability["generation"],
        "lease_worker": capability["worker"],
        "source_scan_id": first["source_scan_id"],
        "workflow_run_id": run_id,
        "github_artifact_id": artifact_id,
        "github_artifact_sha256": digest,
        "pilot_preflight_utc": datetime.fromtimestamp(pre / 1000, timezone.utc).isoformat(),
        "pilot_postflight_utc": datetime.fromtimestamp(post / 1000, timezone.utc).isoformat(),
        "reviewed_utc": now.astimezone(timezone.utc).isoformat(),
        "fixed_checks": ["dependency_install", "node_tests", "vite_build"],
        "evidence_provenance": "GITHUB_ACTIONS_METADATA_AND_ARTIFACT_DIGEST",
        "lease_temporally_consistent": True,
        "lease_attested_by_github_runner": False,
        "independent_head_observed_at_review": True,
        "manual_workflow_trigger_required": True,
        "signed_attestation": False,
        "product_verified": False,
        "verified_complete": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--steward-db", required=True, type=Path)
    p.add_argument("--lease-db", required=True, type=Path)
    p.add_argument("--intake", required=True, type=Path)
    p.add_argument("--lease-file", required=True, type=Path)
    p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--artifact-zip", required=True, type=Path)
    p.add_argument("--confirm", required=True)
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args(argv)
    try:
        intake = leases.load_intake(a.intake.expanduser())
        capability = leases.load_capability(a.lease_file.expanduser())
        archive = a.artifact_zip.expanduser()
        require(archive.is_file() and not archive.is_symlink()
                and 0 < archive.stat().st_size <= evidence.MAX_ARCHIVE_BYTES,
                "PILOT_ARCHIVE_FILE_INVALID")
        result = correlate(
            StewardRegistry(a.steward_db), leases.LeaseLedger(a.lease_db),
            intake, capability, a.run_id, archive.read_bytes(),
            confirmation=a.confirm, token=os.environ.get("GITHUB_TOKEN"))
        output = a.output.expanduser()
        output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        require(not output.exists() and not output.is_symlink(), "OUTPUT_EXISTS")
        raw = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("utf-8")
        require(len(raw) <= 16384, "OUTPUT_TOO_LARGE")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(output, flags, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps({"state": result["state"], "run_id": a.run_id,
                          "merge_authorized": False, "product_verified": False}))
        return 0
    except (CorrelationHeld, claim_bridge.HandoffHeld,
            evidence.ReviewHeld, source.ObservationHeld,
            leases.LeaseHeld, StewardHeld, OSError, ValueError) as exc:
        print("FLEET_R4_HELD " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
