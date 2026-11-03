"""Fleet R0.7: corroborate a downloaded R0.6 pilot ZIP with GitHub Actions.

READ-ONLY. Trust the GitHub API's run and artifact metadata, not an arbitrary
operator-provided JSON file. Require the artifact's SHA-256 digest, fixed
workflow identity, exact source SHA, and internally consistent step receipts.
No API writes, command execution, dispatch, or merge authorization.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import zipfile

import fleet_r05_source_observe as source
import fleet_r06_pilot as pilot

SCHEMA = "agentora.fleet.pilot-evidence-review.v0.7"
AGENTORA = "MichaelWave369/Agentora"
AGENTORA_ID = 1167870912
WORKFLOW_PATH = ".github/workflows/fleet-r06-phimada-pilot.yml"
PILOT_REPO = pilot.REPOSITORY
ARTIFACT_PREFIX = "fleet-r06-phimada-"
MAX_ARCHIVE_BYTES = 2_000_000
MAX_ENTRY_BYTES = 32_000
MAX_TOTAL_UNCOMPRESSED = 96_000
MAX_ARTIFACT_LIST = 100
MAX_RUN_AGE = timedelta(days=8)
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
SHA64 = re.compile(r"[a-f0-9]{64}\Z")
RUN_ID = re.compile(r"[0-9]{1,20}\Z")
ALLOWED_ENTRIES = frozenset(("preflight.json", "steps.json", "final.json"))


class ReviewHeld(Exception):
    """Failed trust boundary; no verification claim may be emitted."""


def require(condition, code):
    if not condition:
        raise ReviewHeld(code)


def fixed_github_get(path, token=None):
    """Only known, bounded read-only Actions API paths."""
    require(isinstance(path, str) and
            path.startswith("/repos/" + AGENTORA + "/actions/runs/") and
            re.fullmatch(r"/repos/MichaelWave369/Agentora/actions/runs/[0-9]{1,20}(?:/artifacts\?per_page=100)?", path) is not None,
            "UNSAFE_GITHUB_ENDPOINT")
    try:
        return source.github_get(path, token)
    except source.ObservationHeld as exc:
        raise ReviewHeld("GITHUB_API_" + str(exc)) from None


def read_archive(raw):
    """Read only three expected small JSON files, without extracting anything."""
    require(isinstance(raw, bytes) and 0 < len(raw) <= MAX_ARCHIVE_BYTES,
            "ARCHIVE_INVALID_OR_TOO_LARGE")
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw), mode="r")
        with archive:
            seen = {}
            total = 0
            for member in archive.infolist():
                # A ZIP from GitHub can contain a pilot-control/ directory or
                # place files at archive root, but cannot introduce other paths.
                if member.is_dir():
                    require(member.filename in ("pilot-control/",),
                            "UNEXPECTED_DIRECTORY")
                    continue
                name = member.filename
                if name.startswith("pilot-control/"):
                    name = name[len("pilot-control/"):]
                require(name in ALLOWED_ENTRIES and name not in seen,
                        "UNEXPECTED_OR_DUPLICATE_ENTRY")
                require(member.file_size <= MAX_ENTRY_BYTES and
                        member.compress_size <= MAX_ARCHIVE_BYTES and
                        (member.flag_bits & 1) == 0,
                        "UNSAFE_ARCHIVE_ENTRY")
                # Reject Unix symlinks, devices, sockets and other nonregular
                # types. Some ZIPs have no Unix mode at all.
                mode = member.external_attr >> 16
                file_type = mode & 0o170000
                require(file_type in (0, 0o100000), "NONREGULAR_ARCHIVE_ENTRY")
                total += member.file_size
                require(total <= MAX_TOTAL_UNCOMPRESSED, "ZIP_UNCOMPRESSED_LIMIT")
                data = archive.read(member)
                require(len(data) <= MAX_ENTRY_BYTES, "ZIP_UNCOMPRESSED_LIMIT")
                try:
                    value = json.loads(data.decode("utf-8"))
                except (UnicodeError, ValueError):
                    raise ReviewHeld("ARCHIVE_JSON_INVALID") from None
                require(isinstance(value, dict), "ARCHIVE_OBJECT_REQUIRED")
                seen[name] = value
            require(set(seen) == ALLOWED_ENTRIES, "INCOMPLETE_PILOT_ARTIFACT")
            return seen
    except (zipfile.BadZipFile, RuntimeError, OSError, EOFError):
        raise ReviewHeld("ARCHIVE_UNREADABLE") from None


def _timestamp(value, now):
    require(isinstance(value, str) and len(value) <= 64,
            "TIMESTAMP_INVALID")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ReviewHeld("TIMESTAMP_INVALID") from None
    require(dt.tzinfo is not None, "TIMESTAMP_UNZONED")
    return dt.astimezone(timezone.utc)


def _run(run, run_id, now):
    require(isinstance(run, dict) and type(run.get("id")) is int and
            run["id"] == run_id and run.get("event") == "workflow_dispatch" and
            run.get("path") == WORKFLOW_PATH and
            run.get("status") == "completed" and run.get("conclusion") == "success" and
            type(run.get("run_attempt")) is int and run["run_attempt"] == 1,
            "RUN_NOT_TRUSTED_OR_INCOMPLETE")
    repository = run.get("repository")
    require(isinstance(repository, dict) and
            repository.get("id") == AGENTORA_ID and
            repository.get("full_name") == AGENTORA and
            run.get("head_repository") is not None and
            isinstance(run["head_repository"], dict) and
            run["head_repository"].get("full_name") == AGENTORA and
            isinstance(run.get("head_sha"), str) and
            SHA40.fullmatch(run["head_sha"]) is not None,
            "RUN_REPOSITORY_OR_SHA_INVALID")
    started = _timestamp(run.get("created_at"), now)
    require(now >= started - timedelta(minutes=5) and now - started <= MAX_RUN_AGE,
            "RUN_TOO_OLD_OR_FROM_FUTURE")
    return run["head_sha"]


def _artifact(record, run_id, raw):
    require(isinstance(record, dict) and
            type(record.get("id")) is int and record["id"] > 0 and
            record.get("name") == ARTIFACT_PREFIX + str(run_id) and
            record.get("expired") is False and
            type(record.get("size_in_bytes")) is int and
            record["size_in_bytes"] > 0 and
            record["size_in_bytes"] <= MAX_ARCHIVE_BYTES,
            "ARTIFACT_METADATA_INVALID")
    workflow_run = record.get("workflow_run")
    if workflow_run is not None:
        require(isinstance(workflow_run, dict) and
                workflow_run.get("id") == run_id,
                "ARTIFACT_WRONG_RUN")
    digest = record.get("digest")
    require(isinstance(digest, str) and digest.startswith("sha256:") and
            SHA64.fullmatch(digest[7:]) is not None,
            "GITHUB_ARTIFACT_DIGEST_MISSING")
    require(hashlib.sha256(raw).hexdigest() == digest[7:],
            "ARTIFACT_DIGEST_MISMATCH")
    return record["id"], digest


def _pilot_payload(files, run_id, now):
    pre, steps, final = (files[key] for key in
                         ("preflight.json", "steps.json", "final.json"))
    require(pre.get("schema") == pilot.PREFLIGHT_SCHEMA and
            pre.get("phase") == "PREFLIGHT" and
            pre.get("scope") == "FIXED_PHI_MADA_NODE_TEST_AND_VITE_BUILD_ONLY" and
            pre.get("state") == "SOURCE_HEAD_MATCH_OBSERVED" and
            pre.get("identity_match") is True and pre.get("head_match") is True and
            pre.get("manual_trigger_required") is True and
            pre.get("code_executed") is False and
            pre.get("checks_run") == 0 and
            pre.get("merge_authorized") is False and
            pre.get("verified_complete") is False and
            pre.get("product_verified") is False,
            "PREFLIGHT_UNTRUSTED")
    require(pre.get("repository") == PILOT_REPO and
            pre.get("repository_id") == pilot.REPOSITORY_ID and
            pre.get("default_branch") == pilot.BRANCH,
            "PREFLIGHT_REPOSITORY_INVALID")
    sha = pre.get("requested_sha")
    require(isinstance(sha, str) and SHA40.fullmatch(sha) is not None and
            pre.get("first_observed_sha") == sha and
            pre.get("last_observed_sha") == sha,
            "PREFLIGHT_SHA_MISMATCH")
    for attr in ("observed_utc",):
        _timestamp(pre.get(attr), now)
    require(set(steps) == {"checkout_sha", "install_exit", "test_exit", "build_exit"} and
            steps["checkout_sha"] == sha and
            all(type(steps[key]) is int and steps[key] == 0
                for key in ("install_exit", "test_exit", "build_exit")),
            "FIXED_CHECK_RESULTS_INVALID")
    require(final.get("schema") == pilot.RECEIPT_SCHEMA and
            final.get("state") == "AUTOMATED_CHECKS_PASSED_AT_OBSERVED_SHA" and
            final.get("automated_checks_passed") is True and
            final.get("repository") == PILOT_REPO and
            final.get("repository_id") == pilot.REPOSITORY_ID and
            final.get("source_sha") == sha and final.get("checkout_sha") == sha and
            final.get("preflight_observed_utc") == pre.get("observed_utc") and
            final.get("workflow_run_id") == str(run_id) and
            final.get("manual_checks") == "NOT_RUN" and
            final.get("installed_with_lifecycle_scripts_disabled") is True,
            "FINAL_RECEIPT_INVALID")
    post = final.get("postflight")
    require(isinstance(post, dict) and
            post.get("repository") == PILOT_REPO and
            post.get("repository_id") == pilot.REPOSITORY_ID and
            post.get("requested_sha") == sha and
            post.get("first_observed_sha") == sha and
            post.get("last_observed_sha") == sha and
            post.get("identity_match") is True and
            post.get("head_match") is True and
            post.get("state") == "SOURCE_HEAD_MATCH_OBSERVED",
            "POSTFLIGHT_SHA_MISMATCH")
    finished = _timestamp(post.get("observed_utc"), now)
    started = _timestamp(pre.get("observed_utc"), now)
    require(started <= finished <= now + timedelta(minutes=5) and
            now - started <= MAX_RUN_AGE, "SOURCE_OBSERVATIONS_INCONSISTENT")
    checks = final.get("checks")
    require(isinstance(checks, dict) and
            set(checks) == {"dependency_install", "node_tests", "vite_build"} and
            all(isinstance(checks[name], dict) and
                checks[name].get("exit_code") == 0 and
                type(checks[name].get("exit_code")) is int and
                checks[name].get("passed") is True for name in checks),
            "RECEIPT_CHECKS_INVALID")
    for flag in ("release_verified", "production_browser_verified",
                 "product_verified", "verified_complete", "merge_authorized",
                 "job_dispatch_authorized", "future_head_stability_guaranteed",
                 "receipt_is_cryptographically_signed"):
        require(final.get(flag) is False, "UNTRUSTED_AUTHORITY_CLAIM")
    return sha, started, finished


def review(run_id, zip_bytes, github_get=fixed_github_get, token=None,
           clock=None):
    require(type(run_id) is int and 0 < run_id < 10**20, "RUN_ID_INVALID")
    require(callable(github_get), "GITHUB_GET_INVALID")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    require(isinstance(now, datetime) and now.tzinfo is not None, "CLOCK_INVALID")
    now = now.astimezone(timezone.utc)
    base = "/repos/" + AGENTORA + "/actions/runs/" + str(run_id)
    run = github_get(base, token)
    agentora_sha = _run(run, run_id, now)
    artifacts = github_get(base + "/artifacts?per_page=100", token)
    require(isinstance(artifacts, dict) and
            type(artifacts.get("total_count")) is int and
            0 < artifacts["total_count"] <= MAX_ARTIFACT_LIST and
            isinstance(artifacts.get("artifacts"), list) and
            len(artifacts["artifacts"]) == artifacts["total_count"],
            "ARTIFACT_CATALOG_INCOMPLETE")
    matching = [x for x in artifacts["artifacts"] if
                isinstance(x, dict) and
                x.get("name") == ARTIFACT_PREFIX + str(run_id)]
    require(len(matching) == 1, "PILOT_ARTIFACT_MISSING_OR_AMBIGUOUS")
    artifact_id, digest = _artifact(matching[0], run_id, zip_bytes)
    files = read_archive(zip_bytes)
    pilot_sha, pre_time, post_time = _pilot_payload(files, run_id, now)
    return {
        "schema": SCHEMA,
        "state": "GITHUB_PILOT_ARTIFACT_DIGEST_CORRELATED",
        "reviewed_utc": now.isoformat(),
        "source": "GITHUB_ACTIONS_REST_AND_SHA256_ARCHIVE",
        "github_workflow_run": {
            "repository": AGENTORA, "run_id": run_id,
            "run_attempt": 1, "event": "workflow_dispatch",
            "workflow_path": WORKFLOW_PATH,
            "agentora_head_sha": agentora_sha,
            "url": "https://github.com/" + AGENTORA + "/actions/runs/" + str(run_id)
        },
        "artifact": {
            "id": artifact_id, "name": ARTIFACT_PREFIX + str(run_id),
            "sha256": digest[7:], "bytes": len(zip_bytes),
            "github_digest_matched": True
        },
        "pilot_repository": PILOT_REPO,
        "pilot_repository_id": pilot.REPOSITORY_ID,
        "pilot_source_sha": pilot_sha,
        "preflight_observed_utc": pre_time.isoformat(),
        "postflight_observed_utc": post_time.isoformat(),
        "observed_fixed_checks": {
            "dependency_install": "EXIT_0_REPORTED_BY_PILOT",
            "node_tests": "EXIT_0_REPORTED_BY_PILOT",
            "vite_build": "EXIT_0_REPORTED_BY_PILOT"
        },
        "scope": "ONE_MANUALLY_TRIGGERED_PHI_MADA_SHA_ONLY",
        "artifact_integrity_correlated": True,
        "workflow_success_observed": True,
        "signed_attestation": False,
        "independent_reproduction_performed": False,
        "current_pilot_head_rechecked": False,
        "runtime_browser_verified": False,
        "product_verified": False,
        "verified_complete": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "operator_review_required": True,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", required=True)
    p.add_argument("--artifact-zip", required=True, type=Path)
    p.add_argument("--output", required=True, type=Path)
    args = p.parse_args(argv)
    try:
        require(RUN_ID.fullmatch(args.run_id) is not None and
                int(args.run_id) > 0, "RUN_ID_INVALID")
        artifact = args.artifact_zip
        require(artifact.is_file() and not artifact.is_symlink() and
                0 < artifact.stat().st_size <= MAX_ARCHIVE_BYTES,
                "ARTIFACT_ZIP_INVALID")
        raw = artifact.read_bytes()
        require(len(raw) <= MAX_ARCHIVE_BYTES, "ARTIFACT_ZIP_TOO_LARGE")
        result = review(int(args.run_id), raw, token=os.environ.get("GITHUB_TOKEN"))
        output = args.output
        output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(not output.exists() and not output.is_symlink(), "OUTPUT_EXISTS")
        payload = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(output, flags, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        print(json.dumps({"state": result["state"],
                          "run_id": result["github_workflow_run"]["run_id"],
                          "pilot_source_sha": result["pilot_source_sha"],
                          "merge_authorized": False,
                          "product_verified": False}, sort_keys=True))
        return 0
    except (ReviewHeld, OSError, ValueError) as exc:
        print("FLEET_R07_HELD " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
