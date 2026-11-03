"""Fleet R0.5: independently re-observe public repo identity and exact HEAD.

Uses the R0.4 local lease as a fencing prerequisite. GitHub GET only.
Never executes repository code, checks or builds; never approves or merges.
A matching HEAD is a time-bounded observation, not a permanent guarantee.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, Request, build_opener

import fleet_r04_leases as leases

SCHEMA = "agentora.fleet.source-observation.v0.5"
MAX_RESPONSE_BYTES = 256_000
BRANCH = re.compile(r"[A-Za-z0-9_.\-/]{1,128}\Z")
HEX40 = re.compile(r"[a-f0-9]{40}\Z")


class ObservationHeld(Exception):
    """No independent source observation can grant execution authority."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def require(ok, reason):
    if not ok:
        raise ObservationHeld(reason)


def validate_branch(branch):
    require(isinstance(branch, str) and bool(BRANCH.fullmatch(branch)) and
            not branch.startswith("/") and not branch.endswith("/") and
            "//" not in branch and
            all(part not in ("", ".", "..") for part in branch.split("/")),
            "BRANCH_UNSAFE")
    return branch


def github_get(path, token=None):
    """Single bounded, non-redirecting GitHub REST GET. No untrusted hostnames."""
    require(isinstance(path, str) and
            path.startswith("/repos/" + leases.OWNER + "/") and
            "://" not in path and len(path) <= 360,
            "GITHUB_PATH_INVALID")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agentora-fleet-r05-readonly",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request("https://api.github.com" + path, headers=headers,
                      method="GET")
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            require(response.status == 200, "GITHUB_HTTP_UNEXPECTED")
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        raise ObservationHeld("GITHUB_HTTP_" + str(exc.code)) from None
    except (URLError, TimeoutError, OSError):
        raise ObservationHeld("GITHUB_READ_UNAVAILABLE") from None
    require(len(raw) <= MAX_RESPONSE_BYTES, "GITHUB_RESPONSE_TOO_LARGE")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise ObservationHeld("GITHUB_RESPONSE_INVALID_JSON") from None


def _assert_lease(ledger, capability, info, now_ms):
    require(isinstance(capability, dict) and
            all(capability.get(k) == info[k] for k in
                ("repository", "repository_id", "source_sha", "request_sha256")),
            "LEASE_INTAKE_MISMATCH")
    # Reuse R0.4's token, generation, worker and expiry validation.
    # No network reads occur inside a SQLite transaction.
    with ledger._connection() as db:
        try:
            ledger._check_owned(db, capability, leases.epoch_ms(now_ms))
        except leases.LeaseHeld as exc:
            raise ObservationHeld("LEASE_NOT_CURRENT_" + str(exc)) from None


def _head(get, token, base, branch):
    result = get(base + "/branches/" + quote(branch, safe=""), token)
    require(isinstance(result, dict) and result.get("name") == branch and
            isinstance(result.get("commit"), dict) and
            isinstance(result["commit"].get("sha"), str) and
            bool(HEX40.fullmatch(result["commit"]["sha"])),
            "GITHUB_BRANCH_RESPONSE_INVALID")
    return result["commit"]["sha"]


def _identity(response, info, branch):
    if not isinstance(response, dict):
        raise ObservationHeld("GITHUB_REPOSITORY_RESPONSE_INVALID")
    # All comparisons are exact: renamed, transferred, private or archived
    # repositories are held rather than silently accepted.
    return (type(response.get("id")) is int and
            response["id"] == info["repository_id"] and
            response.get("full_name") == info["repository"] and
            (response.get("owner") or {}).get("login") == leases.OWNER and
            response.get("private") is False and
            response.get("archived") is False and
            response.get("default_branch") == branch)


def observe(intake, capability, ledger, get=github_get, token=None,
            clock=leases.epoch_ms):
    """Return bounded observation receipt. No run/merge permissions are created.

    A successful observation checks the branch twice, then rechecks the local
    lease before returning. It still cannot prevent a later HEAD change.
    """
    info = leases.validate_intake(intake)
    branch = validate_branch(intake.get("default_branch"))
    require(callable(get) and callable(clock), "OBSERVATION_INPUT_INVALID")
    _assert_lease(ledger, capability, info, clock())
    repo_name = info["repository"].split("/", 1)[1]
    base = "/repos/" + leases.OWNER + "/" + quote(repo_name, safe="")
    identity_response = get(base, token)
    identity_ok = _identity(identity_response, info, branch)

    first = second = None
    if identity_ok:
        first = _head(get, token, base, branch)
        second = _head(get, token, base, branch)
    # Fail rather than publish an old worker's apparently good receipt.
    instant = clock()
    _assert_lease(ledger, capability, info, instant)
    match = identity_ok and first == second == info["source_sha"]
    if not identity_ok:
        state = "HELD_REPOSITORY_IDENTITY_CHANGED"
    elif first != second:
        state = "HELD_HEAD_CHANGED_DURING_READS"
    elif second != info["source_sha"]:
        state = "HELD_SOURCE_REVISION_MOVED"
    else:
        state = "SOURCE_HEAD_MATCH_OBSERVED"
    return {
        "schema": SCHEMA,
        "state": state,
        "repository": info["repository"],
        "repository_id": info["repository_id"],
        "default_branch": branch,
        "requested_sha": info["source_sha"],
        "first_observed_sha": first,
        "last_observed_sha": second,
        "request_sha256": info["request_sha256"],
        "observed_utc": datetime.fromtimestamp(instant / 1000, timezone.utc).isoformat(),
        "lease_generation": capability["generation"],
        "lease_worker": capability["worker"],
        "lease_fenced_at_observation": True,
        "repository_identity_observed_match": identity_ok,
        "source_head_observed_match": bool(match),
        "scope": "READ_ONLY_GITHUB_METADATA_AT_OBSERVATION_INSTANT",
        "git_api_reads": 3 if identity_ok else 1,
        "code_executed": False,
        "automated_tests_run": 0,
        "product_verified": False,
        "operator_approved": False,
        "job_dispatch_authorized": False,
        "merge_authorized": False,
        "independent_check_results": "NOT_RUN",
        "future_head_stability_guaranteed": False,
    }


def write_new_receipt(path, result):
    """Write once, no symlink follow or clobber; token is never included."""
    require(isinstance(result, dict) and result.get("schema") == SCHEMA,
            "RECEIPT_INVALID")
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not target.exists() and not target.is_symlink(), "RECEIPT_EXISTS")
    data = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8")
    require(len(data) <= 16384, "RECEIPT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(target, 0o600)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--lease-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        intake = leases.load_intake(args.intake)
        capability = leases.load_capability(args.lease_file)
        ledger = leases.LeaseLedger(args.db)
        result = observe(intake, capability, ledger,
                         token=os.environ.get("GITHUB_TOKEN"))
        write_new_receipt(args.output, result)
        print(json.dumps({"state": result["state"], "repository": result["repository"],
                          "source_head_observed_match": result["source_head_observed_match"],
                          "code_executed": False, "merge_authorized": False},
                         sort_keys=True))
        return 0 if result["state"] == "SOURCE_HEAD_MATCH_OBSERVED" else 2
    except (ObservationHeld, leases.LeaseHeld, OSError, ValueError) as exc:
        print("FLEET_R05_HELD " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
