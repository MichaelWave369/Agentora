"""Cloud-only public RepoNerve -> existing Agentora R9 admission qualification.

The scan and R9 SQLite files are ephemeral for this PRE-PERSISTENCE pilot.
No workflow dispatch, owner approval, PR write, or merge. Do not mistake
replay inside one runner for cross-run durable state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))

from app.integrations.phireponerve_client import (
    collect_public_observations, RepoNerveUnavailable, EVENT_PAGE_SIZE,
    MAX_EVENT_OFFSET,
)
from app.services.fleet_stewards import StewardRegistry, StewardHeld
import fleet_r04_leases as leases
import fleet_r9_mission_control as r9

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


def cloud_probe(nerve_path, *, expected_action_sha, expected_repo_id,
                get_now=None):
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

    with TemporaryDirectory(prefix="r9-cloud-observe-") as path:
        root = Path(path)
        source_db = root / "reponerve.sqlite3"
        # Force public, anonymous inventory; avoid GitHub App credentials or
        # private owner-affiliated /user/repos enumeration.
        try:
            scan = scan_once(OWNER, source_db, client=GitHubClient(token=""))
        except InventoryError:
            raise ProbeHeld("REPONERVE_PUBLIC_INVENTORY_UNAVAILABLE") from None
        need(scan["status"] == "complete" and scan["repo_count"] > 0,
             "REPONERVE_SCAN_NOT_COMPLETE")
        get_json = store_get_json(FleetStore(source_db))
        observation, event = find_owned_event(get_json, now=now)
        need(any(row["github_id"] == REPO_ID and row["full_name"] == REPO
                 and row["archived"] is False
                 for row in observation["repositories"]),
             "AGENTORA_NOT_IN_PUBLIC_SCAN")
        if event is None:
            return {
                "schema": SCHEMA, "state": "NO_ELIGIBLE_AGENTORA_EVENT",
                "source_scan_id": observation["source_scan_id"],
                "public_repo_count": observation["public_repo_count"],
                "persisted_across_runs": False,
                "dispatch_authorized": False,
                "merge_authorized": False,
            }
        return qualify_observation(observation, event, expected_action_sha,
                                   root, now=now)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reponerve-path", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = cloud_probe(
            args.reponerve_path,
            expected_action_sha=os.getenv("GITHUB_SHA"),
            expected_repo_id=os.getenv("GITHUB_REPOSITORY_ID"),
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ProbeHeld, RepoNerveUnavailable, StewardHeld, r9.MissionHeld,
            leases.LeaseHeld, OSError, KeyError, TypeError, ValueError) as exc:
        reason = re.sub(r"[^A-Z0-9_]", "_", str(exc))[:100]
        print("R9_CLOUD_PROBE_HELD " + reason, file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
