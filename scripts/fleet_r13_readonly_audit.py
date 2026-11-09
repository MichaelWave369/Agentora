"""Fleet R13: owner-authorized, hosted public-repository metadata audit.

This deterministic worker is NOT a model agent. It never checks out or runs
target source code, writes issues/PRs, dispatches work or approves QA.
Its receipt is a claim requiring independent GitHub-backed QA in another
workflow. No local SQLite, installed agent, or user-provided secrets.
"""
import argparse
import json
import os
from pathlib import Path
import sys

import fleet_r12_github_missions as r12

SCHEMA = "agentora.fleet.r13.hosted-readonly-audit.v1"
CONFIRM = "RUN_FLEET_R13_READ_ONLY_AUDIT"
WORKER = "builder_a"


def need(ok, code):
    if not ok:
        raise r12.MissionHeld(code)


def audit(issue_number, *, actor, confirmation, token, get=None):
    # Gate authorization before making even one GitHub API call.
    need(actor == r12.OWNER and confirmation == CONFIRM,
         "OWNER_CONFIRMATION_REQUIRED")
    r12.positive(issue_number, "ISSUE")
    get = get or (lambda path, tok: r12.github("GET", path, tok))
    issue = get("/repos/" + r12.HOME + "/issues/" + str(issue_number), token)
    form, digest = r12.issue_identity(issue, issue_number)
    need(form["Mission kind"] == "Read-only audit", "AUDIT_MISSION_KIND_REQUIRED")
    state, last, seq = r12.journal(get, token, issue_number, digest)
    need(state == "ROLE_PROPOSED" and seq >= 2
         and type(last) is dict and last.get("worker_role") == WORKER
         and last.get("mission_kind") == "Read-only audit"
         and last.get("pr_number") is None,
         "EXACT_PROPOSED_READONLY_ROLE_REQUIRED")
    target = form["Target repository"]
    repo_id, branch, source_sha = r12.source(get, token, target)
    need(last.get("target_repo") == target
         and last.get("target_repo_id") == repo_id
         and last.get("branch") == branch,
         "MISSION_REPOSITORY_IDENTITY_CHANGED")
    repo = get("/repos/" + target, token)
    need(type(repo) is dict and repo.get("id") == repo_id
         and repo.get("full_name") == target and repo.get("private") is False
         and repo.get("archived") is False and repo.get("disabled") is False
         and (repo.get("owner") or {}).get("login") == r12.OWNER
         and repo.get("default_branch") == branch,
         "TARGET_OWNER_OR_STATUS_CHANGED")
    branch_record = get("/repos/" + target + "/branches/" + branch, token)
    need(type(branch_record) is dict
         and (branch_record.get("commit") or {}).get("sha") == source_sha
         and type(branch_record.get("protected")) is bool,
         "BRANCH_PROTECTION_METADATA_UNAVAILABLE")
    commit = get("/repos/" + target + "/commits/" + source_sha, token)
    need(type(commit) is dict and commit.get("sha") == source_sha
         and type(commit.get("parents")) is list,
         "HEAD_COMMIT_IDENTITY_UNVERIFIED")
    verified = ((commit.get("commit") or {}).get("verification") or {}).get("verified")
    need(verified is None or type(verified) is bool, "COMMIT_VERIFICATION_INVALID")
    repo_id2, branch2, sha2 = r12.source(get, token, target)
    need((repo_id2, branch2, sha2) == (repo_id, branch, source_sha),
         "SOURCE_MOVED_DURING_AUDIT")
    return {
        "schema": SCHEMA,
        "state": "AUDIT_RECEIPT_CAPTURED_PENDING_SEPARATE_QA",
        "mission_issue": issue_number,
        "mission_issue_sha256": digest,
        "mission_journal_seq": seq,
        "mission_kind": "Read-only audit",
        "proposed_worker": WORKER,
        "target_repository": target,
        "target_repository_id": repo_id,
        "default_branch": branch,
        "exact_source_sha": source_sha,
        "observations": {
            "public_repository": True,
            "not_archived": True,
            "not_disabled": True,
            "default_branch_protected": branch_record["protected"],
            "head_commit_found": True,
            "head_commit_signature_verified": verified,
        },
        "audit_scope": "PUBLIC_GITHUB_METADATA_ONLY",
        "target_source_executed": False,
        "worker_is_model_agent": False,
        "independent_qa_complete": False,
        "verified_complete": False,
        "merge_authorized": False,
        "dispatch_authorized": False,
        "deployment_authorized": False,
    }


def summary(report):
    if report.get("state") != "AUDIT_RECEIPT_CAPTURED_PENDING_SEPARATE_QA":
        return ("## Fleet R13: audit HELD\n\n"
                "No verified evidence, QA approval or merge permission.\n")
    observations = report["observations"]
    return "\n".join([
        "## Fleet R13: hosted public metadata audit",
        "",
        "- Mission: [Issue #" + str(report["mission_issue"]) +
        "](https://github.com/" + r12.HOME + "/issues/" +
        str(report["mission_issue"]) + ")",
        "- Repository: " + report["target_repository"],
        "- Source SHA: " + report["exact_source_sha"],
        "- Default branch protected: " +
        str(observations["default_branch_protected"]).lower(),
        "- HEAD commit signature verified: " +
        str(observations["head_commit_signature_verified"]).lower(),
        "- Scope: only GitHub public metadata, no target source execution",
        "- Separate QA: PENDING; worker did not approve its own receipt",
        "- No code change, merge, PR approval or deployment authorized",
        "",
    ])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--issue-number", required=True, type=int)
    p.add_argument("--confirmation", required=True)
    p.add_argument("--out", type=Path, default=Path("fleet-r13"))
    args = p.parse_args(argv)
    try:
        report = audit(args.issue_number,
                       actor=os.environ.get("GITHUB_ACTOR"),
                       confirmation=args.confirmation,
                       token=os.environ.get("GITHUB_TOKEN"))
        status = 0
    except (r12.MissionHeld, OSError, ValueError, TypeError) as exc:
        report = {"schema": SCHEMA, "state": "HELD_READONLY_AUDIT",
                  "reason": str(exc) if type(exc) is r12.MissionHeld else
                  "INPUT_OR_RUNTIME_UNAVAILABLE",
                  "verified_complete": False, "merge_authorized": False}
        status = 3
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "receipt.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "summary.md").write_text(summary(report), encoding="utf-8")
    print(json.dumps({"state": report["state"], "verified_complete": False,
                      "merge_authorized": False}))
    return status


if __name__ == "__main__":
    sys.exit(main())
