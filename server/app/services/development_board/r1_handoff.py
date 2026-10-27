"""R1-A: review-only cross-check of GitPorch and PhiBot evidence exports.

Nothing here runs workers, invokes models, writes Git, approves PRs or merges.
Input snapshots remain untrusted self-reports even when their fields agree.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

SHA40 = re.compile(r"^[0-9a-f]{40}$")
GITPORCH_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
GITHUB_REPO = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9_.-]{1,100}$")
GITPORCH_HEALTH = "LOCAL_RECEIPTS_CHECKED_NOT_ATTESTED"
MAX_IMPORT_BYTES = 128 * 1024
LOCAL_URL_PATH = "/api/phirunners"


def _bad(*reasons: str) -> dict[str, Any]:
    return {"status": "HELD", "reasons": list(reasons), "source_attested": False}


def inspect_gitporch(snapshot: Any, local_repo: str, commit_sha: str) -> dict[str, Any]:
    """Compare the latest retained per-lane jobs to a requested SHA, without promoting them."""
    if (not isinstance(local_repo, str) or not isinstance(commit_sha, str) or\n            not GITPORCH_REPO.fullmatch(local_repo) or not SHA40.fullmatch(commit_sha)):
        return _bad("INVALID_REPO_OR_SHA")
    if not isinstance(snapshot, dict) or (
        snapshot.get("service"), snapshot.get("version"), snapshot.get("mode")
    ) != ("PhiRunners", "R1-E", "LOCAL_READ_ONLY"):
        return _bad("GITPORCH_SNAPSHOT_UNRECOGNIZED")
    if snapshot.get("health") != GITPORCH_HEALTH:
        return _bad("GITPORCH_SNAPSHOT_UNVERIFIED")
    lanes = snapshot.get("lanes")
    jobs = snapshot.get("jobs")
    if not isinstance(lanes, dict) or not isinstance(jobs, list) or len(jobs) > 20:
        return _bad("GITPORCH_SNAPSHOT_MALFORMED")
    lane_results: dict[str, Any] = {}
    for lane, kind in (("git", "GIT_OBJECT_INTEGRITY"), ("tests", "NODE_BUILTIN_TESTS")):
        meta = lanes.get(lane)
        if (not isinstance(meta, dict) or meta.get("jobType") != kind
                or meta.get("health") != GITPORCH_HEALTH):
            return _bad("GITPORCH_LANE_UNVERIFIED_" + lane.upper())
        matches = [job for job in jobs if isinstance(job, dict)
                   and job.get("lane") == lane and job.get("repo") == local_repo
                   and job.get("commit") == commit_sha]
        if not matches:
            return _bad("MISSING_EXACT_SHA_" + lane.upper() + "_JOB")
        if any(not isinstance(job.get("id"), str) or not job["id"] for job in matches):
            return _bad("INVALID_" + lane.upper() + "_JOB_ID")
        ids = [job["id"] for job in matches]
        if len(set(ids)) != len(ids):
            return _bad("DUPLICATE_" + lane.upper() + "_JOB_ID")
        latest = max(matches, key=lambda job: job["id"])
        if latest.get("status") != "DONE" or latest.get("outcome") != "PASS":
            return _bad(lane.upper() + "_LATEST_JOB_NOT_PASSING")
        lane_results[lane] = {"job_id": latest["id"], "outcome": "PASS", "sha": commit_sha}
    return {
        "status": "LOCAL_REPORTED_PASS_REVIEW_ONLY",
        "reasons": ["CHECKSUMMED_LOCAL_CLAIMS_NOT_ATTESTED"],
        "source_attested": False,
        "lanes": lane_results,
    }


def inspect_phibot(report: Any, github_repo: str, pr_number: int, commit_sha: str) -> dict[str, Any]:
    """Compare PhiBot's GitHub CI observation export to one exact PR/SHA."""
    if (not GITHUB_REPO.fullmatch(github_repo or "") or
            type(pr_number) is not int or not 1 <= pr_number <= 10_000_000 or
            not SHA40.fullmatch(commit_sha or "")):
        return _bad("INVALID_GITHUB_SCOPE")
    if not isinstance(report, dict) or (
        report.get("schema"), report.get("mode")
    ) != ("phibot.repo-verification.v1", "READ_ONLY_NO_PROMOTION"):
        return _bad("PHIBOT_REPORT_UNRECOGNIZED")
    repos = report.get("repositories")
    if not isinstance(repos, list) or not 1 <= len(repos) <= 30:
        return _bad("PHIBOT_REPORT_MALFORMED")
    targeted = [r for r in repos if isinstance(r, dict) and r.get("repository") == github_repo]
    if len(targeted) != 1:
        return _bad("PHIBOT_REPO_MISSING_OR_AMBIGUOUS")
    entry = targeted[0]
    if entry.get("error") or not isinstance(entry.get("candidates"), list):
        return _bad("PHIBOT_REPO_ERROR")
    candidates = entry["candidates"]
    if len(candidates) > 100:
        return _bad("PHIBOT_CANDIDATES_TRUNCATED")
    selected = [c for c in candidates if isinstance(c, dict) and c.get("pr") == pr_number]
    if len(selected) != 1:
        return _bad("PHIBOT_PR_MISSING_OR_AMBIGUOUS")
    candidate = selected[0]
    if candidate.get("headSha") != commit_sha:
        return _bad("PHIBOT_SHA_MISMATCH")
    if (candidate.get("status") != "CHECKS_PASS_REVIEW_ONLY" or
            candidate.get("checkStatus") != "CHECKS_PASS_REVIEW_ONLY"):
        return _bad("PHIBOT_CHECKS_NOT_PASSING")
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 100:
        return _bad("PHIBOT_MISSING_CHECK_EVIDENCE")
    for check in evidence:
        if not isinstance(check, dict) or not isinstance(check.get("name"), str) or not check["name"]:
            return _bad("PHIBOT_MALFORMED_CHECK")
        if check.get("origin") == "check_run":
            if (check.get("status"), check.get("conclusion")) != ("completed", "success"):
                return _bad("PHIBOT_CHECK_NOT_SUCCESS")
        elif check.get("origin") == "commit_status":
            if check.get("status") != "success":
                return _bad("PHIBOT_CHECK_NOT_SUCCESS")
        else:
            return _bad("PHIBOT_UNKNOWN_CHECK_TYPE")
    return {
        "status": "GITHUB_CI_REPORTED_PASS_REVIEW_ONLY",
        "reasons": ["PHIBOT_EXPORT_UNAUTHENTICATED_AND_POSSIBLY_STALE"],
        "source_attested": False,
        "pr": pr_number,
        "sha": commit_sha,
        "observed_at_untrusted": report.get("observedAt"),
        "check_count": len(evidence),
    }


