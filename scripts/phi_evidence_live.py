"""Phi Evidence Wire R0.2: fresh public GitHub corroboration, never approval.

Rechecks exact merged SHA and all observed GitHub check/status rows against
GMED v1; independently reads the original Agentora Fleet R14 journal entry
and current default-branch SHA. Does NOT revalidate R13/R14 artifact ZIP
bytes, attest model weights, check Lean proofs, or authorize code changes.
"""
from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

import phi_evidence_wire as wire

SCHEMA = "agentora.phi.evidence-live.v0.2"
R14_MARK = "<!-- agentora-fleet-r14-handoff-v1 -->"
MAX_PAGES = 5
MAX_BYTES = 1_000_000
ALLOWED_CONCLUSIONS = {"success", "neutral", "skipped"}
R14_HOME = "MichaelWave369/Agentora"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def github_get(path: str):
    """Return (JSON, has_next). Fixed GitHub HTTPS origin, no redirects."""
    wire.need(type(path) is str and path.startswith("/repos/") and
              ".." not in path and "://" not in path,
              "GITHUB_API_PATH_INVALID")
    token = os.environ.get("GITHUB_TOKEN", "")
    wire.need(len(token) <= 4096 and "\n" not in token and
              "\r" not in token, "GITHUB_TOKEN_INVALID")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Phi-Evidence-Wire-R02",
    }
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request("https://api.github.com" + path, headers=headers)
    try:
        with build_opener(NoRedirect).open(request, timeout=15) as response:
            wire.need(response.status == 200, "GITHUB_API_NOT_OK")
            raw = response.read(MAX_BYTES + 1)
            wire.need(0 < len(raw) <= MAX_BYTES,
                      "GITHUB_API_RESPONSE_TOO_LARGE")
            link = response.headers.get("Link", "")
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise wire.EvidenceHeld("GITHUB_API_READ_FAILED") from exc
    try:
        data = json.loads(raw.decode("utf-8"),
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError) as exc:
        raise wire.EvidenceHeld("GITHUB_API_JSON_INVALID") from exc
    return data, 'rel="next"' in link


def one(get, path):
    result, has_next = get(path)
    wire.need(type(result) is dict and has_next is False,
              "GITHUB_SINGLE_RESPONSE_HELD")
    return result


def pages(get, path: str, field: str | None, *, total_key=None,
          max_pages=MAX_PAGES):
    """Read complete paginated GitHub lists. Never silently truncate."""
    records = []
    for page in range(1, max_pages + 1):
        payload, has_next = get(path + ("&" if "?" in path else "?") +
                                "per_page=100&page=" + str(page))
        if field is None:
            wire.need(type(payload) is list, "GITHUB_LIST_RESPONSE_INVALID")
            block = payload
        else:
            wire.need(type(payload) is dict and type(payload.get(field)) is list,
                      "GITHUB_LIST_RESPONSE_INVALID")
            block = payload[field]
            if total_key is not None:
                total = payload.get(total_key)
                wire.need(type(total) is int and 0 <= total <= 500,
                          "GITHUB_LIST_TOTAL_INVALID")
                wire.need(len(records) + len(block) <= total,
                          "GITHUB_LIST_EXCEEDS_DECLARED_TOTAL")
        wire.need(len(block) <= 100 and len(records) + len(block) <= 500,
                  "GITHUB_LIST_BOUNDS_HELD")
        records.extend(block)
        if not has_next:
            if field is not None and total_key is not None:
                wire.need(len(records) == payload[total_key],
                          "GITHUB_LIST_TRUNCATED")
            return records
    raise wire.EvidenceHeld("GITHUB_PAGINATION_LIMIT_HELD")


def normalize_live_check(item, sha):
    wire.need(type(item) is dict and item.get("head_sha") == sha,
              "GITHUB_CHECK_WRONG_COMMIT")
    name = item.get("name")
    status = item.get("status")
    conclusion = item.get("conclusion")
    wire.need(type(name) is str and name and status == "completed" and
              conclusion in ALLOWED_CONCLUSIONS,
              "GITHUB_CHECK_NOT_COMPLETE_OR_SUCCESSFUL")
    return {"kind": "check", "name": name, "status": status,
            "conclusion": conclusion, "grade": "good"}


def normalize_live_status(item):
    wire.need(type(item) is dict and type(item.get("context")) is str and
              item["context"] and item.get("state") == "success",
              "GITHUB_LEGACY_STATUS_NOT_SUCCESSFUL")
    return {"kind": "status", "name": item["context"],
            "status": "success", "conclusion": None, "grade": "good"}


def normalized_gmed_rows(rows):
    wire.need(type(rows) is list and 0 < len(rows) <= 500,
              "GMED_OBSERVED_ROWS_INVALID")
    fields = ("kind", "name", "status", "conclusion", "grade")
    result = []
    for row in rows:
        wire.need(type(row) is dict, "GMED_OBSERVED_ROW_INVALID")
        result.append({key: row.get(key) for key in fields})
    return result


def sorted_rows(rows):
    return sorted((json.dumps(x, sort_keys=True, separators=(",", ":"))
                   for x in rows))


