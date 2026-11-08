"""GitHub-hosted, read-only evidence review for the fixed PhiMada sandbox pilot.

One GitHub Actions run ID and the GitHub-owned artifact ZIP are verified by
the existing Fleet R0.7 code, on an ephemeral GitHub Actions runner. No
operator-installed Python, SQLite, R0.4 lease files, agent code execution,
GitHub writes, dispatch, PR approval, release, or product qualification.

Do NOT attribute historical untraced runs to newer Agentora R10 missions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import fleet_r05_source_observe as source
import fleet_r07_evidence_review as evidence

SCHEMA = "agentora.fleet.cloud-evidence-review.v1"
MAX_BYTES = evidence.MAX_ARCHIVE_BYTES
HOST = "api.github.com"
SAFE_STORAGE_HOSTS = (
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
)
SAFE_STORAGE_SUFFIXES = (
    ".blob.core.windows.net",
    ".actions.githubusercontent.com",
    ".githubusercontent.com",
)
FIXED_REPO = "MichaelWave369/Agentora"


class CloudReviewHeld(ValueError):
    """Missing or mismatched remote evidence, never an implicit success."""


def need(ok, reason):
    if not ok:
        raise CloudReviewHeld(reason)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _safe_blob(url):
    try:
        parsed = urlsplit(url)
    except ValueError:
        raise CloudReviewHeld("SIGNED_ARTIFACT_URL_INVALID") from None
    host = parsed.hostname
    need(type(host) is str and parsed.scheme == "https"
         and parsed.username is None and parsed.password is None
         and (host in SAFE_STORAGE_HOSTS or
              any(host.endswith(suffix) for suffix in SAFE_STORAGE_SUFFIXES)),
         "SIGNED_ARTIFACT_HOST_NOT_ALLOWLISTED")
    return url


def download_artifact(artifact_id, token):
    """Download one fixed-repo ZIP without forwarding the token on redirect.

    The first request is authenticated to api.github.com, never to an
    attacker-selected domain. The 302's signed storage URL receives an
    entirely NEW, unauthenticated request after hostname validation.
    """
    need(type(artifact_id) is int and 0 < artifact_id <= 9223372036854775807,
         "ARTIFACT_ID_INVALID")
    need(type(token) is str and bool(token.strip()), "ACTIONS_READ_TOKEN_REQUIRED")
    uri = (f"https://{HOST}/repos/{FIXED_REPO}/actions/artifacts/"
           f"{artifact_id}/zip")
    request = Request(uri, method="GET", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentora-r11-readonly-cloud-review",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        try:
            with opener.open(request, timeout=15) as response:
                need(response.status in (301, 302, 303, 307, 308),
                     "GITHUB_ARTIFACT_REDIRECT_REQUIRED")
                location = response.headers.get("Location")
        except HTTPError as err:
            need(err.code in (301, 302, 303, 307, 308),
                 "GITHUB_ARTIFACT_RESPONSE_NOT_REDIRECT")
            location = err.headers.get("Location")
        need(type(location) is str and len(location) <= 8192,
             "SIGNED_ARTIFACT_URL_INVALID")
        signed_url = _safe_blob(location)
        # No Authorization header is included here.
        signed_request = Request(signed_url, method="GET", headers={
            "User-Agent": "agentora-r11-readonly-cloud-review",
        })
        with opener.open(signed_request, timeout=30) as response:
            need(response.status == 200, "GITHUB_ARTIFACT_STORAGE_NOT_OK")
            raw = response.read(MAX_BYTES + 1)
    except (URLError, TimeoutError, OSError):
        raise CloudReviewHeld("ARTIFACT_DOWNLOAD_UNAVAILABLE") from None
    need(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES,
         "ARTIFACT_BYTES_INVALID_OR_TOO_LARGE")
    return raw


def _artifact_id(catalog, run_id):
    need(type(catalog) is dict and
         type(catalog.get("total_count")) is int and
         1 <= catalog["total_count"] <= evidence.MAX_ARTIFACT_LIST and
         type(catalog.get("artifacts")) is list and
         len(catalog["artifacts"]) == catalog["total_count"],
         "GITHUB_ARTIFACT_CATALOG_UNTRUSTED")
    expected_name = evidence.ARTIFACT_PREFIX + str(run_id)
    found = [a for a in catalog["artifacts"] if type(a) is dict and
             a.get("name") == expected_name]
    need(len(found) == 1, "GITHUB_PILOT_ARTIFACT_MISSING_OR_AMBIGUOUS")
    item = found[0]
    need(type(item.get("id")) is int and item["id"] > 0 and
         type(item.get("size_in_bytes")) is int and
         0 < item["size_in_bytes"] <= MAX_BYTES and
         item.get("expired") is False and
         type(item.get("digest")) is str and
         item["digest"].startswith("sha256:") and
         evidence.SHA64.fullmatch(item["digest"][7:]) is not None,
         "GITHUB_PILOT_ARTIFACT_METADATA_INVALID")
    if "workflow_run" in item and item["workflow_run"] is not None:
        need(type(item["workflow_run"]) is dict and
             item["workflow_run"].get("id") == run_id,
             "GITHUB_ARTIFACT_BELONGS_TO_ANOTHER_RUN")
    return item["id"]


def review_run(run_id, *, token, get=evidence.fixed_github_get,
               download=download_artifact, clock=None):
    """Retrieve and independently validate real GitHub run and artifact bytes."""
    need(type(run_id) is int and 0 < run_id <= 9223372036854775807,
         "GITHUB_RUN_ID_INVALID")
    need(callable(get) and callable(download), "REVIEW_CALLBACK_INVALID")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    need(isinstance(now, datetime) and now.tzinfo is not None, "CLOCK_INVALID")
    now = now.astimezone(timezone.utc)
    base = f"/repos/{FIXED_REPO}/actions/runs/{run_id}"
    run = get(base, token)
    # Reuse R0.7's exact GitHub run identity, fixed workflow, successful
    # completed first attempt, and eight-day freshness check.
    try:
        evidence._run(run, run_id, now)
    except evidence.ReviewHeld as exc:
        raise CloudReviewHeld("RUN_NOT_ELIGIBLE_" + str(exc)) from None
    catalog = get(base + "/artifacts?per_page=100", token)
    artifact_id = _artifact_id(catalog, run_id)
    archive = download(artifact_id, token)
    # R0.7 now independently re-fetches the live run and artifact catalog,
    # checks ZIP bytes against the GitHub SHA-256, rejects untrusted ZIP paths,
    # validates source pre/post receipts and checks the optional R10 trace.
    validated = evidence.review(run_id, archive, github_get=get,
                                token=token, clock=lambda: now)
    need(validated["artifact"]["id"] == artifact_id,
         "GITHUB_ARTIFACT_CHANGED_DURING_REVIEW")
    trace = validated.get("dispatch_request_id")
    need(validated.get("dispatch_origin_authenticated") is False and
         validated.get("merge_authorized") is False and
         validated.get("verified_complete") is False,
         "REVIEW_CANNOT_CONFER_AUTHORITY")
    return {
        "schema": SCHEMA, "state": "GITHUB_FIXED_PILOT_EVIDENCE_CORRELATED",
        "workflow_run_id": run_id,
        "workflow_url": validated["github_workflow_run"]["url"],
        "pilot_source_sha": validated["pilot_source_sha"],
        "github_artifact_id": artifact_id,
        "github_artifact_sha256": validated["artifact"]["sha256"],
        "dispatch_request_id": trace,
        "dispatch_trace_present": validated.get("dispatch_trace_present") is True,
        "historical_untraced_run": trace is None,
        "github_artifact_digest_verified": True,
        "sandbox_checks_reported_success": True,
        "dispatch_origin_authenticated": False,
        "independent_qa_performed": False,
        "product_verified": False,
        "verified_complete": False,
        "merge_authorized": False,
        "dispatch_authorized": False,
    }


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    need(not path.is_symlink() and not path.exists(), "OUTPUT_EXISTS")
    raw = data.encode("utf-8")
    need(0 < len(raw) <= 16384, "REVIEW_OUTPUT_TOO_LARGE")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)


def _summary(report):
    state = report["state"]
    if state == "GITHUB_FIXED_PILOT_EVIDENCE_CORRELATED":
        lines = [
            "## Fixed PhiMada pilot: GitHub artifact checked",
            "",
            f"- Run: {report['workflow_url']}",
            f"- PhiMada source SHA: \`{report['pilot_source_sha']}\`",
            f"- Artifact ID: \`{report['github_artifact_id']}\`",
            f"- Verified ZIP SHA-256: \`{report['github_artifact_sha256']}\`",
            f"- Request ID: \`{report['dispatch_request_id'] or 'none (legacy untraced)'}\`",
            "- Fixed sandbox checks: reported success in GitHub-validated receipt",
            "- Independent QA: **not performed**",
            "- Product verification, merge, and deployment: **not authorized**",
        ]
    else:
        lines = [
            "## Fixed PhiMada pilot: evidence held",
            "",
            f"- State: \`{state}\`",
            "- No verified success, QA approval, merge or deployment was granted",
        ]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pilot-run-id", required=True, type=int)
    p.add_argument("--output-dir", default="cloud-review", type=Path)
    a = p.parse_args(argv)
    try:
        report = review_run(a.pilot_run_id, token=os.environ.get("GITHUB_TOKEN"))
        result = 0
    except (CloudReviewHeld, evidence.ReviewHeld, source.ObservationHeld,
            ValueError, TypeError, OSError) as exc:
        # No signed storage URL, environment token, or raw server response
        # should ever appear in report artifacts or step summaries.
        code = str(exc) if isinstance(exc, (CloudReviewHeld, evidence.ReviewHeld,
            source.ObservationHeld)) else "REVIEW_INPUT_OR_IO_UNAVAILABLE"
        report = {"schema": SCHEMA, "state": "HELD_" + code,
                  "workflow_run_id": a.pilot_run_id,
                  "github_artifact_digest_verified": False,
                  "independent_qa_performed": False,
                  "product_verified": False, "verified_complete": False,
                  "merge_authorized": False, "dispatch_authorized": False}
        result = 3
    output = a.output_dir
    _write(output / "review.json", json.dumps(report, sort_keys=True, indent=2) + "\n")
    _write(output / "summary.md", _summary(report))
    print(json.dumps({"state": report["state"], "workflow_run_id": a.pilot_run_id,
                      "merge_authorized": False, "verified_complete": False}))
    return result


if __name__ == "__main__":
    raise SystemExit(main())
