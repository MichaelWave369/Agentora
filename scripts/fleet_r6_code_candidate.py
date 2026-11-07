"""Fleet R6: bounded, deterministic code-change *candidate* for PhiMadaPrime.

A fixed single-file repair is proposed against an independently observed
immutable public source SHA. It outputs an inspectable patch, never pushes
a branch, installs an app, merges, or claims full product verification.

This is a controlled code-writing worker pilot, NOT a general generative
coding agent. Untrusted/model-authored proposals are deliberately not admitted.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import fleet_r06_pilot as pilot

SCHEMA = "agentora.fleet.fixed-code-candidate.v0.6"
PREFLIGHT_SCHEMA = "agentora.fleet.code-candidate-preflight.v0.6"
FINAL_SCHEMA = "agentora.fleet.code-candidate-result.v0.6"
CONFIRM = "PROPOSE_PHI_MADA_COPY_FIX"
REPO = pilot.REPOSITORY
REPO_ID = pilot.REPOSITORY_ID
FILE = "src/reponerve.jsx"
BEFORE = "<small>Reserved at display time</small>"
AFTER = "<small>Reserved when imported</small>"
MAX_SOURCE_BYTES = 200000
MAX_JSON_BYTES = 16384
MAX_PATCH_BYTES = 16000
SHA256 = re.compile(r"[a-f0-9]{64}\Z")


class CandidateHeld(ValueError):
    """A change or evidence boundary was not satisfied."""


def require(ok, reason):
    if not ok:
        raise CandidateHeld(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size <= MAX_JSON_BYTES, "JSON_FILE_UNSAFE")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        raise CandidateHeld("JSON_INVALID") from None
    require(type(data) is dict, "JSON_OBJECT_REQUIRED")
    return data


def create_once(path, data):
    target = Path(path)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    require(not target.exists() and not target.is_symlink(),
            "OUTPUT_EXISTS")
    raw = data.encode("utf-8") if type(data) is str else data
    require(type(raw) is bytes and 0 < len(raw) <= MAX_SOURCE_BYTES,
            "OUTPUT_SIZE_INVALID")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def write_json(path, data):
    create_once(path, json.dumps(data, indent=2, sort_keys=True) + "\n")


def run_git(checkout, *args):
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), *args],
            check=True, capture_output=True, text=True, timeout=12,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        raise CandidateHeld("GIT_CHECK_FAILED") from None
    require(len(result.stdout) <= 16000, "GIT_OUTPUT_TOO_LARGE")
    return result.stdout


def validate_checkout(checkout, sha, *, clean):
    require(type(sha) is str and pilot.SHA40.fullmatch(sha) is not None,
            "EXACT_SHA_REQUIRED")
    checkout = Path(checkout)
    require(checkout.is_dir() and not checkout.is_symlink(), "CHECKOUT_UNSAFE")
    root = checkout.resolve()
    require(run_git(root, "rev-parse", "--show-toplevel").strip() == str(root),
            "NOT_CHECKOUT_ROOT")
    require(run_git(root, "rev-parse", "HEAD").strip() == sha,
            "CHECKOUT_SHA_MISMATCH")
    files = run_git(root, "diff", "--name-only", "--no-ext-diff").strip()
    if clean:
        require(files == "" and
                run_git(root, "diff", "--cached", "--name-only").strip() == "",
                "CHECKOUT_NOT_CLEAN")
    else:
        require(files == FILE and
                run_git(root, "diff", "--cached", "--name-only").strip() == "",
                "OUT_OF_SCOPE_TRACKED_CHANGE")
    return root


def _safe_target(root):
    src = root / "src"
    path = root / FILE
    require(src.is_dir() and not src.is_symlink(), "SRC_DIR_UNSAFE")
    require(path.is_file() and not path.is_symlink()
            and path.resolve().is_relative_to(root),
            "TARGET_FILE_UNSAFE")
    require(0 < path.stat().st_size <= MAX_SOURCE_BYTES,
            "SOURCE_FILE_SIZE_INVALID")
    return path


def preflight(sha, confirmation, get=pilot.source.github_get,
              token=None, clock=None):
    require(confirmation == CONFIRM, "MANUAL_MISSION_OPT_IN_REQUIRED")
    require(type(sha) is str and pilot.SHA40.fullmatch(sha) is not None,
            "EXACT_SHA_REQUIRED")
    evidence = pilot.observe_public_head(sha, get=get, token=token, clock=clock)
    require(evidence["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and evidence["head_match"] is True
            and evidence["identity_match"] is True,
            "SOURCE_HEAD_NOT_CURRENT")
    return {
        "schema": PREFLIGHT_SCHEMA,
        "state": "SOURCE_HEAD_MATCH_OBSERVED",
        "repository": REPO, "repository_id": REPO_ID,
        "source_sha": sha, "observed_utc": evidence["observed_utc"],
        "mission": "FIX_LEASE_SNAPSHOT_LABEL_ONLY",
        "file": FILE, "code_executed": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "verified_complete": False,
    }


def validate_preflight(record, sha):
    require(type(record) is dict and
            set(record) == {"schema", "state", "repository",
                            "repository_id", "source_sha", "observed_utc",
                            "mission", "file", "code_executed",
                            "dispatch_authorized", "merge_authorized",
                            "verified_complete"},
            "PREFLIGHT_FIELDS_INVALID")
    require(record["schema"] == PREFLIGHT_SCHEMA
            and record["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and record["repository"] == REPO
            and record["repository_id"] == REPO_ID
            and record["source_sha"] == sha
            and record["mission"] == "FIX_LEASE_SNAPSHOT_LABEL_ONLY"
            and record["file"] == FILE
            and record["code_executed"] is False
            and record["dispatch_authorized"] is False
            and record["merge_authorized"] is False
            and record["verified_complete"] is False,
            "PREFLIGHT_UNTRUSTED")


def create_candidate(checkout, sha, preflight_receipt, *,
                     checkout_checker=validate_checkout):
    validate_preflight(preflight_receipt, sha)
    root = checkout_checker(checkout, sha, clean=True)
    target = _safe_target(root)
    raw = target.read_bytes()
    try:
        before = raw.decode("utf-8")
    except UnicodeError:
        raise CandidateHeld("NOT_UTF8") from None
    require(before.count(BEFORE) == 1 and AFTER not in before,
            "PATCH_ANCHOR_NOT_UNIQUE_OR_ALREADY_FIXED")
    after = before.replace(BEFORE, AFTER, 1)
    patch = "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile="a/" + FILE, tofile="b/" + FILE,
    )).encode("utf-8")
    require(0 < len(patch) <= MAX_PATCH_BYTES, "PATCH_INVALID")
    branch_name = "r6/local-copy-fix-" + sha[:12]
    run_git(root, "switch", "-c", branch_name)
    require(run_git(root, "branch", "--show-current").strip() == branch_name,
            "LOCAL_BRANCH_CREATION_FAILED")
    target.write_bytes(after.encode("utf-8"))
    return patch, {
        "schema": SCHEMA, "state": "BOUNDED_SOURCE_EDIT_PROPOSED",
        "repository": REPO, "repository_id": REPO_ID,
        "source_sha": sha, "mission": "FIX_LEASE_SNAPSHOT_LABEL_ONLY",
        "file": FILE, "candidate_branch": branch_name,
        "patch_sha256": digest(patch),
        "original_sha256": digest(raw),
        "candidate_sha256": digest(after.encode("utf-8")),
        "changed_file_count": 1,
        "source_files_pushed": 0, "pull_requests_created": 0,
        "merge_authorized": False, "verified_complete": False,
    }


def finalize(sha, checkout, preflight_receipt, candidate, patch,
             steps, *, get=pilot.source.github_get,
             token=None, clock=None):
    validate_preflight(preflight_receipt, sha)
    require(type(candidate) is dict and
            set(candidate) == {
                "schema", "state", "repository", "repository_id",
                "source_sha", "mission", "file", "candidate_branch", "patch_sha256",
                "original_sha256", "candidate_sha256", "changed_file_count",
                "source_files_pushed", "pull_requests_created",
                "merge_authorized", "verified_complete",
            }, "CANDIDATE_FIELDS_INVALID")
    require(candidate["schema"] == SCHEMA
            and candidate["state"] == "BOUNDED_SOURCE_EDIT_PROPOSED"
            and candidate["repository"] == REPO
            and candidate["repository_id"] == REPO_ID
            and candidate["source_sha"] == sha
            and candidate["file"] == FILE
            and candidate["candidate_branch"] == "r6/local-copy-fix-" + sha[:12]
            and candidate["mission"] == "FIX_LEASE_SNAPSHOT_LABEL_ONLY"
            and candidate["changed_file_count"] == 1
            and candidate["source_files_pushed"] == 0
            and candidate["pull_requests_created"] == 0
            and candidate["merge_authorized"] is False
            and candidate["verified_complete"] is False,
            "CANDIDATE_CLAIMS_INVALID")
    require(type(patch) is bytes and 0 < len(patch) <= MAX_PATCH_BYTES
            and digest(patch) == candidate["patch_sha256"]
            and bool(SHA256.fullmatch(candidate["candidate_sha256"]))
            and bool(SHA256.fullmatch(candidate["original_sha256"])),
            "PATCH_DIGEST_INVALID")
    root = validate_checkout(checkout, sha, clean=False)
    require(run_git(root, "branch", "--show-current").strip() ==
            candidate["candidate_branch"], "LOCAL_BRANCH_CHANGED")
    target = _safe_target(root)
    require(digest(target.read_bytes()) == candidate["candidate_sha256"]
            and target.read_bytes().count(AFTER.encode("utf-8")) == 1,
            "CANDIDATE_DRIFT")
    # Independently reconstruct exactly the intended patch from Git HEAD.
    original = run_git(root, "show", "HEAD:" + FILE).encode("utf-8")
    require(digest(original) == candidate["original_sha256"],
            "BASE_CONTENT_MISMATCH")
    expected = "".join(difflib.unified_diff(
        original.decode("utf-8").splitlines(keepends=True),
        target.read_text(encoding="utf-8").splitlines(keepends=True),
        fromfile="a/" + FILE, tofile="b/" + FILE,
    )).encode("utf-8")
    require(expected == patch and original.count(BEFORE.encode()) == 1,
            "PATCH_CONTENT_CHANGED")
    require(type(steps) is dict and
            set(steps) == {"checkout_sha", "install_exit", "test_exit", "build_exit"}
            and steps["checkout_sha"] == sha,
            "STEPS_SHAPE_OR_CHECKOUT_INVALID")
    for k in ("install_exit", "test_exit", "build_exit"):
        require(steps[k] is None or
                (type(steps[k]) is int and 0 <= steps[k] <= 255),
                "STEP_EXIT_INVALID")
    post = pilot.observe_public_head(sha, get=get, token=token, clock=clock)
    require(post["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and post["head_match"] is True, "POSTFLIGHT_HEAD_DRIFT")
    passes = all(steps[k] == 0 for k in
                 ("install_exit", "test_exit", "build_exit"))
    state = ("CANDIDATE_AUTOMATED_CHECKS_PASSED_AT_SHA" if passes else
             "CANDIDATE_CHECKS_INCOMPLETE_OR_FAILED")
    return {
        "schema": FINAL_SCHEMA, "state": state,
        "repository": REPO, "repository_id": REPO_ID,
        "source_sha": sha, "file": FILE,
        "candidate_branch": candidate["candidate_branch"],
        "patch_sha256": candidate["patch_sha256"],
        "candidate_sha256": candidate["candidate_sha256"],
        "checkout_sha": steps["checkout_sha"], "checks": {
            "dependency_install": steps["install_exit"],
            "node_tests": steps["test_exit"],
            "vite_build": steps["build_exit"],
        }, "postflight_observed_utc": post["observed_utc"],
        "sandbox": "NETWORK_NONE_READ_ONLY_ROOT_NONROOT_NO_NEW_PRIVILEGES",
        "manual_review_required": True,
        "code_change_proposed": True,
        "source_files_pushed": 0,
        "pull_requests_created": 0,
        "signed_attestation": False, "independent_reproduction_performed": False,
        "release_verified": False, "product_verified": False,
        "verified_complete": False, "merge_authorized": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="phase", required=True)
    pre = sub.add_parser("preflight")
    pre.add_argument("--sha", required=True)
    pre.add_argument("--confirm", required=True)
    pre.add_argument("--output", required=True, type=Path)
    apply = sub.add_parser("apply")
    apply.add_argument("--sha", required=True)
    apply.add_argument("--checkout", required=True, type=Path)
    apply.add_argument("--preflight", required=True, type=Path)
    apply.add_argument("--output-dir", required=True, type=Path)
    fin = sub.add_parser("finalize")
    fin.add_argument("--sha", required=True)
    fin.add_argument("--checkout", required=True, type=Path)
    fin.add_argument("--preflight", required=True, type=Path)
    fin.add_argument("--candidate", required=True, type=Path)
    fin.add_argument("--patch", required=True, type=Path)
    fin.add_argument("--steps", required=True, type=Path)
    fin.add_argument("--output", required=True, type=Path)
    args = p.parse_args(argv)
    try:
        if args.phase == "preflight":
            result = preflight(args.sha, args.confirm,
                               token=os.environ.get("GITHUB_TOKEN"))
            write_json(args.output, result)
        elif args.phase == "apply":
            patch, result = create_candidate(
                args.checkout, args.sha, read_json(args.preflight))
            write_json(args.output_dir / "candidate.json", result)
            create_once(args.output_dir / "patch.diff", patch)
        else:
            patch = args.patch.read_bytes()
            result = finalize(
                args.sha, args.checkout, read_json(args.preflight),
                read_json(args.candidate), patch, read_json(args.steps),
                token=os.environ.get("GITHUB_TOKEN"))
            write_json(args.output, result)
        print(json.dumps({"phase": args.phase,
                          "state": result["state"],
                          "merge_authorized": False}))
        return 0 if result["state"] not in (
            "CANDIDATE_CHECKS_INCOMPLETE_OR_FAILED",) else 2
    except (CandidateHeld, pilot.PilotHeld,
            pilot.source.ObservationHeld, OSError, ValueError) as exc:
        print("FLEET_R6_HELD " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