def preview_handoff(payload: Any) -> dict[str, Any]:
    """Never returns a release-granting result, including for two claimed PASS sources."""
    result = {
        "schema": "agentora.development-board.handoff.v1",
        "mode": "REVIEW_ONLY",
        "automatic_merge": False,
        "eligible_for_merge": False,
        "verifier_identity_authenticated": False,
        "operator_approval_authenticated": False,
        "status": "HELD",
    }
    if not isinstance(payload, dict):
        return {**result, "reasons": ["INVALID_HANDOFF"]}
    try:
        if len(json.dumps(payload, ensure_ascii=True)) > MAX_IMPORT_BYTES:
            return {**result, "reasons": ["IMPORT_TOO_LARGE"]}
    except (ValueError, TypeError):
        return {**result, "reasons": ["INVALID_HANDOFF"]}
    local_repo = payload.get("local_repo")
    github_repo = payload.get("github_repo")
    commit_sha = payload.get("commit_sha")
    pr_number = payload.get("pr_number")
    gp = inspect_gitporch(payload.get("gitporch"), local_repo, commit_sha)
    pb = inspect_phibot(payload.get("phibot"), github_repo, pr_number, commit_sha)
    both_pass = (gp["status"] == "LOCAL_REPORTED_PASS_REVIEW_ONLY" and
                 pb["status"] == "GITHUB_CI_REPORTED_PASS_REVIEW_ONLY")
    return {
        **result,
        "status": "REVIEW_READY_NOT_AUTHORIZED" if both_pass else "HELD",
        "local_repo": local_repo if isinstance(local_repo, str) and len(local_repo) <= 100 else None,
        "github_repo": github_repo if isinstance(github_repo, str) and len(github_repo) <= 140 else None,
        "commit_sha": commit_sha if isinstance(commit_sha, str) and SHA40.fullmatch(commit_sha) else None,
        "gitporch": gp,
        "phibot": pb,
        "reasons": ["SOURCE_REPORTS_NOT_INDEPENDENT_ATTESTATIONS", "HUMAN_APPROVAL_REQUIRED"]
        if both_pass else ["MISSING_OR_UNVERIFIED_EXACT_SHA_EVIDENCE"],
    }


def fetch_local_gitporch() -> dict[str, Any]:
    """Operator-click-only, explicitly enabled, loopback-only HTTP GET; no URL input."""
    if os.getenv("AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED", "").lower() not in ("1", "true"):
        return {"connection": "DISABLED", "reason": "SET_AGENTORA_DEVBOARD_GITPORCH_READ_ENABLED_TO_OPT_IN"}
    value = os.getenv("AGENTORA_DEVBOARD_GITPORCH_PORT", "3690")
    if not value.isdecimal() or not 1024 <= int(value) <= 65535:
        return {"connection": "UNAVAILABLE", "reason": "INVALID_GITPORCH_PORT"}
    import requests

    session = requests.Session()
    session.trust_env = False  # Don't send loopback requests through environment proxies.
    try:
        with session.get(
            f"http://127.0.0.1:{int(value)}{LOCAL_URL_PATH}",
            timeout=(1, 3),
            stream=True,
            allow_redirects=False,
            headers={"Accept": "application/json"},
        ) as response:
            if response.status_code != 200:
                return {"connection": "UNAVAILABLE", "reason": "HTTP_STATUS_NOT_OK"}
            if "application/json" not in response.headers.get("Content-Type", "").lower():
                return {"connection": "UNAVAILABLE", "reason": "UNEXPECTED_CONTENT_TYPE"}
            chunks: list[bytes] = []
            size = 0
            for block in response.iter_content(chunk_size=8192):
                size += len(block)
                if size > MAX_IMPORT_BYTES:
                    return {"connection": "UNAVAILABLE", "reason": "RESPONSE_TOO_LARGE"}
                chunks.append(block)
            try:
                parsed = json.loads(b"".join(chunks).decode("utf-8"))
            except (UnicodeError, ValueError):
                return {"connection": "UNAVAILABLE", "reason": "INVALID_JSON"}
    except requests.RequestException:
        return {"connection": "UNAVAILABLE", "reason": "LOCAL_GITPORCH_NOT_RESPONDING"}
    finally:
        session.close()
    if not isinstance(parsed, dict) or parsed.get("service") != "PhiRunners":
        return {"connection": "UNAVAILABLE", "reason": "NOT_PHIRUNNERS"}
    return {"connection": "LOCAL_SELF_REPORTED", "snapshot": parsed}
