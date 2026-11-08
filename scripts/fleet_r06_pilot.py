"""Fleet R0.6: explicitly invoked, fixed-scope PhiMada verification pilot.

The corresponding GitHub Actions workflow runs fixed npm checks in network-disabled
Docker containers, never arbitrary imported commands. This module independently
checks public GitHub identity and HEAD before and after the pilot and summarizes
host-recorded check exit codes. It never grants merge or completion authority.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Any

import fleet_r05_source_observe as source

OWNER = "MichaelWave369"
REPOSITORY = "MichaelWave369/PhiMadaPrime"
REPOSITORY_ID = 1443845098
BRANCH = "main"
CONFIRMATION = "RUN_PHI_MADA_TESTS"
PREFLIGHT_SCHEMA = "agentora.fleet.pilot-preflight.v0.6"
RECEIPT_SCHEMA = "agentora.fleet.pilot-check-receipt.v0.6"
SHA40 = re.compile(r"[a-f0-9]{40}\Z")
MAX_FILE_BYTES = 16384
TRACE_SCHEMA = "agentora.fleet.fixed-dispatch-trace.v1"
TRACE_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}\\Z")
CHECK_NAMES = ("install", "node_tests", "vite_build")


class PilotHeld(Exception):
    """Fail closed: the pilot is not a general-purpose executor."""


def require(value: bool, reason: str) -> None:
    if not value:
        raise PilotHeld(reason)


def validate_sha(sha: str) -> str:
    require(isinstance(sha, str) and SHA40.fullmatch(sha) is not None,
            "EXACT_FORTY_CHARACTER_SHA_REQUIRED")
    return sha


def parse_json_file(path: Path) -> dict[str, Any]:
    require(path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= MAX_FILE_BYTES, "FILE_MISSING_OR_UNSAFE")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise PilotHeld("INVALID_JSON") from None
    require(isinstance(obj, dict), "OBJECT_REQUIRED")
    return obj


def observe_public_head(sha: str, get=source.github_get, token=None,
                        clock=None) -> dict[str, Any]:
    """Read fixed repo and branch identity twice; GET only, never checkout."""
    validate_sha(sha)
    clock = clock or (lambda: datetime.now(timezone.utc))
    base = "/repos/" + REPOSITORY
    response = get(base, token)
    require(isinstance(response, dict), "REPO_RESPONSE_INVALID")
    owner = response.get("owner")
    identity = (
        type(response.get("id")) is int and response["id"] == REPOSITORY_ID and
        response.get("full_name") == REPOSITORY and
        isinstance(owner, dict) and owner.get("login") == OWNER and
        response.get("private") is False and
        response.get("archived") is False and
        response.get("default_branch") == BRANCH
    )
    heads = []
    if identity:
        for _ in range(2):
            try:
                heads.append(source._head(get, token, base, BRANCH))
            except source.ObservationHeld as exc:
                raise PilotHeld("BRANCH_RESPONSE_INVALID_" + str(exc)) from None
    if not identity:
        state = "HELD_IDENTITY_MISMATCH"
    elif heads[0] != heads[1]:
        state = "HELD_HEAD_CHANGED_DURING_READS"
    elif heads[1] != sha:
        state = "HELD_REQUESTED_SHA_NOT_CURRENT"
    else:
        state = "SOURCE_HEAD_MATCH_OBSERVED"
    instant = clock()
    require(isinstance(instant, datetime) and instant.tzinfo is not None,
            "CLOCK_INVALID")
    return {
        "state": state, "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "default_branch": BRANCH, "requested_sha": sha,
        "first_observed_sha": heads[0] if heads else None,
        "last_observed_sha": heads[1] if heads else None,
        "identity_match": identity,
        "head_match": state == "SOURCE_HEAD_MATCH_OBSERVED",
        "observed_utc": instant.astimezone(timezone.utc).isoformat(),
        "api_gets": 3 if identity else 1,
    }


def prepare_pilot(sha: str, confirmation: str, get=source.github_get,
                  token=None, clock=None) -> dict[str, Any]:
    require(confirmation == CONFIRMATION, "EXPLICIT_WORKFLOW_OPT_IN_REQUIRED")
    observation = observe_public_head(sha, get=get, token=token, clock=clock)
    return {
        "schema": PREFLIGHT_SCHEMA, "phase": "PREFLIGHT", **observation,
        "scope": "FIXED_PHI_MADA_NODE_TEST_AND_VITE_BUILD_ONLY",
        "manual_trigger_required": True,
        "code_executed": False,
        "checks_run": 0,
        "merge_authorized": False,
        "product_verified": False,
        "verified_complete": False,
    }


def _steps(raw: dict[str, Any] | None, sha: str) -> dict[str, Any]:
    if raw is None:
        return {"checkout_sha": None, "install_exit": None,
                "test_exit": None, "build_exit": None}
    require(isinstance(raw, dict) and set(raw) ==
            {"checkout_sha", "install_exit", "test_exit", "build_exit"},
            "STEPS_FORMAT_INVALID")
    checkout_sha = raw["checkout_sha"]
    require(isinstance(checkout_sha, str) and
            SHA40.fullmatch(checkout_sha) is not None, "CHECKOUT_SHA_INVALID")
    for k in ("install_exit", "test_exit", "build_exit"):
        code = raw[k]
        require(code is None or (type(code) is int and 0 <= code <= 255),
                "STEP_EXIT_CODE_INVALID")
    require(raw["install_exit"] is not None, "INSTALL_EXIT_NOT_RECORDED")
    if raw["install_exit"] != 0:
        require(raw["test_exit"] is None and raw["build_exit"] is None,
                "STEPS_AFTER_FAILED_INSTALL_INVALID")
    return raw


def finalize_pilot(sha: str, preflight: dict[str, Any],
                   steps: dict[str, Any] | None = None,
                   get=source.github_get, token=None, clock=None,
                   workflow_run_id: str | None = None) -> dict[str, Any]:
    validate_sha(sha)
    require(isinstance(preflight, dict) and
            preflight.get("schema") == PREFLIGHT_SCHEMA and
            preflight.get("phase") == "PREFLIGHT" and
            preflight.get("repository") == REPOSITORY and
            preflight.get("repository_id") == REPOSITORY_ID and
            preflight.get("default_branch") == BRANCH and
            preflight.get("requested_sha") == sha and
            preflight.get("head_match") is True and
            preflight.get("identity_match") is True and
            preflight.get("state") == "SOURCE_HEAD_MATCH_OBSERVED" and
            preflight.get("code_executed") is False and
            preflight.get("merge_authorized") is False and
            preflight.get("product_verified") is False and
            preflight.get("verified_complete") is False,
            "PREFLIGHT_DID_NOT_PASS")
    outcomes = _steps(steps, sha)
    # This is a new observation after the checks, not reliance on an old pass.
    postflight = observe_public_head(sha, get=get, token=token, clock=clock)
    matching_checkout = outcomes["checkout_sha"] == sha
    install_ok = outcomes["install_exit"] == 0
    test_ok = outcomes["test_exit"] == 0
    build_ok = outcomes["build_exit"] == 0
    if not postflight["head_match"]:
        state = "HELD_POSTFLIGHT_SOURCE_CHANGED"
    elif not matching_checkout:
        state = "HELD_CHECKOUT_REVISION_MISMATCH_OR_MISSING"
    elif outcomes["install_exit"] is None:
        state = "HELD_NO_EXECUTION_RECORD"
    elif not install_ok:
        state = "FAILED_DEPENDENCY_INSTALL"
    elif outcomes["test_exit"] is None or outcomes["build_exit"] is None:
        state = "HELD_INCOMPLETE_SANDBOX_RESULTS"
    elif not test_ok:
        state = "FAILED_NODE_TESTS"
    elif not build_ok:
        state = "FAILED_VITE_BUILD"
    else:
        state = "AUTOMATED_CHECKS_PASSED_AT_OBSERVED_SHA"
    if workflow_run_id is not None:
        require(isinstance(workflow_run_id, str) and
                re.fullmatch(r"[0-9]{1,20}", workflow_run_id) is not None,
                "WORKFLOW_RUN_ID_INVALID")
    return {
        "schema": RECEIPT_SCHEMA,
        "state": state,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "source_sha": sha,
        "checkout_sha": outcomes["checkout_sha"],
        "preflight_observed_utc": preflight["observed_utc"],
        "postflight": postflight,
        "workflow_run_id": workflow_run_id,
        "runner_type": "GITHUB_HOSTED_EPHEMERAL_UBUNTU",
        "sandbox_type": "DOCKER_NETWORK_NONE_READ_ONLY_ROOT_NONROOT_NO_NEW_PRIVILEGES",
        "installed_with_lifecycle_scripts_disabled": install_ok,
        "checks": {
            "dependency_install": {"exit_code": outcomes["install_exit"],
                                   "passed": install_ok},
            "node_tests": {"exit_code": outcomes["test_exit"],
                           "passed": test_ok},
            "vite_build": {"exit_code": outcomes["build_exit"],
                           "passed": build_ok},
        },
        "automated_checks_passed": state == "AUTOMATED_CHECKS_PASSED_AT_OBSERVED_SHA",
        "manual_checks": "NOT_RUN",
        "release_verified": False,
        "production_browser_verified": False,
        "product_verified": False,
        "verified_complete": False,
        "merge_authorized": False,
        "job_dispatch_authorized": False,
        "future_head_stability_guaranteed": False,
        "receipt_is_cryptographically_signed": False,
    }


def dispatch_trace(sha, request_id, run_id):
    """Inert exact-run correlation marker, not execution authorization."""
    validate_sha(sha)
    require(type(request_id) is str and TRACE_ID.fullmatch(request_id) is not None,
            "TRACE_REQUEST_ID_INVALID")
    require(type(run_id) is str and re.fullmatch(r"[1-9][0-9]{0,19}", run_id) is not None,
            "TRACE_RUN_ID_INVALID")
    return {
        "schema": TRACE_SCHEMA, "request_id": request_id,
        "run_id": int(run_id), "pilot_source_sha": sha,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def write_new(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    require(not path.exists() and not path.is_symlink(), "OUTPUT_ALREADY_EXISTS")
    raw = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8")
    require(len(raw) < MAX_FILE_BYTES, "RECEIPT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":
            os.chmod(path, 0o600)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--sha", required=True)
    pre.add_argument("--confirm", required=True)
    marker = sub.add_parser("marker")
    marker.add_argument("--sha", required=True)
    marker.add_argument("--request-id", required=True)
    post = sub.add_parser("finalize")
    post.add_argument("--sha", required=True)
    post.add_argument("--preflight", required=True, type=Path)
    post.add_argument("--steps", type=Path)
    options = parser.parse_args(argv)
    try:
        token = os.environ.get("GITHUB_TOKEN")
        if options.command == "preflight":
            result = prepare_pilot(options.sha, options.confirm, token=token)
        elif options.command == "marker":
            result = dispatch_trace(options.sha, options.request_id,
                                    os.environ.get("GITHUB_RUN_ID"))
        else:
            prior = parse_json_file(options.preflight)
            steps = parse_json_file(options.steps) if options.steps and options.steps.exists() else None
            result = finalize_pilot(options.sha, prior, steps, token=token,
                                    workflow_run_id=os.environ.get("GITHUB_RUN_ID"))
        write_new(options.output, result)
        print(json.dumps({"state": result.get("state", "TRACE_ONLY"),
                          "repository": REPOSITORY,
                          "merge_authorized": False, "verified_complete": False},
                         sort_keys=True))
        return 0 if options.command == "marker" or result["state"] in (
            "SOURCE_HEAD_MATCH_OBSERVED",
            "AUTOMATED_CHECKS_PASSED_AT_OBSERVED_SHA") else 2
    except (PilotHeld, source.ObservationHeld, OSError, ValueError) as exc:
        print("FLEET_R06_HELD " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
