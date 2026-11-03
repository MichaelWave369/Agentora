"""Fleet Mode R0.1: evidence-limited, read-only GitHub repository audit.

Only public owner repositories are scanned by default. This tool never creates,
updates, merges, dispatches, publishes, or deletes GitHub resources.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

OWNER = "MichaelWave369"
PILOT = ("Agentora", "PhiOS", "PhiServe", "FieldConstellation", "BTM", "SuperPhiVessel")
SCHEMA = "agentora.fleet.audit.v0.1"
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
MAX_API_BYTES = 2_000_000
MAX_README = 150_000
MAX_PAGES = 20
MAX_WORKERS = 4


class AuditHeld(Exception):
    """Input or observation did not meet a fail-closed contract."""


def github_get(path, token=None):
    """GET only, API-origin fixed, bounded response. Return None only for HTTP 404."""
    if not isinstance(path, str) or not path.startswith("/") or "://" in path:
        raise AuditHeld("INVALID_API_PATH")
    request = Request("https://api.github.com" + path, method="GET", headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agentora-fleet-r01-readonly",
        **({"Authorization": "Bearer " + token} if token else {}),
    })
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(MAX_API_BYTES + 1)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise AuditHeld("GITHUB_HTTP_" + str(exc.code)) from None
    except (URLError, TimeoutError, OSError):
        raise AuditHeld("GITHUB_READ_UNAVAILABLE") from None
    if len(raw) > MAX_API_BYTES:
        raise AuditHeld("GITHUB_RESPONSE_TOO_LARGE")
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise AuditHeld("GITHUB_INVALID_JSON") from None


def repo_path(name):
    if not isinstance(name, str) or not REPO_NAME.fullmatch(name) or name in (".", ".."):
        raise AuditHeld("INVALID_REPOSITORY_NAME")
    return "/repos/" + OWNER + "/" + quote(name, safe="")


def inventory(get, token, include_private=False):
    """Exhaust public owner pages; private enumeration is explicit, local-only."""
    if include_private and not token:
        raise AuditHeld("PRIVATE_AUDIT_REQUIRES_TOKEN")
    base = ("/user/repos?affiliation=owner&sort=full_name&per_page=100&page="
            if include_private else
            "/users/" + OWNER + "/repos?type=owner&sort=full_name&per_page=100&page=")
    found = {}
    exhausted = False
    for page in range(1, MAX_PAGES + 1):
        data = get(base + str(page), token)
        if not isinstance(data, list) or len(data) > 100:
            raise AuditHeld("INVENTORY_PAGE_INVALID")
        for row in data:
            if not isinstance(row, dict):
                raise AuditHeld("INVENTORY_ROW_INVALID")
            if (row.get("owner") or {}).get("login", "").lower() != OWNER.lower():
                continue
            name = row.get("name")
            ident = row.get("id")
            if not isinstance(ident, int) or not isinstance(name, str):
                raise AuditHeld("INVENTORY_ID_INVALID")
            repo_path(name)
            if row.get("private") is True and not include_private:
                continue
            if ident in found and found[ident].get("name") != name:
                raise AuditHeld("INVENTORY_DUPLICATE_ID")
            found[ident] = row
        if len(data) < 100:
            exhausted = True
            break
    if not exhausted:
        raise AuditHeld("INVENTORY_PAGE_LIMIT")
    return sorted(found.values(), key=lambda r: (r["name"].lower(), r["id"]))


def decoded_file(value, max_bytes=MAX_README):
    if value is None:
        return None
    if not isinstance(value, dict) or value.get("encoding") != "base64":
        raise AuditHeld("FILE_ENCODING_UNSUPPORTED")
    encoded = value.get("content")
    if not isinstance(encoded, str) or len(encoded) > (max_bytes * 4 // 3 + 100):
        raise AuditHeld("FILE_TOO_LARGE")
    try:
        raw = base64.b64decode(encoded, validate=False)
        if len(raw) > max_bytes:
            raise AuditHeld("FILE_TOO_LARGE")
        return raw.decode("utf-8")
    except (ValueError, UnicodeError):
        raise AuditHeld("FILE_CONTENT_INVALID") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def probe_pages(url, repo_name):
    """Check public owner github.io HTML only; no tokens and no redirects."""
    parsed = urlsplit(url or "")
    expected_host = OWNER.lower() + ".github.io"
    expected_path = "/" + repo_name.lower()
    if (parsed.scheme != "https" or parsed.hostname != expected_host or
            parsed.username or parsed.password or parsed.port or
            not parsed.path.lower().rstrip("/").startswith(expected_path)):
        return "CUSTOM_OR_UNSAFE_URL_NOT_PROBED"
    # Do not accidentally accept a sibling repository with a shared prefix.
    path = parsed.path.lower()
    if path != expected_path and not path.startswith(expected_path + "/"):
        return "CUSTOM_OR_UNSAFE_URL_NOT_PROBED"
    request = Request(url, method="GET", headers={"User-Agent": "agentora-fleet-r01"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            status = response.status
            head = response.read(4096).lower()
            mime = response.headers.get("Content-Type", "").lower()
    except HTTPError as exc:
        return "REDIRECT_UNVERIFIED" if exc.code in (301, 302, 303, 307, 308) else "HTTP_" + str(exc.code)
    except (URLError, TimeoutError, OSError):
        return "NETWORK_UNAVAILABLE"
    if status != 200:
        return "HTTP_" + str(status)
    if "text/html" in mime and (b"<html" in head or b"<!doctype html" in head):
        return "HTML_REACHABLE_NOT_RUNTIME_VERIFIED"
    return "NON_HTML_OR_UNEXPECTED_CONTENT"


def observed(get, token, path, errors, label):
    try:
        return get(path, token)
    except AuditHeld as exc:
        errors.append(label + ":" + str(exc))
        return None


def relationships(readme, known):
    if not readme:
        return []
    related = set()
    for name in re.findall(
            r"github\.com/MichaelWave369/([A-Za-z0-9_.-]+)", readme, flags=re.IGNORECASE):
        cleaned = name.rstrip(".")
        found = known.get(cleaned.lower())
        if found:
            related.add(found)
    return sorted(related, key=str.lower)


def scan_one(row, get, token, known, probe=probe_pages):
    name = row["name"]
    base = repo_path(name)
    branch = row.get("default_branch")
    result = {
        "repository": OWNER + "/" + name,
        "repository_id": row["id"],
        "visibility": "private" if row.get("private") else "public",
        "archived": row.get("archived") is True,
        "default_branch": branch,
        "head_sha": None,
        "software_type": "UNCLASSIFIED",
        "ci": "NOT_VERIFIED",
        "pages": "NOT_VERIFIED",
        "release": "NOT_VERIFIED",
        "relationships": [],
        "relationship_evidence": "README_LINKS_ONLY_NOT_RUNTIME_INTEGRATIONS",
        "roadmap": [],
        "completion": "UNVERIFIED",
        "errors": [],
    }
    errors = result["errors"]
    if not isinstance(branch, str) or not REPO_NAME.fullmatch(branch):
        errors.append("BRANCH:INVALID")
    else:
        head = observed(get, token, base + "/branches/" + quote(branch, safe=""), errors, "BRANCH")
        if isinstance(head, dict):
            sha = (head.get("commit") or {}).get("sha")
            if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha):
                result["head_sha"] = sha
        if result["head_sha"]:
            runs = observed(get, token, base + "/actions/runs?" + urlencode(
                {"branch": branch, "per_page": 20}), errors, "CI")
            if isinstance(runs, dict) and isinstance(runs.get("workflow_runs"), list):
                matching = [r for r in runs["workflow_runs"] if
                            isinstance(r, dict) and r.get("head_sha") == result["head_sha"]]
                if matching:
                    states = {(r.get("status"), r.get("conclusion")) for r in matching}
                    if any(s == "completed" and c == "failure" for s, c in states):
                        result["ci"] = "FAILURE_OBSERVED_AT_HEAD"
                    elif all(s == "completed" and c == "success" for s, c in states):
                        result["ci"] = "OBSERVED_RUNS_GREEN_AT_HEAD_NOT_BUILD_PROOF"
                    else:
                        result["ci"] = "PENDING_OR_NON_SUCCESS_AT_HEAD"
                else:
                    result["ci"] = "NO_RECENT_RUN_AT_HEAD"
            elif runs is None and not any(s.startswith("CI:") for s in errors):
                result["ci"] = "NO_ACTIONS_DATA"
    pages = observed(get, token, base + "/pages", errors, "PAGES")
    if isinstance(pages, dict) and isinstance(pages.get("html_url"), str):
        result["pages"] = probe(pages["html_url"], name)
    elif pages is None and not any(s.startswith("PAGES:") for s in errors):
        result["pages"] = "NOT_CONFIGURED_OR_NOT_ACCESSIBLE"
    releases = observed(get, token, base + "/releases?per_page=5", errors, "RELEASE")
    if isinstance(releases, list):
        eligible = [x for x in releases if isinstance(x, dict) and not x.get("draft")]
        result["release"] = ("PUBLISHED_METADATA_NOT_FUNCTIONALITY_VERIFIED" if eligible
                             else "NO_PUBLISHED_RELEASE_FOUND")
    package = observed(get, token, base + "/contents/package.json", errors, "PACKAGE")
    if package is not None:
        try:
            obj = json.loads(decoded_file(package) or "{}")
            deps = {**(obj.get("dependencies") or {}), **(obj.get("devDependencies") or {})}
            result["software_type"] = ("REACT_CANDIDATE" if "react" in deps else "NODE_CANDIDATE")
        except (ValueError, TypeError, AuditHeld):
            errors.append("PACKAGE:UNREADABLE")
    readme = observed(get, token, base + "/readme", errors, "README")
    if readme is not None:
        try:
            result["relationships"] = [x for x in relationships(decoded_file(readme), known)
                                       if x.lower() != name.lower()]
        except AuditHeld:
            errors.append("README:UNREADABLE")
    if result["ci"] != "OBSERVED_RUNS_GREEN_AT_HEAD_NOT_BUILD_PROOF":
        result["roadmap"].append("Establish or verify exact-head CI and build evidence")
    if result["pages"] != "HTML_REACHABLE_NOT_RUNTIME_VERIFIED":
        result["roadmap"].append("Determine whether a deployed site is required; verify its URL if so")
    if result["release"] != "PUBLISHED_METADATA_NOT_FUNCTIONALITY_VERIFIED":
        result["roadmap"].append("Define release or deliverable acceptance for this project type")
    result["roadmap"].append("Run project-specific functional acceptance and record a version-bound receipt")
    return result


def assemble(rows, get, token, scope="pilot", include_private=False, probe=probe_pages):
    if scope not in ("pilot", "all"):
        raise AuditHeld("INVALID_SCOPE")
    known = {row["name"].lower(): row["name"] for row in rows}
    selected = {n.lower() for n in PILOT} if scope == "pilot" else set(known)
    deep = [row for row in rows if row["name"].lower() in selected]
    output = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        tasks = {pool.submit(scan_one, r, get, token, known, probe): r["name"] for r in deep}
        for task in as_completed(tasks):
            output[tasks[task]] = task.result()
    records = []
    for row in rows:
        name = row["name"]
        records.append(output.get(name, {
            "repository": OWNER + "/" + name,
            "repository_id": row["id"],
            "visibility": "private" if row.get("private") else "public",
            "archived": row.get("archived") is True,
            "completion": "NOT_AUDITED",
        }))
    return {
        "schema": SCHEMA,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "owner": OWNER,
        "scope": scope,
        "private_included": include_private,
        "merge_authorized": False,
        "job_dispatch_authorized": False,
        "repository_count": len(rows),
        "deep_audited_count": len(deep),
        "unverified_count": len(deep),
        "repositories": records,
    }


def markdown(result):
    lines = [
        "# Agentora Fleet Mode R0.1 — Read-Only Audit",
        "",
        f"Generated UTC: {result['generated_utc']}",
        "",
        f"- Owned repositories enumerated: **{result['repository_count']}**",
        f"- Deep audited: **{result['deep_audited_count']}** ({result['scope']} scope)",
        f"- Completion verified: **0** (functional acceptance is out of scope)",
        "- Merge and job dispatch authority: **none**",
        "",
        "This is an observation report, not an assertion that any site, release, "
        "React app, or integration works end-to-end. Private repositories are "
        "excluded unless a local operator explicitly requests them.",
        "",
        "| Repository | CI | Pages | Release | Completion |",
        "|---|---|---|---|---|",
    ]
    for row in result["repositories"]:
        if row["completion"] == "NOT_AUDITED":
            continue
        display = row["repository"].split("/", 1)[1].replace("|", "")
        cells = [display, row["ci"], row["pages"], row["release"], row["completion"]]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "## Evidence gaps and proposed checks", ""]
    for row in result["repositories"]:
        if row["completion"] == "NOT_AUDITED":
            continue
        lines.append("### " + row["repository"])
        lines.append("Related by README links only: " +
                     (", ".join(row["relationships"]) if row["relationships"] else "none observed"))
        for task in row["roadmap"]:
            lines.append("- [ ] " + task)
        if row["errors"]:
            lines.append("Observation limits: " + ", ".join(row["errors"]))
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("pilot", "all"), default="pilot")
    parser.add_argument("--output-dir", default="fleet-artifacts")
    parser.add_argument("--include-private", action="store_true",
                        help="Local-only: do not run with this flag in public GitHub Actions")
    args = parser.parse_args(argv)
    if args.include_private and os.getenv("GITHUB_ACTIONS") == "true":
        raise AuditHeld("PRIVATE_AUDIT_DISABLED_IN_ACTIONS")
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    rows = inventory(github_get, token, args.include_private)
    result = assemble(rows, github_get, token, args.scope, args.include_private)
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "fleet-audit.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                                          encoding="utf-8")
    (out / "fleet-audit.md").write_text(markdown(result), encoding="utf-8")
    print(f"FLEET_READ_ONLY inventory={result['repository_count']} "
          f"audited={result['deep_audited_count']} completion_verified=0")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuditHeld as error:
        print("FLEET_HELD " + str(error), file=sys.stderr)
        raise SystemExit(1)