def r14_comment(get, r14):
    number = r14["mission_issue"]
    issue = one(get, f"/repos/{R14_HOME}/issues/{number}")
    wire.need(issue.get("number") == number and
              issue.get("pull_request") is None,
              "R14_MISSION_ISSUE_INVALID")
    comments = pages(get, f"/repos/{R14_HOME}/issues/{number}/comments",
                     None, max_pages=3)
    found = []
    for comment in comments:
        wire.need(type(comment) is dict, "R14_COMMENT_INVALID")
        body = comment.get("body")
        prefix = R14_MARK + "\n~~~json\n"
        suffix = "\n~~~"
        if type(body) is not str or not body.startswith(R14_MARK):
            continue
        wire.need(body.startswith(prefix) and body.endswith(suffix) and
                  len(body) <= 9000 and
                  (comment.get("user") or {}).get("login") ==
                     "github-actions[bot]" and
                  type(comment.get("created_at")) is str and
                  comment.get("created_at") == comment.get("updated_at"),
                  "R14_JOURNAL_SOURCE_NOT_TRUSTED")
        try:
            parsed = json.loads(body[len(prefix):-len(suffix)],
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except ValueError as exc:
            raise wire.EvidenceHeld("R14_JOURNAL_JSON_INVALID") from exc
        wire.need(type(parsed) is dict, "R14_JOURNAL_NOT_OBJECT")
        if parsed == r14:
            found.append(comment["id"])
    wire.need(len(found) == 1, "R14_ORIGINAL_JOURNAL_NOT_UNIQUELY_MATCHED")
    return found[0]


def corroborate(repo: str, pr: int, sha: str, gmed: dict, r14: dict,
                clavis: dict | None = None, *, get=None):
    wire.need(type(pr) is int and 0 < pr <= 1_000_000_000,
              "PULL_NUMBER_INVALID")
    initial = wire.correlate(repo, sha, gmed, r14, clavis)
    fetch = get or github_get
    root = "/repos/" + repo
    pull = one(fetch, root + "/pulls/" + str(pr))
    wire.need(pull.get("number") == pr and pull.get("merged") is True and
              pull.get("merge_commit_sha") == sha and
              type(pull.get("merged_at")) is str and
              (pull.get("base") or {}).get("ref") is not None and
              ((pull.get("base") or {}).get("repo") or {}).get("full_name") == repo,
              "LIVE_PR_MERGE_IDENTITY_HELD")
    base = pull["base"]["ref"]
    repository = one(fetch, root)
    wire.need(repository.get("full_name") == repo and
              repository.get("private") is False and
              repository.get("archived") is False and
              repository.get("disabled") is False and
              repository.get("default_branch") == base,
              "LIVE_REPOSITORY_IDENTITY_HELD")
    branch_path = root + "/branches/" + base
    branch = one(fetch, branch_path)
    wire.need((branch.get("commit") or {}).get("sha") == sha and
              type(branch.get("protected")) is bool,
              "LIVE_DEFAULT_BRANCH_MOVED_OR_UNKNOWN")
    check_runs = pages(fetch, root + "/commits/" + sha +
                       "/check-runs?filter=latest", "check_runs",
                       total_key="total_count")
    status_rows = pages(fetch, root + "/commits/" + sha + "/status",
                        "statuses")
    live_rows = ([normalize_live_check(x, sha) for x in check_runs] +
                 [normalize_live_status(x) for x in status_rows])
    wire.need(sorted_rows(live_rows) ==
              sorted_rows(normalized_gmed_rows(gmed["checks"])),
              "LIVE_CHECK_ROWS_DIFFER_FROM_GMED")
    wire.need(any(row["kind"] == "status" or
                  row["conclusion"] == "success" for row in live_rows),
              "LIVE_GITHUB_NO_SUCCESSFUL_CHECK")
    journal_id = r14_comment(fetch, r14)
    branch_again = one(fetch, branch_path)
    wire.need((branch_again.get("commit") or {}).get("sha") == sha,
              "SOURCE_DRIFT_DURING_GITHUB_CORROBORATION")
    return {
        "schema": SCHEMA,
        "state": "GITHUB_METADATA_CORROBORATED_REVIEW_ONLY",
        "target_repository": repo,
        "pr": pr,
        "source_sha": sha,
        "gmed_receipt_sha256": wire.digest(gmed),
        "r14_journal_sha256": wire.digest(r14),
        "r14_github_comment_id": journal_id,
        "check_run_count": len(check_runs),
        "legacy_status_count": len(status_rows),
        "default_branch_protected_observed": branch["protected"],
        "optional_clavis_attached": clavis is not None,
        "github_metadata_live_read": True,
        "r14_journal_observed_in_github": True,
        "r14_r13_qa_artifact_bytes_revalidated": False,
        "required_check_policy_verified": False,
        "independent_cryptographic_attestation": False,
        "formal_proof_checked": False,
        "independent_human_qa_complete": False,
        "model_routing_activated": False,
        "worker_dispatch_authorized": False,
        "code_write_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
        "prior_offline_receipt_state": initial["state"],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--sha", required=True)
    p.add_argument("--gmed", type=wire.Path, required=True)
    p.add_argument("--r14", type=wire.Path, required=True)
    p.add_argument("--clavis", type=wire.Path)
    args = p.parse_args(argv)
    try:
        result = corroborate(
            args.repo, args.pr, args.sha,
            wire.load_public_summary(args.gmed),
            wire.load_public_summary(args.r14),
            wire.load_public_summary(args.clavis) if args.clavis else None,
        )
    except (wire.EvidenceHeld, OSError, TypeError, ValueError,
            OverflowError, KeyError) as exc:
        p.exit(2, "PHI EVIDENCE LIVE HELD: " + str(exc) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
