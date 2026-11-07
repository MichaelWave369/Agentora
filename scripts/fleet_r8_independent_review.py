"""Fleet R8: independently audit ONE R7 Actions artifact before PR handoff.

Verify a successful fixed-scope GitHub Actions run, its SHA-256 artifact
digest, exact R7 receipts, source bytes fetched independently at the pinned
GitHub SHA, and the reproducible model patch. No GitHub mutation is done by
this module; R8 publisher is a separate explicit operator capability.

Artifact contents, including model output and their claims, are untrusted.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import io
import json
import re
import zipfile

import fleet_r05_source_observe as source
import fleet_r06_pilot as pilot
import fleet_r7_model_proposal as r7

SCHEMA = "agentora.fleet.r8-independent-review.v0.8"
AGENTORA = "MichaelWave369/Agentora"
AGENTORA_ID = 1167870912
RUN_WORKFLOW = ".github/workflows/fleet-r7-phimada-model-proposal.yml"
ARTIFACT_PREFIX = "fleet-r7-public-model-candidate-"
MAX_ARCHIVE = 2_000_000
MAX_ENTRIES = 6
MAX_TOTAL = 64_000
MAX_ENTRY = 20_000
MAX_AGE = timedelta(days=8)
NAMES = frozenset((
    "preflight.json", "proposal.json", "candidate.json",
    "patch.diff", "steps.json", "final.json",
))
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
RUN_PATH = re.compile(
    r"/repos/MichaelWave369/Agentora/actions/runs/[0-9]{1,20}"
    r"(?:/artifacts\?per_page=100)?\Z"
)
CONTENT_PATH = re.compile(
    r"/repos/MichaelWave369/PhiMadaPrime/contents/src/reponerve\.jsx"
    r"\?ref=[a-f0-9]{40}\Z"
)
FINAL_KEYS = frozenset((
    "schema", "state", "repository", "repository_id", "source_sha",
    "file", "proposal_sha256", "candidate_sha256", "patch_sha256",
    "candidate_branch", "reported_checks", "postflight_observed_utc",
    "model_output_is_untrusted", "independent_reproduction_performed",
    "manual_code_review_required", "source_files_pushed",
    "pull_requests_created", "release_verified", "product_verified",
    "verified_complete", "dispatch_authorized", "merge_authorized",
))


class ReviewHeld(ValueError):
    """No run verification or publication permission was established."""


def require(ok, reason):
    if not ok:
        raise ReviewHeld(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def fixed_get(path, token=None):
    """Allow only two exact Actions GET shapes and one pinned public file GET."""
    require(type(path) is str and (
        RUN_PATH.fullmatch(path) is not None or
        CONTENT_PATH.fullmatch(path) is not None
    ), "GITHUB_READ_ENDPOINT_REFUSED")
    try:
        return source.github_get(path, token)
    except source.ObservationHeld:
        raise ReviewHeld("GITHUB_READ_HELD") from None


def stamp(value):
    require(type(value) is str and len(value) <= 64, "TIME_INVALID")
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ReviewHeld("TIME_INVALID") from None
    require(instant.tzinfo is not None, "TIME_ZONE_REQUIRED")
    return instant.astimezone(timezone.utc)


def read_zip(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_ARCHIVE,
            "ARCHIVE_SIZE_INVALID")
    found, size = {}, 0
    try:
        with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
            require(len(archive.infolist()) <= MAX_ENTRIES + 1,
                    "ARCHIVE_ENTRY_COUNT_INVALID")
            for member in archive.infolist():
                if member.is_dir():
                    require(member.filename == "r7-review/", "ARCHIVE_DIRECTORY_INVALID")
                    continue
                name = member.filename
                if name.startswith("r7-review/"):
                    name = name[len("r7-review/"):]
                require(name in NAMES and name not in found,
                        "ARCHIVE_UNKNOWN_OR_DUPLICATE_MEMBER")
                require(0 <= member.file_size <= MAX_ENTRY
                        and 0 <= member.compress_size <= MAX_ARCHIVE
                        and not (member.flag_bits & 1),
                        "ARCHIVE_MEMBER_LIMIT")
                kind = (member.external_attr >> 16) & 0o170000
                require(kind in (0, 0o100000), "ARCHIVE_NONREGULAR_ENTRY")
                size += member.file_size
                require(size <= MAX_TOTAL, "ARCHIVE_DECOMPRESSION_LIMIT")
                data = archive.read(member)
                require(len(data) == member.file_size, "ARCHIVE_MEMBER_TRUNCATED")
                found[name] = data
    except (zipfile.BadZipFile, RuntimeError, EOFError, OSError):
        raise ReviewHeld("ARCHIVE_CORRUPT") from None
    require(set(found) == NAMES, "ARCHIVE_INCOMPLETE")
    return found


def parse_json(raw, *, limit=MAX_ENTRY):
    require(type(raw) is bytes and 0 < len(raw) <= limit,
            "JSON_SIZE_INVALID")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=r7._pairs_no_duplicates,
                           parse_constant=lambda _x: (_ for _ in ()).throw(
                               ReviewHeld("JSON_NON_FINITE")))
    except (UnicodeError, ValueError, TypeError):
        raise ReviewHeld("JSON_PARSE_INVALID") from None
    require(type(value) is dict, "JSON_OBJECT_REQUIRED")
    return value


def get_original(source_sha, get, token):
    require(type(source_sha) is str and HEX40.fullmatch(source_sha) is not None,
            "SOURCE_SHA_INVALID")
    response = get(
        "/repos/MichaelWave369/PhiMadaPrime/contents/src/reponerve.jsx"
        "?ref=" + source_sha, token)
    require(type(response) is dict
            and response.get("type") == "file"
            and response.get("path") == r7.FILE
            and response.get("encoding") == "base64"
            and type(response.get("size")) is int
            and 0 < response["size"] <= r7.MAX_SOURCE_BYTES
            and type(response.get("sha")) is str
            and HEX40.fullmatch(response["sha"]) is not None
            and type(response.get("content")) is str,
            "GITHUB_FILE_METADATA_INVALID")
    try:
        original = base64.b64decode(
            "".join(response["content"].split()), validate=True)
    except (ValueError, binascii.Error):
        raise ReviewHeld("GITHUB_FILE_BASE64_INVALID") from None
    require(len(original) == response["size"]
            and hashlib.sha1(
                b"blob " + str(len(original)).encode() + b"\0" + original
            ).hexdigest() == response["sha"],
            "GITHUB_BLOB_IDENTITY_MISMATCH")
    return original, response["sha"]


def _check_run(run, run_id, trusted_agentora_sha, now):
    require(type(run) is dict
            and type(run.get("id")) is int and run["id"] == run_id
            and run.get("event") == "workflow_dispatch"
            and run.get("path") == RUN_WORKFLOW
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and type(run.get("run_attempt")) is int
            and run["run_attempt"] == 1
            and run.get("head_sha") == trusted_agentora_sha
            and type(run.get("repository")) is dict
            and run["repository"].get("id") == AGENTORA_ID
            and run["repository"].get("full_name") == AGENTORA
            and type(run.get("head_repository")) is dict
            and run["head_repository"].get("full_name") == AGENTORA,
            "GITHUB_RUN_IDENTITY_UNTRUSTED")
    created = stamp(run.get("created_at"))
    updated = stamp(run.get("updated_at"))
    require(created <= updated <= now + timedelta(minutes=5)
            and now - created <= MAX_AGE
            and created >= now - MAX_AGE,
            "GITHUB_RUN_AGE_INVALID")
    return created, updated


def _check_artifact(catalog, run_id, raw):
    require(type(catalog) is dict
            and type(catalog.get("total_count")) is int
            and 0 < catalog["total_count"] <= 100
            and type(catalog.get("artifacts")) is list
            and len(catalog["artifacts"]) == catalog["total_count"],
            "GITHUB_ARTIFACT_LIST_INCOMPLETE")
    matching = [a for a in catalog["artifacts"] if
                type(a) is dict and a.get("name") ==
                ARTIFACT_PREFIX + str(run_id)]
    require(len(matching) == 1, "GITHUB_ARTIFACT_MISSING_OR_AMBIGUOUS")
    artifact = matching[0]
    raw_digest = artifact.get("digest")
    require(type(artifact.get("id")) is int and artifact["id"] > 0
            and artifact.get("expired") is False
            and type(artifact.get("size_in_bytes")) is int
            and 0 < artifact["size_in_bytes"] <= MAX_ARCHIVE
            and type(raw_digest) is str
            and raw_digest.startswith("sha256:")
            and HEX64.fullmatch(raw_digest[7:]) is not None
            and digest(raw) == raw_digest[7:],
            "GITHUB_ARTIFACT_DIGEST_INVALID")
    linked = artifact.get("workflow_run")
    require(linked is None or
            (type(linked) is dict and linked.get("id") == run_id),
            "GITHUB_ARTIFACT_WRONG_RUN")
    return artifact["id"], raw_digest[7:]


def _receipt_consistent(files, original, source_sha, created, updated, now):
    pre = parse_json(files["preflight.json"])
    proposal = r7.decode_json(files["proposal.json"])
    candidate = parse_json(files["candidate.json"])
    steps = parse_json(files["steps.json"])
    final = parse_json(files["final.json"])
    r7.validate_preflight(pre, source_sha)
    pre_time = stamp(pre["observed_utc"])
    require(created - timedelta(minutes=5) <= pre_time
            and pre_time <= updated + timedelta(minutes=5),
            "PREFLIGHT_TIME_NOT_RUN_BOUND")
    revised = r7.validate_proposal(proposal, source_sha, original)
    expected_patch = "".join(difflib.unified_diff(
        original.decode("utf-8").splitlines(keepends=True),
        revised.decode("utf-8").splitlines(keepends=True),
        fromfile="a/" + r7.FILE, tofile="b/" + r7.FILE,
    )).encode("utf-8")
    patch = files["patch.diff"]
    require(0 < len(patch) <= r7.MAX_PATCH_BYTES and patch == expected_patch,
            "PATCH_NOT_REPRODUCIBLE")
    prop_hash = digest(r7.canonical(proposal))
    patch_hash = digest(patch)
    candidate_hash = digest(revised)
    local_branch = "r7/proposal-" + source_sha[:12] + "-" + prop_hash[:10]
    require(set(candidate) == r7.CANDIDATE_KEYS
            and candidate["schema"] == r7.CANDIDATE
            and candidate["state"] == "MODEL_SUGGESTION_APPLIED_LOCALLY_FOR_REVIEW"
            and candidate["repository"] == r7.REPO
            and type(candidate["repository_id"]) is int
            and candidate["repository_id"] == r7.REPO_ID
            and candidate["source_sha"] == source_sha
            and candidate["file"] == r7.FILE
            and candidate["mission"] == r7.MISSION
            and candidate["candidate_branch"] == local_branch
            and candidate["proposal_sha256"] == prop_hash
            and candidate["original_sha256"] == digest(original)
            and candidate["candidate_sha256"] == candidate_hash
            and candidate["patch_sha256"] == patch_hash
            and type(candidate["changed_file_count"]) is int
            and candidate["changed_file_count"] == 1
            and type(candidate["source_files_pushed"]) is int
            and candidate["source_files_pushed"] == 0
            and type(candidate["pull_requests_created"]) is int
            and candidate["pull_requests_created"] == 0
            and candidate["merge_authorized"] is False
            and candidate["verified_complete"] is False,
            "CANDIDATE_METADATA_UNTRUSTED")
    expect_steps = {"checkout_sha": source_sha,
                    "install_exit": 0, "test_exit": 0, "build_exit": 0}
    require(steps == expect_steps, "REPORTED_TESTS_NOT_PASSED")
    require(set(final) == FINAL_KEYS
            and final["schema"] == r7.FINAL
            and final["state"] == "FIXED_AUTOMATED_CHECKS_REPORTED_PASSED_AT_SHA"
            and final["repository"] == r7.REPO
            and type(final["repository_id"]) is int
            and final["repository_id"] == r7.REPO_ID
            and final["source_sha"] == source_sha
            and final["file"] == r7.FILE
            and final["candidate_branch"] == local_branch
            and final["proposal_sha256"] == prop_hash
            and final["candidate_sha256"] == candidate_hash
            and final["patch_sha256"] == patch_hash
            and final["reported_checks"] == {
                "install_exit": 0, "test_exit": 0, "build_exit": 0}
            and final["model_output_is_untrusted"] is True
            and final["manual_code_review_required"] is True
            and type(final["source_files_pushed"]) is int
            and final["source_files_pushed"] == 0
            and type(final["pull_requests_created"]) is int
            and final["pull_requests_created"] == 0,
            "FINAL_RECEIPT_UNTRUSTED")
    for flag in ("independent_reproduction_performed",
                 "release_verified", "product_verified", "verified_complete",
                 "dispatch_authorized", "merge_authorized"):
        require(final[flag] is False, "FORGED_FINAL_AUTHORITY")
    post_time = stamp(final["postflight_observed_utc"])
    require(pre_time <= post_time <= updated + timedelta(minutes=5)
            and post_time <= now + timedelta(minutes=5),
            "POSTFLIGHT_TIME_INVALID")
    return revised, patch_hash, prop_hash, candidate_hash


def review(run_id, archive, trusted_agentora_sha, *, get=fixed_get,
           token=None, clock=None):
    """Return review-only metadata plus independently reconstructed source bytes.

    Those bytes are NOT approval to publish; a separate operator action with
    exact patch-digest acknowledgment is needed.
    """
    require(type(run_id) is int and 0 < run_id < 10**20,
            "RUN_ID_INVALID")
    require(type(trusted_agentora_sha) is str
            and HEX40.fullmatch(trusted_agentora_sha) is not None,
            "TRUSTED_AGENTORA_SHA_REQUIRED")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    require(isinstance(now, datetime) and now.tzinfo is not None,
            "CLOCK_INVALID")
    now = now.astimezone(timezone.utc)
    require(type(archive) is bytes and 0 < len(archive) <= MAX_ARCHIVE,
            "ARCHIVE_INVALID")
    path = "/repos/" + AGENTORA + "/actions/runs/" + str(run_id)
    run = get(path, token)
    created, updated = _check_run(run, run_id, trusted_agentora_sha, now)
    artifacts = get(path + "/artifacts?per_page=100", token)
    artifact_id, artifact_digest = _check_artifact(artifacts, run_id, archive)
    files = read_zip(archive)
    proposal = r7.decode_json(files["proposal.json"])
    source_sha = proposal.get("source_sha")
    require(type(source_sha) is str and HEX40.fullmatch(source_sha) is not None,
            "PROPOSAL_SHA_INVALID")
    first = pilot.observe_public_head(source_sha, get=get, token=token,
                                      clock=lambda: now)
    require(first["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and first["head_match"] is True and first["identity_match"] is True,
            "SOURCE_HEAD_NOT_CURRENT")
    original, blob_sha = get_original(source_sha, get, token)
    revised, patch_digest, proposal_digest, candidate_digest = _receipt_consistent(
        files, original, source_sha, created, updated, now)
    second = pilot.observe_public_head(source_sha, get=get, token=token,
                                       clock=lambda: now)
    require(second["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and second["head_match"] is True and second["identity_match"] is True,
            "SOURCE_MOVED_DURING_REVIEW")
    return ({
        "schema": SCHEMA,
        "state": "GITHUB_R7_PATCH_CORROBORATED_REVIEW_REQUIRED",
        "repository": r7.REPO, "repository_id": r7.REPO_ID,
        "source_sha": source_sha, "source_blob_sha": blob_sha,
        "source_file": r7.FILE,
        "controller_sha": trusted_agentora_sha,
        "github_run_id": run_id, "github_artifact_id": artifact_id,
        "github_artifact_sha256": artifact_digest,
        "proposal_sha256": proposal_digest,
        "patch_sha256": patch_digest,
        "candidate_sha256": candidate_digest,
        "fixed_checks_reported_passed": True,
        "github_run_success_observed": True,
        "archive_digest_correlated": True,
        "independent_patch_reconstruction": True,
        "manual_code_review_required": True,
        "signed_attestation": False, "product_verified": False,
        "verified_complete": False, "merge_authorized": False,
        "publication_authorized": False,
    }, revised)
