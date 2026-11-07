"""Read-only PhiRepoNerve R1 consumer. No GitHub credentials or action authority."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

BASE = "http://127.0.0.1:8765"
SCHEMA = "phireponerve.agentora.public-observations.v1"
OWNER = "MichaelWave369"
MAX_REPOS = 10000
PAGE_SIZE = 500
MAX_RESPONSE_BYTES = 1024 * 1024
ALLOWED_EVENTS = {
    "first_observed", "visible_again", "renamed", "archival_changed",
    "default_branch_changed", "push_activity_observed",
}


class RepoNerveUnavailable(ValueError):
    """Invalid, stale, incomplete, or unreachable source observation."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise RepoNerveUnavailable("REPONERVE_REDIRECT_REFUSED")


def _local_json(path: str):
    """Fixed loopback endpoint only; proxy, redirects and oversized replies disabled."""
    if path not in ("/api/summary", "/api/events?limit=200&offset=0") and not (
        path.startswith("/api/repos?limit=500&offset=")
        and path.removeprefix("/api/repos?limit=500&offset=").isdigit()
    ):
        raise RepoNerveUnavailable("REPONERVE_PATH_REFUSED")
    url = BASE + path
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(Request(url, headers={"Accept": "application/json"}), timeout=4) as res:
            if res.geturl() != url or res.status != 200:
                raise RepoNerveUnavailable("REPONERVE_HTTP_UNAVAILABLE")
            raw = res.read(MAX_RESPONSE_BYTES + 1)
    except RepoNerveUnavailable:
        raise
    except Exception as exc:
        raise RepoNerveUnavailable("REPONERVE_UNAVAILABLE") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RepoNerveUnavailable("REPONERVE_RESPONSE_TOO_LARGE")
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise RepoNerveUnavailable("REPONERVE_INVALID_JSON") from exc


def _positive_id(value):
    return type(value) is int and 0 < value <= 9007199254740991


def _age_ok(timestamp, now):
    try:
        dt = datetime.fromisoformat(timestamp)
        if dt.tzinfo is None:
            return False
        seconds = (now - dt).total_seconds()
        return -300 <= seconds <= 36 * 3600
    except (TypeError, ValueError, OverflowError):
        return False


def collect_public_observations(get_json=None, *, now=None):
    """Return ONLY public metadata and redacted event kinds from a complete local scan.

    Caller-provided get_json permits offline tests. This return value is data,
    never an authorization token, release certificate, or agent job.
    """
    get_json = get_json or _local_json
    now = now or datetime.now(timezone.utc)
    summary = get_json("/api/summary")
    if not isinstance(summary, dict):
        raise RepoNerveUnavailable("REPONERVE_SUMMARY_INVALID")
    scan = summary.get("latest_complete")
    attempt = summary.get("latest_attempt")
    if not isinstance(scan, dict) or not isinstance(attempt, dict):
        raise RepoNerveUnavailable("REPONERVE_NO_COMPLETE_SCAN")
    if (scan.get("status") != "complete" or attempt.get("status") != "complete"
            or scan.get("id") != attempt.get("id") or scan.get("owner") != OWNER
            or not _positive_id(scan.get("id"))
            or not _age_ok(scan.get("observed_at"), now)):
        raise RepoNerveUnavailable("REPONERVE_INCOMPLETE_OR_STALE")
    expected = scan.get("repo_count")
    if type(expected) is not int or not 0 <= expected <= MAX_REPOS:
        raise RepoNerveUnavailable("REPONERVE_COUNT_INVALID")

    all_rows = []
    for offset in range(0, expected + PAGE_SIZE, PAGE_SIZE):
        response = get_json(f"/api/repos?limit=500&offset={offset}")
        batch = response.get("items") if isinstance(response, dict) else None
        if not isinstance(batch, list) or len(batch) > PAGE_SIZE:
            raise RepoNerveUnavailable("REPONERVE_PAGE_INVALID")
        all_rows.extend(batch)
        if len(all_rows) > expected:
            raise RepoNerveUnavailable("REPONERVE_COUNT_DRIFT")
        if len(batch) < PAGE_SIZE:
            break
    if len(all_rows) != expected:
        raise RepoNerveUnavailable("REPONERVE_INVENTORY_DRIFT")

    seen = set()
    public = []
    public_by_id = {}
    for row in all_rows:
        if not isinstance(row, dict) or not _positive_id(row.get("github_id")):
            raise RepoNerveUnavailable("REPONERVE_ID_INVALID")
        repo_id = row["github_id"]
        if repo_id in seen:
            raise RepoNerveUnavailable("REPONERVE_DUPLICATE_ID")
        seen.add(repo_id)
        full = row.get("full_name")
        if not isinstance(full, str) or not full.startswith(OWNER + "/"):
            raise RepoNerveUnavailable("REPONERVE_OWNER_INVALID")
        name = full[len(OWNER) + 1:]
        if not name or len(name) > 100 or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for ch in name):
            raise RepoNerveUnavailable("REPONERVE_NAME_INVALID")
        if row.get("private") not in (0, 1, False, True) or row.get("present") not in (1, True):
            raise RepoNerveUnavailable("REPONERVE_VISIBILITY_INVALID")
        if bool(row["private"]):
            continue
        item = {"github_id": repo_id, "full_name": full, "archived": bool(row.get("archived")),
                "source_only": True, "verified_complete": False}
        public.append(item)
        public_by_id[repo_id] = full

    response = get_json("/api/events?limit=200&offset=0")
    event_rows = response.get("items") if isinstance(response, dict) else None
    if not isinstance(event_rows, list) or len(event_rows) > 200:
        raise RepoNerveUnavailable("REPONERVE_EVENTS_INVALID")
    recent = []
    for e in event_rows:
        if not isinstance(e, dict):
            raise RepoNerveUnavailable("REPONERVE_EVENT_INVALID")
        rid = e.get("github_id")
        if rid not in public_by_id or e.get("event_type") not in ALLOWED_EVENTS:
            continue
        if not _positive_id(e.get("id")) or not _age_ok(e.get("observed_at"), now):
            continue
        # Never copy before_value, after_value or historic repository names.
        recent.append({"id": e["id"], "github_id": rid, "full_name": public_by_id[rid],
                       "event_type": e["event_type"], "observed_at": e["observed_at"]})

    # Source may change between pagination and final check. Do not export races.
    after = get_json("/api/summary")
    new_scan = after.get("latest_complete") if isinstance(after, dict) else None
    new_attempt = after.get("latest_attempt") if isinstance(after, dict) else None
    if not isinstance(new_scan, dict) or not isinstance(new_attempt, dict) or (
        new_scan.get("id") != scan["id"] or new_attempt.get("id") != scan["id"]
        or new_attempt.get("status") != "complete"
    ):
        raise RepoNerveUnavailable("REPONERVE_SCAN_CHANGED")

    return {
        "schema": SCHEMA, "owner": OWNER, "scope": "public_only",
        "source": "PHIREPONERVE_LOCAL_R1", "source_scan_id": scan["id"],
        "observed_at": scan["observed_at"], "public_repo_count": len(public),
        "repositories": sorted(public, key=lambda r: r["full_name"].lower()),
        "recent_events": recent,
        "source_only": True, "dispatch_authorized": False,
        "merge_authorized": False, "verified_complete": False,
    }
