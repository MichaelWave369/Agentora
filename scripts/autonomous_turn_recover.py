"""Owner-approved recovery for one immutable R1 CI observation timeout.

No worker, App key, policy edits or bypass. The original task approval and a
new, exact owner environment approval are both mandatory before finish().
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys

from autonomous_turn import read, write
from autonomous_turn_contract import (REPO_ID, OWNER_ID, HEX40, HEX64,
    Held, need, validate, task_digest)
from autonomous_turn_github import (BASE, ENVIRONMENT, GitHub, authority,
    main_head, finish, return_receipt)

WORKFLOW = ".github/workflows/autonomous-turn-recover.yml"


def positive(value):
    need(isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value),
         "RECOVERY_ID_INVALID")
    return int(value)


def approval_comment(task, original_run, pr_number, head_sha):
    return (f"APPROVE RECOVERY {task_digest(task)} RUN {original_run} "
            f"PR {pr_number} HEAD {head_sha}")


def inputs():
    original_run = positive(os.environ["ORIGINAL_RUN_ID"])
    pr_number = positive(os.environ["EXPECTED_PR_NUMBER"])
    head_sha = os.environ["EXPECTED_HEAD_SHA"]
    task_sha = os.environ["EXPECTED_TASK_SHA256"]
    need(HEX40.fullmatch(head_sha or "") and HEX64.fullmatch(task_sha or ""),
         "RECOVERY_DIGEST_OR_HEAD_INVALID")
    return original_run, pr_number, head_sha, task_sha


def original_evidence(api, task, published, observed, value, sandbox,
                      original_run, pr_number, head_sha, task_sha):
    validate(task)
    need(task_digest(task) == task_sha and task["merge_policy"] == "docs" and
         task["max_repairs"] == 0 and
         value.get("attempt") == 0 and sandbox.get("attempt") == 0 and
         published.get("attempt") == 0 and observed.get("attempt") == 0,
         "RECOVERY_SCOPE_MISMATCH")
    need(published.get("pr_number") == pr_number and
         published.get("head_sha") == head_sha and
         published.get("task_sha256") == task_sha and
         observed.get("pr_number") == pr_number and
         observed.get("head_sha") == head_sha and
         observed.get("task_sha256") == task_sha and
         observed.get("state") == "CI_PENDING_TIMEOUT",
         "ORIGINAL_TIMEOUT_NOT_CONFIRMED")
    original = api(BASE+f"/actions/runs/{original_run}")
    need(original.get("status") == "completed" and
         original.get("conclusion") == "success" and
         original.get("run_attempt") == 1, "ORIGINAL_RUN_NOT_FINAL")
    authority(api, task, original_run, task["source_sha"])
    need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")


def recovery_authority(api, task, original_run, pr_number, head_sha,
                       recovery_run, control_sha):
    need(type(recovery_run) is int and recovery_run > 0 and
         recovery_run != original_run and control_sha == task["source_sha"],
         "RECOVERY_CONTROLLER_IDENTITY")
    run = api(BASE+f"/actions/runs/{recovery_run}")
    need(run.get("id") == recovery_run and
         run.get("repository", {}).get("id") == REPO_ID and
         run.get("head_sha") == control_sha and
         run.get("head_branch") == "main" and
         run.get("event") == "workflow_dispatch" and
         run.get("run_attempt") == 1 and
         run.get("path", "").split("@")[0] == WORKFLOW and
         all(run.get(k, {}).get("id") == OWNER_ID and
             run.get(k, {}).get("type") == "User"
             for k in ("actor", "triggering_actor")),
         "RECOVERY_NOT_OWNER_DISPATCHED_TRUSTED_MAIN")
    environment = api(BASE+"/environments/"+ENVIRONMENT)
    need(type(environment.get("id")) is int and
         environment.get("name") == ENVIRONMENT, "RECOVERY_ENVIRONMENT_IDENTITY")
    reviewers = [r for rule in environment.get("protection_rules", [])
                 if rule.get("type") == "required_reviewers"
                 for r in rule.get("reviewers", [])]
    need(len(reviewers) == 1 and reviewers[0].get("type") == "User" and
         reviewers[0].get("reviewer", {}).get("id") == OWNER_ID,
         "OWNER_REVIEWER_CONFIGURATION_REQUIRED")
    records = api(BASE+f"/actions/runs/{recovery_run}/approvals")
    need(isinstance(records, list) and 0 < len(records) < 100,
         "RECOVERY_APPROVAL_MISSING")
    relevant = [r for r in records
                if any(e.get("id") == environment.get("id") and
                       e.get("name") == ENVIRONMENT
                       for e in r.get("environments", []))]
    need(relevant and all(r.get("state") == "approved" for r in relevant),
         "RECOVERY_APPROVAL_REJECTED")
    expected = approval_comment(task, original_run, pr_number, head_sha)
    matching = [r for r in relevant
                if r.get("user", {}).get("id") == OWNER_ID and
                   r.get("user", {}).get("type") == "User" and
                   r.get("comment") == expected]
    need(len(matching) == 1, "EXACT_RECOVERY_OWNER_APPROVAL_REQUIRED")
    need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")


def execute(api, original_run, pr_number, head_sha, task_sha, recovery_run,
            control_sha, directory, stage):
    task = read(directory/"task.json")
    published = read(directory/"published.json")
    observed = read(directory/"observation.json")
    value = read(directory/"proposal.json")
    sandbox = read(directory/"sandbox.json")
    original_evidence(api, task, published, observed, value, sandbox,
                      original_run, pr_number, head_sha, task_sha)
    if stage == "plan":
        message = approval_comment(task, original_run, pr_number, head_sha)
        summary = ("### Autonomous R1 late-CI recovery: new owner review required\n\n"
                   f"Original run: {original_run}\n\n"
                   f"PR: #{pr_number} at exact head {head_sha}\n\n"
                   f"Task expires: {task['expires_utc']}\n\n"
                   "Only the original docs attempt-0 is eligible. "
                   "No new edits, repair or approval shortcuts.\n\n"
                   "In Review deployments, enter exactly:\n\n"
                   f"{message}\n")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            Path(os.environ["GITHUB_STEP_SUMMARY"]).write_text(summary)
        return {"state": "RECOVERY_REVIEW_REQUIRED", "original_run": original_run,
                "pr_number": pr_number, "head_sha": head_sha}
    need(stage == "finish", "RECOVERY_STAGE")
    recovery_authority(api, task, original_run, pr_number, head_sha,
                       recovery_run, control_sha)
    result = finish(api, task, published, value, sandbox, original_run,
                    task["source_sha"])
    write(directory/"turn-receipt.json", result)
    return_receipt(api, task, result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("plan", "finish"))
    parser.add_argument("--directory", type=Path, default=Path("turn-control"))
    args = parser.parse_args()
    try:
        original, pr, head, task_sha = inputs()
        api = GitHub(os.environ["GH_TOKEN"],
                     audit_path=args.directory/"network-audit.jsonl")
        result = execute(api, original, pr, head, task_sha,
                         int(os.environ["GITHUB_RUN_ID"]), os.environ["GITHUB_SHA"],
                         args.directory, args.stage)
        print("AUTONOMOUS_RECOVERY_RESULT "+result["state"])
    except (Held, KeyError, ValueError, OSError) as exc:
        reason = str(exc) if isinstance(exc, Held) else "RECOVERY_RUNTIME_UNAVAILABLE"
        write(args.directory/"hold.json",
              {"schema": "agentora.autonomous-hold.v1", "state": "HELD",
               "reason": reason})
        print("AUTONOMOUS_RECOVERY_HELD "+reason, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
