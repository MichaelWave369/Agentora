"""Pilot CI observer: one public PhiMadaPrime workflow -> Agentora Issue #124.

This is status reporting only, never a code writer, worker dispatcher, release
approver or merge authority. No target-code checkout or model execution.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

HOME = "MichaelWave369/Agentora"
TARGET = "MichaelWave369/PhiMadaPrime"
TARGET_ID = 1443845098
OWNER_ID = 247459237
ISSUE = 124
BRANCH = "main"
WORKFLOW = ".github/workflows/ci.yml"
MARKER = "<!-- agentora-pitcrew-ci-watch-r1 PhiMadaPrime ci.yml issue-124 -->"
ISSUE_TITLE = "Fleet R10: connect existing RepoNerve"
SHA = re.compile(r"[0-9a-f]{40}\Z")
API = "https://api.github.com"


class Held(RuntimeError):
    """Missing or conflicting evidence must not be silently promoted."""


def need(condition, reason):
    if not condition:
        raise Held(reason)


def github(method, path, token, payload=None):
    need(path.startswith("/repos/") and not path.startswith("//"),
         "API_PATH_NOT_ALLOWLISTED")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        API + path, data=data, method=method,
        headers={"Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Authorization": "Bearer " + token,
                 "User-Agent": "agentora-pitcrew-ci-watch-r1",
                 **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read(300_001)
            need(len(raw) <= 300_000, "API_RESPONSE_OVERSIZED")
            return json.loads(raw) if raw else {}
    except (urllib.error.URLError, ValueError) as exc:
        raise Held("GITHUB_API_UNAVAILABLE") from exc


def safe_name(value):
    if not isinstance(value, str):
        return "unavailable"
    return "".join(c if (c.isascii() and (c.isalnum() or c in " ._-/():"))
                   else "?" for c in value)[:90]


def observe(get):
    repo = get("/repos/" + TARGET)
    need(isinstance(repo, dict) and repo.get("id") == TARGET_ID
         and repo.get("full_name") == TARGET and repo.get("private") is False
         and repo.get("archived") is False
         and repo.get("default_branch") == BRANCH,
         "TARGET_IDENTITY_OR_BRANCH_CHANGED")
    branch = get("/repos/" + TARGET + "/branches/" + BRANCH)
    head = (branch.get("commit") or {}).get("sha") if isinstance(branch, dict) else None
    need(isinstance(head, str) and SHA.fullmatch(head), "MAIN_HEAD_UNAVAILABLE")
    path = ("/repos/" + TARGET + "/actions/workflows/ci.yml/runs"
            "?branch=main&event=push&per_page=30")
    result = get(path)
    need(isinstance(result, dict)
         and isinstance(result.get("workflow_runs"), list)
         and isinstance(result.get("total_count"), int)
         and len(result["workflow_runs"]) <= 30,
         "RUN_LIST_UNAVAILABLE")
    matching = [r for r in result["workflow_runs"]
                if isinstance(r, dict) and r.get("head_sha") == head
                and r.get("head_branch") == BRANCH and r.get("event") == "push"
                and r.get("path", "").split("@")[0] == WORKFLOW
                and type(r.get("id")) is int and r["id"] > 0
                and type(r.get("run_attempt")) is int and r["run_attempt"] > 0]
    if not matching:
        return {"state": "NO_EXACT_HEAD_CI", "head_sha": head,
                "run_id": None, "run_attempt": None, "failed_jobs": []}
    run = max(matching, key=lambda r: (r["id"], r["run_attempt"]))
    status, conclusion = run.get("status"), run.get("conclusion")
    if status != "completed":
        state = "CI_PENDING_EXACT_HEAD"
    elif conclusion == "success":
        state = "CI_SUCCESS_EXACT_HEAD"
    elif conclusion in ("failure", "timed_out"):
        state = "CI_FAILURE_EXACT_HEAD"
    else:
        state = "CI_INCONCLUSIVE_EXACT_HEAD"
    failed = []
    if state == "CI_FAILURE_EXACT_HEAD":
        # Details are advisory; a readable run outcome remains authoritative.
        try:
            jobs = get("/repos/" + TARGET + "/actions/runs/"
                       + str(run["id"]) + "/jobs?per_page=100")
            if (isinstance(jobs, dict) and type(jobs.get("total_count")) is int
                    and 0 <= jobs["total_count"] <= 100
                    and isinstance(jobs.get("jobs"), list)
                    and len(jobs["jobs"]) == jobs["total_count"]):
                failed = [safe_name(j.get("name"))
                          for j in jobs["jobs"] if isinstance(j, dict)
                          and j.get("conclusion") in ("failure", "timed_out")][:12]
        except Held:
            pass
    return {"state": state, "head_sha": head,
            "run_id": run["id"], "run_attempt": run["run_attempt"],
            "failed_jobs": failed}


def ensure_head_unchanged(get, report):
    """Recheck target main immediately before writing the status comment.

    A branch can still move *after* this read; the periodic observer corrects
    the snapshot on its next run. This check closes the ordinary read/write
    window without pretending to provide GitHub-level atomicity.
    """
    need(isinstance(report, dict)
         and isinstance(report.get("head_sha"), str)
         and SHA.fullmatch(report["head_sha"]),
         "OBSERVED_HEAD_INVALID")
    branch = get("/repos/" + TARGET + "/branches/" + BRANCH)
    current = (branch.get("commit") or {}).get("sha") if isinstance(branch, dict) else None
    need(current == report["head_sha"], "MAIN_CHANGED_DURING_OBSERVATION")


def review_candidate(report):
    """Construct one inert, replay-stable failure review handoff.

    A CI failure alone is not a diagnosis, a RepoNerve event, an R9 mission,
    or an approval to run code. The dedupe key is a *local identity*, not an
    authenticated GitHub receipt, signature, or cross-run lock.
    """
    need(isinstance(report, dict), "CANDIDATE_REPORT_INVALID")
    if report.get("state") != "CI_FAILURE_EXACT_HEAD":
        return None
    head = report.get("head_sha")
    run_id = report.get("run_id")
    attempt = report.get("run_attempt")
    jobs = report.get("failed_jobs")
    need(isinstance(head, str) and SHA.fullmatch(head)
         and type(run_id) is int and run_id > 0
         and type(attempt) is int and 0 < attempt <= 10000
         and type(jobs) is list and len(jobs) <= 12
         and all(type(job) is str and job == safe_name(job)
                 and len(job) <= 90 for job in jobs),
         "CANDIDATE_EVIDENCE_INVALID")
    origin = {
        "target_repository": TARGET, "target_repo_id": TARGET_ID,
        "default_branch": BRANCH, "source_sha": head,
        "workflow": WORKFLOW, "source_run_id": run_id,
        "source_run_attempt": attempt
    }
    material = json.dumps(origin, sort_keys=True, separators=(",", ":")).encode()
    return {
        "schema": "agentora.pitcrew.failure-review-candidate.v1",
        "state": "NEEDS_REVIEW_NO_WORKER",
        **origin,
        "dedupe_key": "sha256:" + hashlib.sha256(material).hexdigest(),
        "source_run_url": ("https://github.com/" + TARGET
                           + "/actions/runs/" + str(run_id)),
        "failed_jobs_advisory": jobs,
        "canonical_mission_issue": ISSUE,
        "recommended_next_action": "Inspect the failed CI run and prepare a separately authorized bounded task in existing Agentora R9 / Autonomous R1. No remediation is authorized by this receipt.",
        "source_authenticated_independently": False,
        "cause_identified": False,
        "worker_started": False,
        "independent_qa_complete": False,
        "repair_authorized": False,
        "dispatch_authorized": False,
        "merge_authorized": False,
        "verified_complete": False
    }


def render(report):
    state = report["state"]
    run_id = report["run_id"]
    lines = [MARKER, "### Φ Pit Crew R1 | PhiMadaPrime CI", "",
             "**" + state + "** (observation only, not a release or playtest).",
             "",
             "- Repository: `" + TARGET + "`",
             "- Workflow: `" + WORKFLOW + "` on `main`",
             "- Exact observed main SHA: `" + report["head_sha"] + "`"]
    if run_id:
        lines += ["- GitHub Actions: [run " + str(run_id) + "]("
                  + "https://github.com/" + TARGET + "/actions/runs/"
                  + str(run_id) + "), attempt " + str(report["run_attempt"])]
    else:
        lines.append("- Run: no qualifying CI run found for this exact head")
    if report["failed_jobs"]:
        lines.append("- Failed jobs (advisory): "
                     + ", ".join("`" + name + "`" for name in report["failed_jobs"]))
    lines += ["", "This comment is a single, deduplicated status surface on the "
              "existing [fleet mission #124](https://github.com/" + HOME +
              "/issues/124). It does not enqueue a worker, authorize a code "
              "change, certify independent QA, merge a PR, or confirm deployment.",
              "A passing CI run is not proof that the product works in VR or on devices."]
    return "\n".join(lines) + "\n"


def publish(get, send, report):
    issue = get("/repos/" + HOME + "/issues/" + str(ISSUE))
    need(isinstance(issue, dict) and issue.get("number") == ISSUE
         and issue.get("state") == "open" and "pull_request" not in issue
         and issue.get("title", "").startswith(ISSUE_TITLE)
         and (issue.get("user") or {}).get("id") == OWNER_ID,
         "CANONICAL_MISSION_CHANGED")
    comments = get("/repos/" + HOME + "/issues/" + str(ISSUE)
                   + "/comments?per_page=100")
    need(isinstance(comments, list) and len(comments) < 100,
         "COMMENT_LIST_INCOMPLETE")
    matches = [c for c in comments
               if isinstance(c, dict) and isinstance(c.get("body"), str)
               and c["body"].startswith(MARKER)
               and (c.get("user") or {}).get("login") == "github-actions[bot]"]
    need(len(matches) <= 1, "DUPLICATE_TRUSTED_PITCREW_COMMENTS")
    body = render(report)
    if matches:
        old = matches[0]
        if old.get("body") == body:
            return "UNCHANGED"
        need(type(old.get("id")) is int and old["id"] > 0,
             "COMMENT_ID_INVALID")
        send("PATCH", "/repos/" + HOME + "/issues/comments/" + str(old["id"]),
             {"body": body})
        return "UPDATED"
    send("POST", "/repos/" + HOME + "/issues/" + str(ISSUE) + "/comments",
         {"body": body})
    return "CREATED"


def main():
    output = Path("pitcrew-r1")
    output.mkdir(exist_ok=True)
    try:
        token = os.environ["GITHUB_TOKEN"]
        need(bool(token), "GITHUB_TOKEN_MISSING")
        get = lambda path: github("GET", path, token)
        report = observe(get)
        ensure_head_unchanged(get, report)
        report["publication"] = publish(
            get, lambda method, path, body: github(method, path, token, body),
            report)
        candidate = review_candidate(report)
        if candidate is not None:
            (output / "failure-review-candidate.json").write_text(
                json.dumps(candidate, indent=2, sort_keys=True) + "\n")
        (output / "observation.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")
        summary = ("## Phi Pit Crew R1\n\n" + render(report) +
                   "\nJournal action: " + report["publication"] + "\n")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(summary)
        print(report["state"], report["publication"])
        return 0
    except (Held, KeyError, OSError) as exc:
        reason = str(exc) if isinstance(exc, Held) else "RUNTIME_UNAVAILABLE"
        (output / "hold.json").write_text(
            json.dumps({"state": "HELD", "reason": reason}) + "\n")
        print("PITCREW_HELD " + reason, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
