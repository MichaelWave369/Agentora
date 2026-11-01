"""R2.2 GitHub-native, read-only queue snapshot.

The queue is an *advisory*. It never sends POST/PUT/PATCH/DELETE, reads
credentials from PR content, checks out PR heads, applies labels, or merges.
The existing trusted devloop gate alone decides whether a merge is permitted.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from devloop_r2_policy import (
    CodeHeld, OWNER, REPO, HOLDS, LOW_RISK_UI,
    classify_files, require_independent_review,
)

REQUIRED = ("backend (3.12)", "backend (3.13)", "web")
LABELS = {
    "docs": "phi-automerge",
    "solo": "phi-solo-automerge",
    "reviewed": "phi-code-automerge",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
MAX_PAGES = 3
PAGE_SIZE = 100


class QueueHeld(Exception):
    """Evidence is unavailable or incomplete; never treat it as authorization."""


def github_get(token: str, path: str):
    if not isinstance(path, str) or not path.startswith("/repos/" + REPO + "/"):
        raise QueueHeld("R22_UNEXPECTED_API_PATH")
    if not token:
        raise QueueHeld("R22_READ_TOKEN_MISSING")
    req = Request(
        "https://api.github.com" + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentora-devloop-r22-readonly",
        },
        method="GET",
    )
    try:
        with urlopen(req, timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        raise QueueHeld("R22_GITHUB_READ_UNAVAILABLE") from None


def load_open_prs(get, token):
    rows = []
    for page in range(1, MAX_PAGES + 1):
        batch = get(
            token, f"/repos/{REPO}/pulls?state=open&per_page={PAGE_SIZE}&page={page}"
        )
        if not isinstance(batch, list) or len(batch) > PAGE_SIZE:
            raise QueueHeld("R22_PR_LIST_MALFORMED")
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
    # At maximum bound, no proof that more pages don't exist.
    raise QueueHeld("R22_PR_LIST_LIMIT_EXCEEDED")


def verify_main_rules(get, token):
    rows = get(token, f"/repos/{REPO}/rulesets?includes_parents=true")
    if not isinstance(rows, list) or len(rows) >= 100:
        raise QueueHeld("R22_RULESET_LIST_INCOMPLETE")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("enforcement") != "active":
            continue
        rid = row.get("id")
        if type(rid) is not int:
            raise QueueHeld("R22_RULESET_ID_INVALID")
        detail = get(token, f"/repos/{REPO}/rulesets/{rid}")
        if not isinstance(detail, dict):
            raise QueueHeld("R22_RULESET_DETAIL_INVALID")
        if detail.get("target") != "branch" or detail.get("enforcement") != "active":
            continue
        include = ((detail.get("conditions") or {}).get("ref_name") or {}).get("include") or []
        if not isinstance(include, list) or not set(include) & {
            "~DEFAULT_BRANCH", "main", "refs/heads/main"
        }:
            continue
        for rule in detail.get("rules") or []:
            if rule.get("type") == "required_status_checks":
                seen.update(
                    c.get("context") for c in
                    ((rule.get("parameters") or {}).get("required_status_checks") or [])
                    if isinstance(c, dict)
                )
    return set(REQUIRED).issubset(seen)


def check_summary(get, token, sha):
    if not isinstance(sha, str) or not HEX40.fullmatch(sha):
        return {"state": "UNVERIFIED", "reason": "INVALID_HEAD_SHA", "checks": {}}
    response = get(token, f"/repos/{REPO}/commits/{sha}/check-runs?per_page=100")
    if (not isinstance(response, dict) or
            type(response.get("total_count")) is not int or
            response["total_count"] >= 100 or
            not isinstance(response.get("check_runs"), list) or
            len(response["check_runs"]) != response["total_count"]):
        return {"state": "UNVERIFIED", "reason": "CHECK_EVIDENCE_INCOMPLETE", "checks": {}}
    statuses = {name: [] for name in REQUIRED}
    for check in response["check_runs"]:
        if not isinstance(check, dict):
            return {"state": "UNVERIFIED", "reason": "BAD_CHECK_RECORD", "checks": {}}
        name = check.get("name")
        if name in statuses:
            if (check.get("app") or {}).get("slug") != "github-actions":
                return {"state": "UNVERIFIED", "reason": "WRONG_CHECK_SOURCE", "checks": {}}
            statuses[name].append(check)
    summary = {}
    for name, items in statuses.items():
        if not items:
            summary[name] = "MISSING"
        elif any(item.get("status") != "completed" for item in items):
            summary[name] = "PENDING"
        elif any(item.get("conclusion") != "success" for item in items):
            summary[name] = "FAILED"
        else:
            summary[name] = "GREEN"
    state = ("GREEN" if all(v == "GREEN" for v in summary.values())
             else "FAILED" if "FAILED" in summary.values()
             else "PENDING" if "PENDING" in summary.values()
             else "MISSING")
    return {"state": state, "checks": summary}


def docs_candidate(pr, files):
    if (pr.get("changed_files") != len(files) or not 1 <= len(files) <= 10):
        return False
    for f in files:
        if not isinstance(f, dict) or f.get("status") not in ("modified", "added"):
            return False
        name = f.get("filename")
        if not isinstance(name, str) or len(name) > 240:
            return False
        if name == "README.md":
            continue
        segments = name.split("/")
        if (len(segments) < 2 or segments[0] != "docs" or
                not name.endswith(".md") or
                any(x in ("", ".", "..") for x in segments)):
            return False
    return True


def classify_candidate(pr, files):
    if not isinstance(pr, dict) or pr.get("state") != "open":
        return "manual", "NOT_OPEN"
    if pr.get("draft") is not False:
        return "manual", "DRAFT"
    base, head = pr.get("base") or {}, pr.get("head") or {}
    if (base.get("ref") != "main" or (base.get("repo") or {}).get("full_name") != REPO
            or (head.get("repo") or {}).get("full_name") != REPO):
        return "manual", "FORK_OR_OTHER_BASE"
    if docs_candidate(pr, files):
        return "docs", "DOCS_ONLY"
    try:
        result = classify_files(files)
    except CodeHeld:
        return "manual", "CODE_OUT_OF_SCOPE"
    if pr.get("changed_files") != len(files):
        return "manual", "FILE_LIST_MISMATCH"
    if (pr.get("user") or {}).get("login") == OWNER and result["paths"] == [
        "web/src/components/Nav.tsx"
    ] and len(files) == 1 and result["additions"] <= 10 and (
        result["deletions"] <= 10 and result["additions"] + result["deletions"] <= 16
    ):
        return "solo", "ONE_TINY_OWNER_UI_FILE"
    return "reviewed", "SMALL_UI_REQUIRES_INDEPENDENT_REVIEW"


def review_advisory(get, token, pr):
    number = pr.get("number")
    sha = (pr.get("head") or {}).get("sha")
    author = (pr.get("user") or {}).get("login")
    try:
        reviewers = require_independent_review(
            lambda token, path, payload=None, method=None: get(token, path),
            token, number, sha, author,
        )
        return {"status": "VERIFIED", "reviewers": reviewers}
    except CodeHeld as exc:
        return {"status": "NOT_VERIFIED", "reason": str(exc)[:70]}


def evaluate(pr, files, checks, rules_present, review=None):
    number = pr.get("number")
    head_sha = (pr.get("head") or {}).get("sha")
    if type(number) is not int or number < 1:
        raise QueueHeld("R22_INVALID_PR_ID")
    if not isinstance(head_sha, str) or not HEX40.fullmatch(head_sha):
        raise QueueHeld("R22_INVALID_PR_SHA")
    lane, detail = classify_candidate(pr, files)
    raw_labels = pr.get("labels") or []
    if not isinstance(raw_labels, list) or any(not isinstance(z, dict) for z in raw_labels):
        raise QueueHeld("R22_INVALID_PR_LABELS")
    labels = {str(x.get("name", "")).lower() for x in raw_labels}
    authorization_label = LABELS.get(lane)
    row = {
        "number": number,
        "title": str(pr.get("title") or "(untitled)")[:180],
        "url": f"https://github.com/{REPO}/pull/{number}",
        "head_sha": head_sha,
        "author": (pr.get("user") or {}).get("login"),
        "lane": lane,
        "risk": ("DOCS_SCOPE" if lane == "docs" else
                 "BOUNDED_OWNER_UI_NOT_SECURITY_REVIEWED" if lane == "solo" else
                 "SMALL_UI_REVIEW_REQUIRED" if lane == "reviewed" else
                 "MANUAL_OR_UNCLASSIFIED"),
        "classification": detail,
        "ci": checks,
        "rules_verified": rules_present,
        "label_present": authorization_label in labels if authorization_label else False,
        "review": review if lane == "reviewed" else None,
        "authorization_granted": False,
        "merge_authorized": False,
    }
    if lane == "manual":
        row["status"], row["next_action"] = "OUT_OF_SCOPE", "Manual review and merge; no auto-label"
    elif HOLDS & labels or len(set(LABELS.values()) & labels) > 1:
        row["status"], row["next_action"] = "HELD", "Resolve hold/conflicting labels and re-review"
    elif not rules_present:
        row["status"], row["next_action"] = "RULES_UNVERIFIED", "Verify active main-branch required checks"
    elif checks.get("state") != "GREEN":
        row["status"] = "CI_" + str(checks.get("state", "UNVERIFIED"))
        row["next_action"] = "Inspect and repair/wait for CI; do not authorize yet"
    elif lane == "reviewed" and (review or {}).get("status") != "VERIFIED":
        row["status"], row["next_action"] = "REVIEW_REQUIRED", "Obtain verified independent collaborator approval"
    elif row["label_present"]:
        row["status"], row["next_action"] = "AUTHORIZED_EVENT_PENDING", "Inspect governance run and receipt; never blindly reapply"
    else:
        row["status"] = "OWNER_REVIEW_REQUIRED"
        row["next_action"] = (
            "Review Files changed and exact SHA; owner may then apply " + authorization_label
        )
    return row


def snapshot(get, token):
    rules_present = verify_main_rules(get, token)
    prs = load_open_prs(get, token)
    rows = []
    for pr in prs:
        if not isinstance(pr, dict):
            raise QueueHeld("R22_INVALID_PR_RECORD")
        number = pr.get("number")
        sha = (pr.get("head") or {}).get("sha")
        if type(number) is not int or number < 1:
            raise QueueHeld("R22_INVALID_PR_ID")
        count = pr.get("changed_files")
        # Pull collection can omit changed_files. Fetch detail for exact metadata.
        detail = get(token, f"/repos/{REPO}/pulls/{number}")
        if not isinstance(detail, dict) or detail.get("number") != number:
            raise QueueHeld("R22_PR_DETAILS_INVALID")
        count = detail.get("changed_files")
        if type(count) is not int or count < 0:
            raise QueueHeld("R22_PR_FILE_COUNT_INVALID")
        files = []
        if 1 <= count <= 10:
            files = get(token, f"/repos/{REPO}/pulls/{number}/files?per_page=100")
            if not isinstance(files, list) or len(files) != count:
                raise QueueHeld("R22_PR_DIFF_INCOMPLETE")
        checks = check_summary(get, token, (detail.get("head") or {}).get("sha"))
        lane, _ = classify_candidate(detail, files)
        review = review_advisory(get, token, detail) if lane == "reviewed" else None
        rows.append(evaluate(detail, files, checks, rules_present, review))
    return {
        "schema": "agentora.devloop.review-queue.v2.2",
        "repository": REPO,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_ADVISORY_NOT_MERGE_AUTHORITY",
        "rules_verified": rules_present,
        "open_pr_count": len(rows),
        "rows": rows,
        "can_merge": False,
    }


def md_escape(value):
    text = str(value).replace("\n", " ").replace("\r", " ")
    for char in ("\\", "|", "<", ">", "[", "]", "`", "*", "_"):
        text = text.replace(char, "\\" + char)
    return text[:220]


def markdown(data):
    lines = [
        "# Φ Agentora · Solo Sovereign Review Queue",
        "",
        "**Read-only snapshot. Not a permission grant or a GitHub merge status.** "
        "Every candidate needs human diff review and a fresh authorization label "
        "event in its own PR.",
        "",
        f"Snapshot (UTC): {md_escape(data.get('captured_utc', 'unknown'))}",
        f"Active three-check main ruleset: {'verified' if data.get('rules_verified') else 'NOT VERIFIED'}",
        f"Open PRs examined: {data.get('open_pr_count', 0)}",
        "",
    ]
    if data.get("error"):
        lines.extend([f"**Queue held:** {md_escape(data['error'])}", ""])
    rows = data.get("rows") or []
    if rows:
        lines += [
            "| PR | Lane / scope | Checks | Queue status | Next action |",
            "|---|---|---|---|---|",
        ]
        for row in rows:
            checks = row["ci"].get("state", "UNVERIFIED")
            lines.append(
                f"| [#{row['number']}]({row['url']}) {md_escape(row['title'])} | "
                f"{md_escape(row['lane'])} · {md_escape(row['risk'])} | "
                f"{md_escape(checks)} | {md_escape(row['status'])} | "
                f"{md_escape(row['next_action'])} |"
            )
        lines += ["", "### Exact heads"]
        for row in rows:
            lines.append(
                f"- [#{row['number']}]({row['url']}): \`{row['head_sha']}\` "
                f"({md_escape(row['classification'])})"
            )
    else:
        lines.append("**No open PRs in this bounded snapshot.**")
    lines += [
        "",
        "The queue never labels or merges PRs. It is a point-in-time advisory, "
        "not a live approval. Open the PR's **Files changed** tab and Actions "
        "checks before making a decision.",
        "",
    ]
    return "\n".join(lines)


def main():
    output = {
        "schema": "agentora.devloop.review-queue.v2.2",
        "repository": REPO, "mode": "READ_ONLY_ADVISORY_NOT_MERGE_AUTHORITY",
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "rows": [], "open_pr_count": 0, "can_merge": False,
    }
    rc = 0
    try:
        output = snapshot(github_get, os.environ["GH_TOKEN"])
        print("R22_REVIEW_QUEUE_SNAPSHOT open_prs=" + str(output["open_pr_count"]))
    except (QueueHeld, CodeHeld, KeyError, ValueError, TypeError, OSError) as exc:
        output["error"] = str(exc) if isinstance(exc, (QueueHeld, CodeHeld)) else "R22_INVALID_RUNTIME"
        print("::error::R22_REVIEW_QUEUE_HELD " + output["error"], file=sys.stderr)
        rc = 1
    finally:
        Path("devloop-artifacts").mkdir(exist_ok=True)
        Path("devloop-artifacts/review-queue.json").write_text(
            json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write(markdown(output))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
