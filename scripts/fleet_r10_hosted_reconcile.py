"""Reconcile GitHub-hosted R10 docs requests using existing R1 evidence checks.

This is NOT a new mission queue or owner-approval mechanism. It only considers
owner-authored issues bearing the original bot dispatch fence and a second,
bot-authored run link from the same one-shot dispatcher. It reuses R9->R1's
independent full-tree, exact-CI and recorded-merge verification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
import re
import sys

import autonomous_turn_contract as contract
import autonomous_turn_github as github
import fleet_r10_hosted_dispatch as hosted
import fleet_r10_r1 as r10

REPO = hosted.REPO
BOT_ID = hosted.BOT_ID
RUN_LINK_PREFIX = hosted.RUN_LINK_PREFIX
COMPLETE_PREFIX = "<!-- agentora-r10-hosted-verified-v1 issue="
MAX_ISSUES_PER_PASS = 10


def need(ok, reason):
    if not ok:
        raise hosted.Held(reason)


def _bot(row):
    return (isinstance(row, dict) and
            row.get("user", {}).get("id") == BOT_ID and
            row.get("user", {}).get("login") == "github-actions[bot]" and
            isinstance(row.get("body"), str))


def comments(client, issue_no):
    """Never trust incomplete comments: a missing fence/link is not absence."""
    found = []
    for page in range(1, hosted.MAX_PAGES + 1):
        rows = client.request(
            f"/issues/{issue_no}/comments?per_page={hosted.MAX_PAGE_SIZE}&page={page}")
        need(isinstance(rows, list) and len(rows) <= hosted.MAX_PAGE_SIZE,
             "R10_RECONCILE_COMMENT_PAGE_INVALID")
        found.extend(rows)
        if len(rows) < hosted.MAX_PAGE_SIZE:
            return found
    raise hosted.Held("R10_RECONCILE_COMMENT_HISTORY_INCOMPLETE")


def task_from_issue(issue):
    need(isinstance(issue.get("body"), str), "R10_RECONCILE_TASK_MISSING")
    task = contract.parse(issue["body"])
    # A historical successful run is valid even after the original task TTL.
    # Validate its immutable schema at a time strictly inside that TTL.
    created, expires = (contract.instant(task["created_utc"]),
                        contract.instant(task["expires_utc"]))
    historical_now = created + (expires - created) / 2
    hosted.checked_task(issue, historical_now)
    return task


def correlate_index(issue, comments_list):
    """Require precisely one genuine original fence and one original run link."""
    number = issue["number"]
    task = task_from_issue(issue)
    digest = contract.task_digest(task)
    fence = hosted.FENCE_PREFIX + str(number) + " -->"
    link = RUN_LINK_PREFIX + str(number) + " -->"
    fences = [r["body"] for r in comments_list if _bot(r) and
              r["body"].startswith(fence)]
    links = [r["body"] for r in comments_list if _bot(r) and
             r["body"].startswith(link)]
    need(len(fences) == 1, "R10_RECONCILE_FENCE_MISSING_OR_AMBIGUOUS")
    need(f"Task SHA-256: {digest}\n" in fences[0] + "\n",
         "R10_RECONCILE_FENCE_DIGEST_MISMATCH")
    if not links:
        return task, None
    need(len(links) == 1, "R10_RECONCILE_RUN_LINK_AMBIGUOUS")
    pattern = (re.escape(link) + r"\nTask SHA-256: ([0-9a-f]{64})\n"
               r"R1 run ID: ([1-9][0-9]{0,15})\n"
               r"Run URL: (https://github\.com/MichaelWave369/Agentora/actions/runs/[0-9]+)")
    matched = re.fullmatch(pattern, links[0])
    need(matched is not None and matched[1] == digest,
         "R10_RECONCILE_RUN_LINK_INVALID")
    run_id = int(matched[2])
    need(matched[3] == f"https://github.com/{REPO}/actions/runs/{run_id}",
         "R10_RECONCILE_RUN_URL_MISMATCH")
    return task, run_id


def verified_result(client, task, run_id):
    """Use existing R9/R1 evidence verifiers, not PR title or success alone."""
    api = github.GitHub(client.token)
    github.identity(api)
    run = api(github.BASE + f"/actions/runs/{run_id}")
    github.run_identity(run, task, run_id, task["source_sha"])
    if run.get("status") != "completed":
        return None  # An owner approval or CI job may still be pending.
    need(run.get("conclusion") == "success", "R10_RECONCILE_R1_NOT_SUCCESSFUL")
    jobs = r10.job_records(api, run_id, task)
    for name in r10.JOB_NAMES:
        need(r10.job_passed(jobs, name), "R10_RECONCILE_R1_REQUIRED_JOB_NOT_GREEN")
    authorized_at = contract.instant(jobs["owner-authorization"]["completed_at"])
    need(contract.instant(task["created_utc"]) <= authorized_at <
         contract.instant(task["expires_utc"]), "R10_RECONCILE_OWNER_REVIEW_EXPIRED")
    github.original_owner_review(api, task, run_id, task["source_sha"])
    r10.frozen_plan(api,
        lambda aid: r10.artifacts.download_artifact(aid, client.token),
        task, run_id)
    result, state, reason = r10.independent_result(api, task, run_id, jobs)
    need(state == "MERGED" and reason is None and
         type(result.get("pr_number")) is int and
         re.fullmatch(r"[0-9a-f]{40}", result.get("merge_sha", "")) and
         result.get("ci_status") == "PASSED",
         "R10_RECONCILE_MERGE_NOT_INDEPENDENTLY_VERIFIED")
    return result


def complete_body(number, task, run_id, verified):
    return (COMPLETE_PREFIX + str(number) + " -->\n"
            "Verified hosted R10 docs completion using the original R1 records.\n"
            f"Task SHA-256: {contract.task_digest(task)}\n"
            f"R1 run: https://github.com/{REPO}/actions/runs/{run_id}\n"
            f"Merged PR: https://github.com/{REPO}/pull/{verified['pr_number']}\n"
            f"Merge SHA: {verified['merge_sha']}\n"
            "State: VERIFIED_MERGED; this is not deployment or product acceptance.")


def reconcile_issue(client, issue, *, close_verified=False,
                    verify=verified_result):
    if not hosted.is_candidate(issue):
        return {"issue": issue.get("number"), "state": "IGNORED"}
    number = issue["number"]
    rows = comments(client, number)
    if not any(_bot(r) and r["body"].startswith(
            hosted.FENCE_PREFIX + str(number) + " -->") for r in rows):
        return {"issue": number, "state": "AWAITING_DISPATCH"}
    task, run_id = correlate_index(issue, rows)
    if run_id is None:
        return {"issue": number, "state": "HELD_NO_ORIGINAL_RUN_LINK"}
    verified = verify(client, task, run_id)
    if verified is None:
        return {"issue": number, "state": "AWAITING_R1_COMPLETION",
                "run_id": run_id}
    summary = {"issue": number, "state": "VERIFIED_MERGED",
               "run_id": run_id, "pr_number": verified["pr_number"],
               "merge_sha": verified["merge_sha"]}
    if not close_verified:
        return summary

    # Re-read issue identity and immutable body before any write.
    latest = client.request(f"/issues/{number}")
    need(hosted.is_candidate(latest) and latest.get("id") == issue.get("id")
         and latest.get("body") == issue.get("body"),
         "R10_RECONCILE_ISSUE_CHANGED_BEFORE_WRITE")
    latest_rows = comments(client, number)
    latest_task, latest_run_id = correlate_index(latest, latest_rows)
    need(latest_run_id == run_id and
         contract.task_digest(latest_task) == contract.task_digest(task),
         "R10_RECONCILE_INDEX_CHANGED_BEFORE_WRITE")
    expected = complete_body(number, task, run_id, verified)
    completions = [r["body"] for r in latest_rows if _bot(r) and
                   r["body"].startswith(COMPLETE_PREFIX + str(number) + " -->")]
    need(not completions or completions == [expected],
         "R10_RECONCILE_COMPLETION_CONFLICT")
    if not completions:
        written = client.request(f"/issues/{number}/comments",
                                 payload={"body": expected})
        need(type(written.get("id")) is int and written["id"] > 0,
             "R10_RECONCILE_COMPLETION_COMMENT_UNCONFIRMED")
    # PATCH only this already-verified issue; never alter a PR or ruleset.
    api = github.GitHub(client.token)
    closed = api(github.BASE + f"/issues/{number}",
                 {"state": "closed", "state_reason": "completed"}, method="PATCH")
    need(closed.get("number") == number and closed.get("state") == "closed" and
         closed.get("state_reason") == "completed",
         "R10_RECONCILE_CLOSE_NOT_CONFIRMED")
    summary["state"] = "CLOSED_VERIFIED"
    return summary


def reconcile_pass(client, *, close_verified=False, verify=verified_result):
    results = []
    for issue in hosted.open_issues(client):
        if not hosted.is_candidate(issue):
            continue
        if len(results) >= MAX_ISSUES_PER_PASS:
            raise hosted.Held("R10_RECONCILE_ISSUE_BUDGET_EXCEEDED")
        try:
            results.append(reconcile_issue(client, issue,
                close_verified=close_verified, verify=verify))
        except (hosted.Held, contract.Held, r10.artifacts.CloudReviewHeld) as exc:
            results.append({"issue": issue["number"], "state": "HELD",
                            "reason": re.sub(r"[^A-Z0-9_]", "_", str(exc))[:100]})
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--close-verified", action="store_true")
    args = parser.parse_args(argv)
    try:
        output = reconcile_pass(hosted.GitHubAPI(os.getenv("GITHUB_TOKEN")),
                                close_verified=args.close_verified)
        print(json.dumps({"schema": "agentora.r10-hosted-reconcile.v1",
                          "mode": "close_verified" if args.close_verified else "observe",
                          "results": output}, sort_keys=True))
        return 3 if any(r["state"] == "HELD" for r in output) else 0
    except (hosted.Held, contract.Held, r10.artifacts.CloudReviewHeld) as exc:
        print("R10_HOSTED_RECONCILE_HELD " +
              re.sub(r"[^A-Z0-9_]", "_", str(exc))[:100], file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
