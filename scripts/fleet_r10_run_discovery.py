"""Read-only GitHub Actions candidate discovery for one already accepted R10 mission.

This is an OPERATOR INFORMATION TOOL, not a dispatcher or evidence verifier.
GitHub's 204 workflow_dispatch response does not contain a run ID. This tool
narrows the candidates using the trusted *local* R9/R10/R5 intent journals and
GitHub-owned run/artifact metadata. Matching times, workflow paths, and even a
GitHub artifact digest are NOT enough to attribute a run to a mission.

To establish correlation, download the actual ZIP and run the existing
R10 evidence-to-QA correlation, which independently checks the exact
request-id marker, run ID, GitHub artifact SHA-256, source and active lease.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))

import fleet_r04_leases as leases
import fleet_r05_source_observe as source
import fleet_r07_evidence_review as r07
import fleet_r9_mission_control as r9
import fleet_r10_mission_evidence as e10
import fleet_r10_r9_r5_bridge as dispatch
import fleet_r5_guarded_dispatch as r5

SCHEMA = "agentora.fleet.r10-readonly-run-discovery.v1"
OWNER = "MichaelWave369/Agentora"
EXPECTED_PATH = r07.WORKFLOW_PATH
MAX_PAGES = 3
PER_PAGE = 100
MAX_CANDIDATES = 20
CLOCK_SKEW = timedelta(minutes=5)
WINDOW = timedelta(days=8)
MAX_RUN_ID = 9223372036854775807


class DiscoveryHeld(ValueError):
    """Untrusted or incomplete GitHub/local evidence must not be attributed."""


def need(ok, reason):
    if not ok:
        raise DiscoveryHeld(reason)


def _utc(value):
    need(isinstance(value, datetime) and value.tzinfo is not None,
         "CLOCK_UNZONED_OR_INVALID")
    return value.astimezone(timezone.utc)


def _timestamp(text):
    need(type(text) is str and len(text) <= 64, "GITHUB_TIME_INVALID")
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise DiscoveryHeld("GITHUB_TIME_INVALID") from None
    return _utc(stamp)


def load_attempt(ledger, mission_id):
    """Read existing one-shot *accepted* journals without requiring live lease.

    An expired local worker lease is allowed for historical discovery, but
    never for subsequent R4/R10 source verification or QA handoff.
    """
    request_id = dispatch._request_id(mission_id)
    with ledger._connection() as db:
        tables = {r["name"] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('r9_missions','r10_r5_dispatch_links','r5_fixed_dispatches')")}
        need(tables == {"r9_missions", "r10_r5_dispatch_links",
                        "r5_fixed_dispatches"}, "MISSION_DISPATCH_JOURNALS_MISSING")
        row = db.execute(
            "SELECT * FROM r9_missions WHERE mission_id=?", (mission_id,)
        ).fetchone()
        need(row is not None and row["kind"] == r9.KIND_TEST and
             row["policy"] == r9.PUBLIC_ALLOWED and
             row["repository"] == r5.pilot.REPOSITORY and
             row["github_id"] == r5.pilot.REPOSITORY_ID and
             type(row["source_sha"]) is str and
             r5.pilot.SHA40.fullmatch(row["source_sha"]) is not None and
             type(row["intake_digest"]) is str and
             r9.DIGEST.fullmatch(row["intake_digest"]) is not None and
             row["worker"] is not None and row["generation"] is not None,
             "MISSION_NOT_FIXED_ASSIGNED_PILOT")
        candidate = {
            "repository_id": row["github_id"], "source_sha": row["source_sha"],
            "intake_digest": row["intake_digest"], "worker": row["worker"],
            "generation": row["generation"]
        }
        try:
            e10._dispatch_link(None, mission_id, candidate, request_id, db=db)
        except e10.EvidenceHeld as exc:
            raise DiscoveryHeld("NO_ACCEPTED_IDENTICAL_R10_R5_DISPATCH") from exc
        dispatched = db.execute(
            "SELECT attempted_ms FROM r10_r5_dispatch_links "
            "WHERE mission_id=?", (mission_id,)
        ).fetchone()
        moment = dispatched["attempted_ms"]
        need(type(moment) is int and 0 <= moment < 10**15,
             "DISPATCH_TIME_INVALID")
        return {
            "mission_id": mission_id, "request_id": request_id,
            "pilot_source_sha": row["source_sha"],
            "attempted_ms": moment,
        }


def _eligible_run(raw, after, now):
    """GitHub-owned coarse run metadata only. NOT evidence of this request."""
    if type(raw) is not dict:
        raise DiscoveryHeld("GITHUB_RUN_SHAPE_INVALID")
    run_id = raw.get("id")
    if type(run_id) is not int or not 0 < run_id <= MAX_RUN_ID:
        raise DiscoveryHeld("GITHUB_RUN_ID_INVALID")
    if (raw.get("event") != "workflow_dispatch" or
        raw.get("path") != EXPECTED_PATH):
        return None
    repo = raw.get("repository")
    head_repo = raw.get("head_repository")
    need(type(repo) is dict and
         repo.get("id") == r07.AGENTORA_ID and
         repo.get("full_name") == OWNER and
         type(head_repo) is dict and
         head_repo.get("full_name") == OWNER and
         type(raw.get("head_sha")) is str and
         r07.SHA40.fullmatch(raw["head_sha"]) is not None,
         "GITHUB_RUN_SOURCE_IDENTITY_INVALID")
    when = _timestamp(raw.get("created_at"))
    if when < after - CLOCK_SKEW or when > now + CLOCK_SKEW or (
            now - when > WINDOW):
        return None
    need(type(raw.get("run_attempt")) is int and
         raw["run_attempt"] >= 1, "GITHUB_RUN_ATTEMPT_INVALID")
    status = raw.get("status")
    conclusion = raw.get("conclusion")
    need(status in ("queued", "in_progress", "completed") and
         conclusion in (None, "success", "failure", "cancelled",
                        "timed_out", "neutral", "skipped", "action_required",
                        "stale"), "GITHUB_RUN_STATUS_INVALID")
    if raw["run_attempt"] != 1:
        return None
    return {"run_id": run_id, "status": status,
            "conclusion": conclusion, "created_at": when.isoformat(),
            "head_sha": raw["head_sha"]}


def _artifact(run_id, list_response):
    need(type(list_response) is dict and
         type(list_response.get("total_count")) is int and
         0 <= list_response["total_count"] <= 100 and
         type(list_response.get("artifacts")) is list and
         len(list_response["artifacts"]) == list_response["total_count"],
         "GITHUB_ARTIFACT_LIST_INCOMPLETE")
    name = r07.ARTIFACT_PREFIX + str(run_id)
    matches = [a for a in list_response["artifacts"] if
               type(a) is dict and a.get("name") == name]
    need(len(matches) <= 1, "DUPLICATE_FIXED_RUN_ARTIFACTS")
    if not matches:
        return None
    a = matches[0]
    digest = a.get("digest")
    linked = a.get("workflow_run")
    need(type(a.get("id")) is int and a["id"] > 0 and
         a.get("expired") is False and
         type(a.get("size_in_bytes")) is int and
         0 < a["size_in_bytes"] <= r07.MAX_ARCHIVE_BYTES and
         type(digest) is str and digest.startswith("sha256:") and
         r07.SHA64.fullmatch(digest[7:]) is not None and
         (linked is None or
          (type(linked) is dict and linked.get("id") == run_id)),
         "GITHUB_ARTIFACT_METADATA_INVALID")
    return {"artifact_id": a["id"], "artifact_name": name,
            "artifact_sha256_claim": digest[7:],
            "archive_bytes_claim": a["size_in_bytes"]}


def discover(ledger, mission_id, *, run_get=source.github_get,
             artifact_get=r07.fixed_github_get, token=None, now=None,
             max_pages=2):
    """List bounded candidates; do not claim any particular run belongs to R10.

    This never downloads or executes remote bytes. Only the existing R0.7/R4
    evidence path may establish run/artifact/request correlation afterward.
    """
    need(type(max_pages) is int and 1 <= max_pages <= MAX_PAGES,
         "PAGE_BUDGET_INVALID")
    need(callable(run_get) and callable(artifact_get),
         "GITHUB_READ_CALLBACK_INVALID")
    now = _utc(now or datetime.now(timezone.utc))
    attempt = load_attempt(ledger, mission_id)
    after = datetime.fromtimestamp(
        attempt["attempted_ms"] / 1000, timezone.utc)
    need(after <= now + CLOCK_SKEW, "DISPATCH_TIMESTAMP_FROM_FUTURE")
    # The existing R0.7 verifier refuses runs older than eight days, and
    # the hosted R0.6 artifacts expire after seven. Do not imply the old
    # journal can still be field-qualified.
    need(now - after <= WINDOW + CLOCK_SKEW, "DISPATCH_TOO_OLD_TO_REVIEW")

    considered = set()
    candidates = []
    scanned = 0
    truncated = False
    for page in range(1, max_pages + 1):
        path = ("/repos/" + OWNER + "/actions/runs?"
                "event=workflow_dispatch&per_page=100&page=" + str(page))
        catalog = run_get(path, token)
        need(type(catalog) is dict and
             type(catalog.get("total_count")) is int and
             0 <= catalog["total_count"] <= 1000000 and
             type(catalog.get("workflow_runs")) is list and
             len(catalog["workflow_runs"]) <= PER_PAGE,
             "GITHUB_RUN_LIST_INVALID")
        runs = catalog["workflow_runs"]
        scanned += len(runs)
        for run in runs:
            item = _eligible_run(run, after, now)
            if item is None:
                continue
            need(item["run_id"] not in considered,
                 "GITHUB_RUN_DUPLICATE_ACROSS_PAGES")
            considered.add(item["run_id"])
            if item["status"] == "completed" and item["conclusion"] == "success":
                artifact_path = ("/repos/" + OWNER + "/actions/runs/"
                                 + str(item["run_id"]) + "/artifacts?per_page=100")
                found = _artifact(item["run_id"], artifact_get(
                    artifact_path, token))
                if found is None:
                    item["state"] = "SUCCESSFUL_RUN_BUT_NO_PILOT_ARTIFACT"
                else:
                    item.update(found)
                    item["state"] = "CANDIDATE_NOT_CORRELATED_NEEDS_ZIP_AND_R07"
            else:
                item["state"] = "RUN_NOT_SUCCESSFULLY_COMPLETED"
            item["run_url"] = (
                "https://github.com/" + OWNER + "/actions/runs/"
                + str(item["run_id"]))
            candidates.append(item)
            if len(candidates) == MAX_CANDIDATES:
                truncated = True
                break
        if truncated:
            break
        if scanned >= catalog["total_count"] or len(runs) < PER_PAGE:
            break
        if page == max_pages:
            truncated = True
    return {"schema": SCHEMA, "state": (
                "CANDIDATES_ONLY_NO_MISSION_ATTRIBUTION" if candidates
                else "NO_CANDIDATE_IN_SCANNED_WINDOW"),
            "mission_id": mission_id, "request_id": attempt["request_id"],
            "pilot_source_sha_claim": attempt["pilot_source_sha"],
            "local_dispatch_attempt_utc": after.isoformat(),
            "searched_pages": page, "scanned_run_records": scanned,
            "truncated": truncated,
            "candidates": candidates,
            "run_artifact_bytes_verified": False,
            "dispatch_origin_authenticated": False,
            "independent_qa_complete": False,
            "verified_complete": False, "merge_authorized": False,
            "dispatch_authorized": False}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--lease-db", type=Path, required=True)
    p.add_argument("--mission-id", required=True)
    p.add_argument("--max-pages", type=int, default=2)
    a = p.parse_args(argv)
    try:
        path = a.lease_db.expanduser()
        need(path.is_file() and not path.is_symlink(),
             "EXISTING_LOCAL_LEDGER_REQUIRED")
        result = discover(leases.LeaseLedger(path), a.mission_id,
                          token=os.environ.get("GITHUB_TOKEN"),
                          max_pages=a.max_pages)
        print(json.dumps(result, indent=2))
        return 0
    except (DiscoveryHeld, e10.EvidenceHeld, dispatch.BridgeHeld,
            source.ObservationHeld, r07.ReviewHeld, leases.LeaseHeld,
            sqlite3.Error, ValueError, OSError) as exc:
        # Never print token, raw response body or private lease capabilities.
        safe = str(exc) if isinstance(exc, (DiscoveryHeld, e10.EvidenceHeld,
            dispatch.BridgeHeld, source.ObservationHeld,
            r07.ReviewHeld, leases.LeaseHeld)) else "LOCAL_LEDGER_OR_INPUT_UNAVAILABLE"
        print("FLEET_R10_DISCOVERY_HELD " + safe, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
