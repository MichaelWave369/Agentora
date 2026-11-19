"""Cloud-only public RepoNerve -> existing Agentora R9 admission qualification.

The scan and R9 SQLite files are ephemeral for this PRE-PERSISTENCE pilot.
No workflow dispatch, owner approval, PR write, or merge. Do not mistake
replay inside one runner for cross-run durable state.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib import parse, request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))

from app.integrations.phireponerve_client import (
    collect_public_observations, RepoNerveUnavailable, EVENT_PAGE_SIZE,
    MAX_EVENT_OFFSET,
)
from app.services.fleet_stewards import StewardRegistry, StewardHeld
import fleet_r04_leases as leases
import fleet_r9_mission_control as r9
from fleet_r9_cloud_state import VolumeState, VolumeHeld

SCHEMA = "agentora.fleet.r9-cloud-reponerve-probe.v1"
REPO = "MichaelWave369/Agentora"
REPO_ID = 1167870912
OWNER = "MichaelWave369"
NERVE_SHA = "a625e8ac34831420ab52f2372bf4ec9079258c4a"
GIT_SHA = re.compile(r"[0-9a-f]{40}\Z")
REPO_ROOT = HERE.parent


class ProbeHeld(ValueError):
    pass


def need(ok, why):
    if not ok:
        raise ProbeHeld(why)


def rev_parse(path):
    try:
        return subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL, timeout=8, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        raise ProbeHeld("GIT_REVISION_UNAVAILABLE") from None


def authenticated_public_opener(token, *, transport=None):
    """Authenticate ONLY the fixed public owner inventory API, never /user/repos.

    RepoNerve's existing GitHubClient must be instantiated with token=""
    so it continues to select /users/MichaelWave369/repos. Auth is added
    *after* the destination and GET query have been strictly validated.
    A non-redirectable header prevents forwarding the token on redirects.
    """
    need(type(token) is str and 8 <= len(token) <= 4096 and
         not any(c in token for c in "\r\n\x00 "),
         "REPONERVE_READ_TOKEN_MISSING_OR_UNSAFE")
    transport = transport or request.urlopen

    def public_only(req, *, timeout):
        need(isinstance(req, request.Request) and req.get_method() == "GET",
             "REPONERVE_PUBLIC_METHOD_REJECTED")
        uri = parse.urlsplit(req.full_url)
        need(uri.scheme == "https" and uri.netloc == "api.github.com" and
             uri.path == f"/users/{OWNER}/repos" and not uri.fragment,
             "REPONERVE_PUBLIC_ENDPOINT_REJECTED")
        params = parse.parse_qs(uri.query, keep_blank_values=True)
        need(set(params) == {"per_page", "page", "type", "sort", "direction"} and
             params["per_page"] == ["100"] and
             params["type"] == ["owner"] and
             params["sort"] == ["full_name"] and
             params["direction"] == ["asc"] and
             len(params["page"]) == 1 and
             re.fullmatch(r"[1-9][0-9]{0,2}", params["page"][0]),
             "REPONERVE_PUBLIC_QUERY_REJECTED")
        req.add_unredirected_header("Authorization", "Bearer " + token)
        return transport(req, timeout=timeout)

    return public_only


def inventory_error_reason(exc):
    """Stable diagnostic category, with no token, URL, or remote body."""
    code = re.fullmatch(r"GitHub returned HTTP ([1-5][0-9]{2})", str(exc))
    if code:
        return "REPONERVE_PUBLIC_HTTP_" + code.group(1)
    if str(exc).startswith("GitHub inventory request failed:"):
        return "REPONERVE_PUBLIC_TRANSPORT_UNAVAILABLE"
    return "REPONERVE_PUBLIC_INVENTORY_UNAVAILABLE"


def store_get_json(store):
    """Adapt the real local RepoNerve store to Agentora's existing reader.

    Only the three fixed read-only routes are permitted. No private inventory,
    raw SQL, HTTP server, or network callback is exposed.
    """
    def get_json(path):
        if path == "/api/summary":
            return store.summary()
        match = re.fullmatch(r"/api/(repos|events)\?limit=(500|200)&offset=(0|[1-9][0-9]{0,4})", path)
        need(match is not None, "REPONERVE_READ_PATH_NOT_ALLOWLISTED")
        kind, limit, offset = match.groups()
        need((kind == "repos" and limit == "500") or
             (kind == "events" and limit == "200"),
             "REPONERVE_READ_LIMIT_INVALID")
        count, start = int(limit), int(offset)
        need(start <= MAX_EVENT_OFFSET, "REPONERVE_READ_OFFSET_UNSAFE")
        if kind == "repos":
            return {"items": store.repositories(limit=count, offset=start),
                    "limit": count, "offset": start}
        return {"items": store.events(limit=count, offset=start),
                "limit": count, "offset": start}
    return get_json


def find_owned_event(get_json, *, now):
    """Search the complete bounded public event window for Agentora only."""
    for offset in range(0, MAX_EVENT_OFFSET + 1, EVENT_PAGE_SIZE):
        observed = collect_public_observations(
            get_json=get_json, now=now, event_offset=offset)
        candidates = [e for e in observed["recent_events"]
                      if e["github_id"] == REPO_ID and
                      e["full_name"] == REPO and
                      e["event_type"] in r9.R10_EVENT_KINDS]
        if candidates:
            return observed, max(candidates, key=lambda e: e["id"])
        raw = get_json(f"/api/events?limit={EVENT_PAGE_SIZE}&offset={offset}")
        need(type(raw) is dict and type(raw.get("items")) is list,
             "REPONERVE_EVENTS_TRUNCATED")
        if len(raw["items"]) < EVENT_PAGE_SIZE:
            return observed, None
    raise ProbeHeld("REPONERVE_EVENT_WINDOW_INCOMPLETE")


def held_intake(observation, event, source_sha):
    need(type(observation) is dict and type(event) is dict, "EVENT_OR_SOURCE_INVALID")
    need(event.get("github_id") == REPO_ID and event.get("full_name") == REPO
         and event.get("event_type") in r9.R10_EVENT_KINDS,
         "AGENTORA_EVENT_NOT_ALLOWLISTED")
    need(type(source_sha) is str and GIT_SHA.fullmatch(source_sha),
         "AGENTORA_SOURCE_SHA_INVALID")
    # Digest is provenance, NOT human authorization or proof of current HEAD.
    fingerprint = hashlib.sha256(json.dumps({
        "source": observation["schema"],
        "source_scan_id": observation["source_scan_id"],
        "event": event,
        "repository_id": REPO_ID,
        "source_sha": source_sha,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": leases.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": OWNER, "repository": REPO, "repository_id": REPO_ID,
        "source_sha": source_sha, "request_sha256": fingerprint,
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False, "digest_is_authentication": False,
        "independent_checks_run": 0,
        "checks": [{"check_id": "public_source_review",
                    "verification_state": "NOT_RUN",
                    "evidence_receipt": None}],
    }


def qualify_observation(observation, event, source_sha, root, *, now=None):
    """Use the unchanged R9 tables and replay fence, with no external effects."""
    now = now or datetime.now(timezone.utc)
    need(type(observation) is dict and type(event) is dict, "OBSERVATION_INVALID")
    root = Path(root)
    registry = StewardRegistry(root / "r9-stewards.sqlite3")
    registry.ingest(observation, now=now)
    ledger = leases.LeaseLedger(root / "r9-leases.sqlite3")
    control = r9.MissionControl(registry, ledger)
    intake = held_intake(observation, event, source_sha)
    first = control.enqueue_observed(observation, event["id"], intake,
                                     confirmation=r9.CONFIRM, now=now)
    second = control.enqueue_observed(observation, event["id"], intake,
                                      confirmation=r9.CONFIRM, now=now)
    need(first["state"] == "QUEUED_LOCAL_ONLY" and
         second["state"] == "EVENT_ALREADY_QUEUED_NO_NEW_MISSION" and
         first["mission_id"] == second["mission_id"],
         "R9_REPLAY_UNQUALIFIED")
    with ledger._connection() as db:
        mission_count = db.execute("SELECT COUNT(*) FROM r9_missions").fetchone()[0]
        event_count = db.execute("SELECT COUNT(*) FROM r10_event_links").fetchone()[0]
        row = db.execute("SELECT kind,state,github_id FROM r9_missions").fetchone()
    need(mission_count == event_count == 1 and
         row["kind"] == r9.KIND_AUDIT and row["state"] == "QUEUED" and
         row["github_id"] == REPO_ID, "R9_QUEUE_OR_POLICY_MISMATCH")
    return {
        "schema": SCHEMA,
        "state": "EPHEMERAL_ADMISSION_REPLAY_QUALIFIED",
        "repo": REPO,
        "repository_id": REPO_ID,
        "source_sha": source_sha,
        "source_scan_id": observation["source_scan_id"],
        "event_id": event["id"],
        "event_type": event["event_type"],
        "mission_id": first["mission_id"],
        "r9_rows": mission_count,
        "dedupe_verified": True,
        "source_only": True,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "head_revalidated_live": False,
        "persisted_across_runs": False,
        "product_verified_complete": False,
    }


@contextmanager
def state_root(state_dir):
    if state_dir is None:
        with TemporaryDirectory(prefix="r9-cloud-observe-") as temporary:
            yield Path(temporary), None
    else:
        with VolumeState(state_dir) as volume:
            yield volume.working, volume


def recorded_durable_event(root, observation, event):
    """Verify both independent SQLite histories before deduplicating a replay.

    Existing R9 event IDs are bound to the ORIGINAL RepoNerve scan lineage.
    A later scan or newer checked-out source SHA must not rewrite that record.
    """
    with sqlite3.connect(str(root / "r9-leases.sqlite3")) as db:
        db.row_factory = sqlite3.Row
        row = db.execute("""SELECT e.mission_id,e.github_id,e.source_scan_id,
                                    e.event_type,e.source_payload_digest,
                                    m.repository,m.source_sha,m.intake_digest,
                                    m.kind,m.state
                             FROM r10_event_links e JOIN r9_missions m
                               ON e.mission_id=m.mission_id
                             WHERE e.source_event_id=?""", (event["id"],)).fetchone()
    if row is None:
        return None
    old = dict(row)
    with sqlite3.connect(str(root / "reponerve.sqlite3")) as db:
        db.row_factory = sqlite3.Row
        historic = db.execute("""SELECT scan_id,github_id,full_name,event_type
                                 FROM events WHERE id=?""",
                              (event["id"],)).fetchone()
    need(historic is not None and
         historic["scan_id"] == old["source_scan_id"] and
         historic["github_id"] == event["github_id"] and
         historic["full_name"] == event["full_name"] and
         historic["event_type"] == event["event_type"] and
         old["github_id"] == REPO_ID and old["repository"] == REPO and
         old["event_type"] == event["event_type"] and
         old["kind"] == r9.KIND_AUDIT and
         GIT_SHA.fullmatch(old["source_sha"]) and
         re.fullmatch(r"[0-9a-f]{64}", old["source_payload_digest"]) and
         re.fullmatch(r"[0-9a-f]{64}", old["intake_digest"]) and
         old["state"] in ("QUEUED", "QA_HELD", "HELD_RECONCILE", "ARCHIVED_HELD",
                          "COMPLETED", "MERGED"),
         "R9_DURABLE_EVENT_HISTORY_CONFLICT")
    need(observation["source_scan_id"] >= old["source_scan_id"],
         "R9_DURABLE_SOURCE_SCAN_ROLLBACK")
    return {"schema": SCHEMA,
            "state": "DURABLE_REPLAY_VERIFIED",
            "repository_id": REPO_ID,
            "repo": REPO,
            "source_scan_id": observation["source_scan_id"],
            "event_id": event["id"],
            "event_type": event["event_type"],
            "mission_id": old["mission_id"],
            "original_source_sha": old["source_sha"],
            "r9_rows": 1,
            "dedupe_verified": True,
            "persisted_across_runs": True,
            "dispatch_authorized": False,
            "merge_authorized": False,
            "product_verified_complete": False}


def cloud_probe(nerve_path, *, expected_action_sha, expected_repo_id,
                get_now=None, state_dir=None):
    need(expected_repo_id == str(REPO_ID), "ACTIONS_REPO_IDENTITY_INVALID")
    need(type(expected_action_sha) is str and
         GIT_SHA.fullmatch(expected_action_sha) and
         rev_parse(REPO_ROOT) == expected_action_sha,
         "TRUSTED_MAIN_CHECKOUT_MISMATCH")
    nerve_path = Path(nerve_path).resolve(strict=True)
    need(nerve_path.is_dir() and rev_parse(nerve_path) == NERVE_SHA,
         "REPONERVE_PINNED_SOURCE_MISMATCH")
    now = get_now or datetime.now(timezone.utc)
    sys.path.insert(0, str(nerve_path))
    # The pinned *read-only observer* is checked out as source, never from
    # an untrusted PR branch or dynamic package index.
    from phireponerve.cli import scan_once
    from phireponerve.github import GitHubClient, InventoryError
    from phireponerve.store import FleetStore

    with state_root(state_dir) as (root, volume):
        source_db = root / "reponerve.sqlite3"
        # A GitHub runner's anonymous API pool may be exhausted. The scoped
        # Actions token is permitted ONLY for the fixed public GET endpoint.
        # RepoNerve still chooses /users/{owner}/repos because token="".
        public_opener = authenticated_public_opener(os.getenv("GITHUB_TOKEN"))
        try:
            scan = scan_once(
                OWNER, source_db,
                client=GitHubClient(token="", opener=public_opener))
        except InventoryError as exc:
            raise ProbeHeld(inventory_error_reason(exc)) from None
        need(scan["status"] == "complete" and scan["repo_count"] > 0,
             "REPONERVE_SCAN_NOT_COMPLETE")
        get_json = store_get_json(FleetStore(source_db))
        observation, event = find_owned_event(get_json, now=now)
        need(any(row["github_id"] == REPO_ID and row["full_name"] == REPO
                 and row["archived"] is False
                 for row in observation["repositories"]),
             "AGENTORA_NOT_IN_PUBLIC_SCAN")
        if event is None:
            if volume is not None:
                registry = StewardRegistry(root / "r9-stewards.sqlite3")
                ledger = leases.LeaseLedger(root / "r9-leases.sqlite3")
                r9.MissionControl(registry, ledger)
                registry.ingest(observation, now=now)
                volume.commit()
            return {
                "schema": SCHEMA, "state": "NO_ELIGIBLE_AGENTORA_EVENT",
                "source_scan_id": observation["source_scan_id"],
                "public_repo_count": observation["public_repo_count"],
                "persisted_across_runs": volume is not None,
                "dispatch_authorized": False,
                "merge_authorized": False,
            }
        if volume is not None and not volume.is_new:
            historical = recorded_durable_event(root, observation, event)
            if historical is not None:
                StewardRegistry(root / "r9-stewards.sqlite3").ingest(
                    observation, now=now)
                volume.commit()
                return historical
        result = qualify_observation(observation, event, expected_action_sha,
                                     root, now=now)
        if volume is not None:
            volume.commit()
            result = {**result,
                      "state": "DURABLE_FIRST_ADMISSION_QUALIFIED",
                      "persisted_across_runs": True}
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reponerve-path", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path,
                        help="private mounted volume, requires explicit opt-in")
    args = parser.parse_args(argv)
    try:
        if args.state_dir is not None:
            need(os.getenv("AGENTORA_R9_DURABLE_ENABLED") == "true",
                 "R9_DURABLE_MODE_NOT_ENABLED")
        result = cloud_probe(
            args.reponerve_path,
            expected_action_sha=os.getenv("GITHUB_SHA"),
            expected_repo_id=os.getenv("GITHUB_REPOSITORY_ID"),
            state_dir=args.state_dir,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ProbeHeld, RepoNerveUnavailable, StewardHeld, r9.MissionHeld,
            leases.LeaseHeld, VolumeHeld, sqlite3.DatabaseError, OSError,
            KeyError, TypeError, ValueError) as exc:
        reason = re.sub(r"[^A-Z0-9_]", "_", str(exc))[:100]
        print("R9_CLOUD_PROBE_HELD " + reason, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
