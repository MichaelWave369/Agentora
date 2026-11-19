"""GitHub-hosted, docs-only R1 dispatch bridge.

This is a bounded transport pilot, NOT a replacement for Agentora's R9 SQLite
mission queue. It consumes owner-authored public task issues and persists its
one-shot dispatch fence in an original GitHub bot comment before the API POST.
The existing R1 workflow remains responsible for owner approval and merging.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

import autonomous_turn_contract as contract
import autonomous_turn_github as github

REPO = "MichaelWave369/Agentora"
REPO_ID = 1167870912
OWNER_ID = 247459237
BOT_ID = 41898282
TITLE_PREFIX = "Fleet R10 docs request:"
FENCE_PREFIX = "<!-- agentora-r10-hosted-dispatch-v1 issue="
RUN_LINK_PREFIX = "<!-- agentora-r10-hosted-run-v1 issue="
API_ROOT = "https://api.github.com/repos/" + REPO
DISPATCH = "/actions/workflows/autonomous-turn-r1.yml/dispatches"
MAX_PAGES = 5
MAX_PAGE_SIZE = 100
MAX_BODY = 32768


class Held(ValueError):
    pass


def need(test, code):
    if not test:
        raise Held(code)


class GitHubAPI:
    def __init__(self, token):
        need(isinstance(token, str) and len(token) > 0, "R10_HOSTED_GITHUB_TOKEN_REQUIRED")
        self.token = token

    def request(self, path, *, payload=None):
        # The endpoint is intentionally fixed to this repository.
        need(path.startswith("/") and ".." not in path and "//" not in path,
             "R10_HOSTED_UNSAFE_API_PATH")
        data = None if payload is None else json.dumps(
            payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        need(data is None or len(data) < 40000, "R10_HOSTED_PAYLOAD_TOO_LARGE")
        req = Request(API_ROOT + path, data=data, method="GET" if data is None else "POST",
                      headers={"Authorization": "Bearer " + self.token,
                               "Accept": "application/vnd.github+json",
                               "Content-Type": "application/json",
                               "X-GitHub-Api-Version": "2026-03-10",
                               "User-Agent": "Agentora-R10-Hosted"})
        try:
            with build_opener(github.NoRedirect()).open(req, timeout=20) as response:
                if response.status == 204:
                    return {"status": 204}
                expected = 200 if data is None or path == DISPATCH else 201
                need(response.status == expected, "R10_HOSTED_GITHUB_HTTP_UNEXPECTED")
                raw = response.read(512000 + 1)
                need(len(raw) <= 512000, "R10_HOSTED_GITHUB_RESPONSE_TOO_LARGE")
                return json.loads(raw)
        except HTTPError as exc:
            raise Held("R10_HOSTED_GITHUB_HTTP_" + str(exc.code)) from None
        except (URLError, OSError, ValueError):
            raise Held("R10_HOSTED_GITHUB_UNAVAILABLE") from None


def open_issues(client):
    """Exhaust a bounded issue window: truncated inventory is a HOLD."""
    found = []
    for page in range(1, MAX_PAGES + 1):
        rows = client.request(
            f"/issues?state=open&per_page={MAX_PAGE_SIZE}&page={page}&direction=asc")
        need(isinstance(rows, list) and len(rows) <= MAX_PAGE_SIZE,
             "R10_HOSTED_ISSUE_PAGE_INVALID")
        found.extend(rows)
        if len(rows) < MAX_PAGE_SIZE:
            return found
    raise Held("R10_HOSTED_ISSUE_LIST_INCOMPLETE")


def is_candidate(issue):
    return (isinstance(issue, dict) and issue.get("state") == "open"
            and issue.get("repository_url") == API_ROOT
            and issue.get("user", {}).get("id") == OWNER_ID
            and issue.get("user", {}).get("login") == "MichaelWave369"
            and isinstance(issue.get("title"), str)
            and issue["title"].startswith(TITLE_PREFIX)
            and "pull_request" not in issue
            and type(issue.get("number")) is int
            and issue["number"] > 0)


def existing_fence(client, issue_no):
    """A trusted original comment is a non-repeatable dispatch fence."""
    fence = FENCE_PREFIX + str(issue_no) + " -->"
    for page in range(1, MAX_PAGES + 1):
        rows = client.request(
            f"/issues/{issue_no}/comments?per_page={MAX_PAGE_SIZE}&page={page}")
        need(isinstance(rows, list) and len(rows) <= MAX_PAGE_SIZE,
             "R10_HOSTED_COMMENT_PAGE_INVALID")
        for comment in rows:
            if (comment.get("user", {}).get("id") == BOT_ID
                    and comment.get("user", {}).get("login") == "github-actions[bot]"
                    and isinstance(comment.get("body"), str)
                    and comment["body"].startswith(fence)):
                return True
        if len(rows) < MAX_PAGE_SIZE:
            return False
    raise Held("R10_HOSTED_COMMENT_HISTORY_INCOMPLETE")


def checked_task(issue, now):
    raw = issue.get("body")
    need(isinstance(raw, str) and 0 < len(raw.encode("utf-8")) <= MAX_BODY,
         "R10_HOSTED_TASK_BODY_INVALID")
    task = contract.parse(raw)
    contract.validate(task, now=now)
    need(task["repository"] == REPO and task["repository_id"] == REPO_ID
         and task["target_branch"] == "main" and task["merge_policy"] == "docs"
         and task["max_repairs"] == 0 and len(task["allowed_paths"]) == 1
         and task["max_files"] == 1
         and all(github.devloop.is_doc(p) for p in task["allowed_paths"]),
         "R10_HOSTED_TASK_SCOPE_UNSAFE")
    return task


def preflight_task(client, task):
    # The API client used here is read-only. The original R1 plan, worker,
    # owner gate and merge gate independently revalidate after dispatch.
    source = github.GitHub(client.token)
    github.identity(source)
    need(github.main_head(source) == task["source_sha"], "R10_HOSTED_SOURCE_DRIFT")
    contract.proposal(task, github.source_files(source, task), 0)


def dispatch_one(client, *, dry_run=False, now=None, preflight=preflight_task):
    now = now or datetime.now(timezone.utc)
    need(now.tzinfo is not None, "R10_HOSTED_CLOCK_INVALID")
    for issue in open_issues(client):
        if not is_candidate(issue):
            continue
        issue_no = issue["number"]
        # Read the durable fence BEFORE considering the potentially edited body.
        if existing_fence(client, issue_no):
            continue
        try:
            task = checked_task(issue, now)
            preflight(client, task)
        except (Held, contract.Held) as exc:
            # An invalid/expired/stale owner request is never dispatched.
            # Continue to the next issue instead of creating a silent green.
            print("R10_HOSTED_SKIPPED issue=" + str(issue_no) +
                  " reason=" + re.sub(r"[^A-Z0-9_]", "_", str(exc))[:100], flush=True)
            continue

        digest = contract.task_digest(task)
        if dry_run:
            return {"state": "ELIGIBLE_NOT_DISPATCHED", "issue": issue_no,
                    "task_sha256": digest, "owner_review_required": True}
        body = (FENCE_PREFIX + str(issue_no) + " -->\n"
                "Dispatch intent durably recorded BEFORE contacting Actions.\n"
                "Task SHA-256: " + digest + "\n"
                "State: SUBMISSION_UNCERTAIN until original R1 run is independently checked.\n"
                "Never repeat this task automatically if GitHub's response is lost.\n"
                "This comment is NOT owner authorization, execution, CI or merge evidence.")
        result = client.request(f"/issues/{issue_no}/comments", payload={"body": body})
        need(isinstance(result, dict) and type(result.get("id")) is int,
             "R10_HOSTED_FENCE_CONFIRMATION_MISSING")
        # From here on, NO automatic retry of the POST is permitted.
        payload = {"ref": "main", "return_run_details": True,
                   "inputs": {"task_json": contract.canonical(task).decode("utf-8")}}
        response = client.request(DISPATCH, payload=payload)
        run_id = response.get("workflow_run_id")
        if type(run_id) is int and run_id > 0:
            need(response.get("html_url") ==
                 f"https://github.com/{REPO}/actions/runs/{run_id}" and
                 response.get("run_url") ==
                 f"{API_ROOT}/actions/runs/{run_id}",
                 "R10_HOSTED_RUN_IDENTITY_INVALID")
            # The original fence remains the one-shot authority against replay.
            # This second bot-authored link is a durable INDEX, never approval.
            # If the link response is lost, do not retry the original dispatch.
            link = (RUN_LINK_PREFIX + str(issue_no) + " -->\n"
                    "Task SHA-256: " + digest + "\n"
                    "R1 run ID: " + str(run_id) + "\n"
                    "Run URL: " + response["html_url"])
            linked = client.request(f"/issues/{issue_no}/comments",
                                    payload={"body": link})
            need(isinstance(linked, dict) and type(linked.get("id")) is int
                 and linked["id"] > 0, "R10_HOSTED_RUN_LINK_UNCONFIRMED")
            return {"state": "FENCED_DISPATCH_ACCEPTED_RUN_IDENTIFIED",
                    "issue": issue_no, "task_sha256": digest,
                    "workflow_run_id": run_id, "run_link_comment_id": linked["id"],
                    "run_url": response["html_url"], "owner_review_required": True}
        need(response.get("status") == 204, "R10_HOSTED_DISPATCH_UNCONFIRMED")
        return {"state": "FENCED_DISPATCH_ACCEPTED_RUN_UNCONFIRMED",
                "issue": issue_no, "task_sha256": digest,
                "owner_review_required": True}
    return {"state": "NO_ELIGIBLE_UNFENCED_TASK", "owner_review_required": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = dispatch_one(GitHubAPI(os.getenv("GITHUB_TOKEN")), dry_run=args.dry_run)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Held, contract.Held) as exc:
        print("R10_HOSTED_HELD " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
