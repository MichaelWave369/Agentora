"""Trusted GitHub stages. Never import or execute candidate project code here."""
from __future__ import annotations

import base64
import hashlib
from datetime import datetime, timezone
import json
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, quote
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

import devloop_automerge as devloop
from devloop_r2_policy import classify_files, require_independent_review, CodeHeld
from autonomous_turn_contract import (REPO, REPO_ID, OWNER_ID, Held, HEX40,
    canonical, digest, task_digest, validate, need, verify_proposal, proposal as build_proposal)

BASE = "/repos/" + REPO
WORKFLOW = ".github/workflows/autonomous-turn-r1.yml"
ENVIRONMENT = "autonomous-turn-owner"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHub:
    def __init__(self, token, audit_path=None):
        self.token = token
        self.audit_path = Path(audit_path) if audit_path else None
        self.audit_count = 0

    def audit(self, path, method, payload, status, response_digest=None):
        if self.audit_path is None:
            return
        self.audit_count += 1
        need(self.audit_count <= 2000, "API_REQUEST_BUDGET")
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        need(not self.audit_path.is_symlink(), "AUDIT_PATH_UNSAFE")
        row = {"sequence": self.audit_count, "method": method, "path": path,
               "request_sha256": digest(canonical(payload)), "status": status,
               "response_sha256": response_digest,
               "observed_utc": datetime.now(timezone.utc).isoformat()}
        # No bearer, payload text, signed redirect URL or response body is saved.
        with self.audit_path.open("ab") as stream:
            stream.write(canonical(row)+b"\n")

    def __call__(self, path, payload=None, method=None):
        need(path == "/graphql" or path.startswith(BASE + "/") or path == BASE, "API_PATH")
        need(self.audit_count < 2000, "API_REQUEST_BUDGET")
        request = Request("https://api.github.com"+path,
            data=None if payload is None else canonical(payload),
            method=method or ("POST" if payload is not None else "GET"),
            headers={"Authorization": "Bearer "+self.token,
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json",
                     "X-GitHub-Api-Version": "2022-11-28",
                     "User-Agent": "agentora-autonomous-turn-r1"})
        status, response_digest = None, None
        verb = method or ("POST" if payload is not None else "GET")
        try:
            with build_opener(NoRedirect()).open(request, timeout=20) as response:
                status = response.status
                raw = response.read(2_000_001)
            need(len(raw) <= 2_000_000, "API_RESPONSE_SIZE")
            response_digest = digest(raw)
            return json.loads(raw)
        except HTTPError as exc:
            status = exc.code
            raise Held("GITHUB_HTTP_"+str(exc.code)) from None
        except (URLError, TimeoutError, ValueError):
            raise Held("GITHUB_API_UNAVAILABLE") from None
        finally:
            self.audit(path, verb, payload, status, response_digest)

    def log_tail(self, job_id):
        # The signed redirect is fetched WITHOUT the API bearer token.
        need(self.audit_count < 2000, "API_REQUEST_BUDGET")
        request = Request("https://api.github.com"+BASE+f"/actions/jobs/{job_id}/logs",
            headers={"Authorization": "Bearer "+self.token,
                     "Accept": "application/vnd.github+json"})
        status, response_digest = None, None
        try:
            try:
                with build_opener(NoRedirect()).open(request, timeout=20) as response:
                    status = response.status
                    raw = response.read(1_000_001)
            except HTTPError as redirect:
                need(redirect.code == 302, "LOG_DOWNLOAD_REFUSED")
                target = redirect.headers.get("Location", "")
                parsed = urlparse(target)
                need(parsed.scheme == "https" and parsed.hostname and
                     parsed.hostname.endswith(".blob.core.windows.net") and
                     parsed.port in (None, 443) and not parsed.username and not parsed.password,
                     "LOG_REDIRECT_REFUSED")
                with build_opener(NoRedirect()).open(Request(target), timeout=20) as response:
                    status = response.status
                    raw = response.read(1_000_001)
            need(len(raw) <= 1_000_000, "LOG_DOWNLOAD_SIZE")
            response_digest = digest(raw)
            # Remove workflow commands, control characters and common secret values.
            text = raw[-32768:].decode("utf-8", errors="replace")
            text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
            text = re.sub(r"(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)", "[REDACTED]", text)
            return text.replace("::", ": :")
        except (HTTPError, URLError, TimeoutError, ValueError):
            raise Held("LOG_DOWNLOAD_UNAVAILABLE") from None
        finally:
            self.audit(BASE+f"/actions/jobs/{job_id}/logs", "GET", None, status, response_digest)


def identity(api):
    repo = api(BASE)
    need(repo.get("id") == REPO_ID and repo.get("full_name") == REPO and
         repo.get("private") is False and repo.get("archived") is False and
         repo.get("default_branch") == "main" and
         repo.get("owner", {}).get("id") == OWNER_ID, "GITHUB_REPOSITORY_IDENTITY")
    return repo


def main_head(api):
    first = api(BASE+"/git/ref/heads/main").get("object", {}).get("sha")
    second = api(BASE+"/git/ref/heads/main").get("object", {}).get("sha")
    need(isinstance(first, str) and HEX40.fullmatch(first) and first == second, "SOURCE_DRIFT")
    return first


def authority(api, task, run_id, control_sha):
    """JSON/comments/labels cannot satisfy this GitHub-owned review record."""
    validate(task)
    identity(api)
    need(type(run_id) is int and run_id > 0 and HEX40.fullmatch(control_sha) and
         control_sha == task["source_sha"], "RUN_IDENTITY")
    run = api(BASE+f"/actions/runs/{run_id}")
    need(run.get("id") == run_id and run.get("repository", {}).get("id") == REPO_ID and
         run.get("head_sha") == control_sha and run.get("head_branch") == "main" and
         run.get("event") in ("workflow_dispatch", "issues") and run.get("run_attempt") == 1 and
         run.get("path", "").split("@")[0] == WORKFLOW and
         all(run.get(k, {}).get("id") == OWNER_ID and
             run.get(k, {}).get("type") == "User" for k in ("actor", "triggering_actor")),
         "RUN_NOT_OWNER_DISPATCHED_TRUSTED_MAIN")
    env = api(BASE+"/environments/"+ENVIRONMENT)
    need(type(env.get("id")) is int and env.get("name") == ENVIRONMENT, "ENVIRONMENT_IDENTITY")
    reviewers = [r for rule in env.get("protection_rules", [])
                 if rule.get("type") == "required_reviewers" for r in rule.get("reviewers", [])]
    need(len(reviewers) == 1 and reviewers[0].get("type") == "User" and
         reviewers[0].get("reviewer", {}).get("id") == OWNER_ID, "OWNER_REVIEWER_CONFIGURATION_REQUIRED")
    reviews = api(BASE+f"/actions/runs/{run_id}/approvals")
    need(isinstance(reviews, list) and 0 < len(reviews) < 100, "ENVIRONMENT_REVIEW_REQUIRED")
    relevant = [r for r in reviews if any(e.get("id") == env["id"] and
                e.get("name") == ENVIRONMENT for e in r.get("environments", []))]
    need(relevant and not any(r.get("state") != "approved" for r in relevant), "ENVIRONMENT_REJECTED")
    approvals = [r for r in relevant if r.get("user", {}).get("id") == OWNER_ID and
                 r.get("user", {}).get("type") == "User" and
                 r.get("comment") == "APPROVE "+task_digest(task)]
    need(len(approvals) == 1, "EXACT_TASK_OWNER_APPROVAL_REQUIRED")
    # The review evidence is fetched fresh by every privileged stage. This hash
    # identifies GitHub's record; it is not a fabricated approval certificate.
    return {"run_id": run_id, "environment_id": env["id"], "owner_id": OWNER_ID,
            "task_sha256": task_digest(task), "control_sha": control_sha,
            "github_review_sha256": digest(canonical(approvals[0]))}


def source_files(api, task):
    result = {}
    for path in task["allowed_paths"]:
        data = api(BASE+"/contents/"+quote(path, safe="/")+"?ref="+task["source_sha"])
        need(data.get("type") == "file" and data.get("encoding") == "base64" and
             type(data.get("size")) is int and 0 < data["size"] <= 100000, "SOURCE_FILE_UNSAFE")
        try:
            value = base64.b64decode(data["content"], validate=False).decode("utf-8")
        except (ValueError, UnicodeError, KeyError):
            raise Held("SOURCE_ENCODING") from None
        need(len(value.encode()) == data["size"] and "\x00" not in value, "SOURCE_SIZE")
        result[path] = value
    return result


def branch_for(task, run_id):
    return f"autonomous/r1/{task['task_id']}-{run_id}"


def files_for_pr(api, pr):
    files = api(BASE+f"/pulls/{pr['number']}/files?per_page=100")
    need(isinstance(files, list) and 0 < len(files) < 100 and
         type(pr.get("changed_files")) is int and len(files) == pr["changed_files"], "PR_FILES_INCOMPLETE")
    return files


def verify_commit_tree(api, task, head, proposal):
    """Compare complete Git trees, including modes and unchanged files.

    Contents API can dereference symlinks. A content digest by itself must not
    let a symlink, submodule, hidden extra file or executable-bit change through.
    """
    trees = []
    for sha in (task["source_sha"], head):
        commit = api(BASE+"/git/commits/"+sha)
        tree = api(BASE+"/git/trees/"+commit["tree"]["sha"]+"?recursive=1")
        need(tree.get("truncated") is False and isinstance(tree.get("tree"), list), "GIT_TREE_INCOMPLETE")
        rows = tree["tree"]
        need(len(rows) <= 10000, "GIT_TREE_SIZE")
        mapping = {r["path"]: {k: r[k] for k in ("mode", "type", "sha")}
                   for r in rows if r.get("type") != "tree"}
        need(len(mapping) == len([r for r in rows if r.get("type") != "tree"]), "GIT_TREE_DUPLICATE")
        trees.append(mapping)
    expected = dict(trees[0])
    for change in proposal["changes"]:
        path, raw = change["path"], change["content"].encode()
        need(expected.get(path, {}).get("mode") == "100644" and
             expected[path]["type"] == "blob", "ORIGINAL_NOT_REGULAR_FILE")
        sha = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        expected[path] = {"mode": "100644", "type": "blob", "sha": sha}
    need(trees[1] == expected, "FULL_GIT_TREE_OUT_OF_SCOPE")


def verify_pr(api, task, pr, proposal, run_id, merged=False):
    need(type(pr.get("number")) is int and pr["number"] > 0 and
         pr.get("draft") is False and
         (pr.get("merged") is True if merged else pr.get("state") == "open") and
         pr.get("base", {}).get("repo", {}).get("id") == REPO_ID and
         pr.get("base", {}).get("repo", {}).get("full_name") == REPO and
         pr.get("base", {}).get("ref") == "main" and
         pr.get("head", {}).get("repo", {}).get("id") == REPO_ID and
         pr.get("head", {}).get("repo", {}).get("full_name") == REPO and
         pr.get("head", {}).get("ref") == branch_for(task, run_id) and
         isinstance(pr.get("head", {}).get("sha"), str) and HEX40.fullmatch(pr["head"]["sha"]), "PR_IDENTITY")
    labels = {r.get("name", "").lower() for r in pr.get("labels", [])}
    need(not labels & (devloop.HELD | {devloop.LABEL, devloop.CODE_LABEL, devloop.SOLO_LABEL}), "PR_HELD_OR_CONFLICTING_AUTHORIZATION")
    # Require the exact approved source to be an ancestor, not a PR body claim.
    compare = api(BASE+f"/compare/{task['source_sha']}...{pr['head']['sha']}")
    need(compare.get("merge_base_commit", {}).get("sha") == task["source_sha"] and
         compare.get("status") == "ahead", "PR_SOURCE_ANCESTRY")
    verify_commit_tree(api, task, pr["head"]["sha"], proposal)
    files = files_for_pr(api, pr)
    expected = {c["path"]: c for c in proposal["changes"]}
    need({f.get("filename") for f in files} == set(expected) and
         len(files) == len(expected) and all(f.get("status") == "modified" for f in files), "PR_SCOPE")
    need(sum(f.get("additions", -100000)+f.get("deletions", -100000) for f in files)
         <= task["max_changed_lines"] and all(type(f.get(k)) is int and f[k] >= 0
                      for f in files for k in ("additions", "deletions")), "PR_DIFF_SIZE")
    if task["merge_policy"] == "docs":
        need(all(devloop.is_doc(f["filename"]) for f in files), "DOCS_POLICY")
    else:
        try:
            classify_files(files)
        except CodeHeld:
            raise Held("EXISTING_CODE_POLICY_HELD") from None
    for path, change in expected.items():
        data = api(BASE+"/contents/"+quote(path, safe="/")+"?ref="+pr["head"]["sha"])
        need(data.get("type") == "file" and data.get("encoding") == "base64", "PR_BLOB_TYPE")
        try:
            raw = base64.b64decode(data["content"])
        except (ValueError, KeyError):
            raise Held("PR_BLOB_ENCODING") from None
        need(digest(raw) == change["after_sha256"] and raw == change["content"].encode(), "PR_BLOB_CHANGED")
    return files


def check_runs(api, sha):
    value = api(BASE+f"/commits/{sha}/check-runs?per_page=100")
    need(type(value.get("total_count")) is int and 0 <= value["total_count"] < 100 and
         isinstance(value.get("check_runs"), list) and
         len(value["check_runs"]) == value["total_count"], "CHECKS_INCOMPLETE")
    checks, ci_runs = [], {}
    for name in sorted(devloop.REQUIRED):
        found = [r for r in value["check_runs"] if r.get("name") == name]
        for row in found:
            need(row.get("head_sha") == sha and
                 row.get("app", {}).get("slug") == "github-actions" and
                 row.get("app", {}).get("id") == 15368, "CHECK_SOURCE_OR_SHA")
            match = re.fullmatch(r"https://github\.com/MichaelWave369/Agentora/actions/runs/(\d+)/job/(\d+)", row.get("details_url", ""))
            need(match is not None, "CHECK_RUN_IDENTITY")
            rid = int(match[1])
            if rid not in ci_runs:
                ci_runs[rid] = api(BASE+f"/actions/runs/{rid}")
            ci = ci_runs[rid]
            need(ci.get("head_sha") == sha and ci.get("repository", {}).get("id") == REPO_ID and
                 ci.get("path", "").split("@")[0] == ".github/workflows/ci.yml" and
                 ci.get("event") in ("push", "pull_request"), "REQUIRED_CHECK_WRONG_WORKFLOW")
        # Both push and PR CI exist in Agentora. Every observed run must pass;
        # an earlier green result never conceals a newer failed or pending run.
        for row in found or [{}]:
            checks.append({"name": name, "id": row.get("id"),
                           "status": row.get("status", "missing"),
                           "conclusion": row.get("conclusion"), "head_sha": sha,
                           "details_url": row.get("details_url")})
    for row in value["check_runs"]:
        if row.get("name") not in devloop.REQUIRED:
            need(row.get("conclusion") not in ("failure", "timed_out", "action_required", "cancelled"),
                 "ADDITIONAL_SECURITY_OR_CHECK_FAILURE")
    return checks


def green(checks):
    return (len(checks) >= 3 and {r["name"] for r in checks} == devloop.REQUIRED and
            all(r["status"] == "completed" and r["conclusion"] == "success" for r in checks))


def sandbox_valid(task, proposal, sandbox):
    need(isinstance(sandbox, dict) and set(sandbox) ==
         {"schema", "task_sha256", "proposal_sha256", "attempt", "checks", "isolated"} and
         sandbox.get("schema") == "agentora.autonomous-sandbox.v1" and
         sandbox.get("task_sha256") == task_digest(task) and
         sandbox.get("proposal_sha256") == digest(canonical(proposal)) and
         sandbox.get("attempt") == proposal["attempt"] and sandbox.get("isolated") is True and
         sandbox.get("checks") == [{"name": name, "exit_code": 0} for name in task["tests"]], "SANDBOX_NOT_PASSED")


def verify_repair(api, task, value, previous_head, originals):
    attempt = value["attempt"]
    need(1 <= attempt <= len(task["repairs"]) <= task["max_repairs"] <= 2 and
         isinstance(previous_head, str) and HEX40.fullmatch(previous_head), "REPAIR_EXHAUSTED")
    prior = build_proposal(task, originals, attempt-1)
    verify_commit_tree(api, task, previous_head, prior)
    checks = check_runs(api, previous_head)
    rule = task["repairs"][attempt-1]
    failed = [r for r in checks if r["status"] == "completed" and r["conclusion"] != "success"]
    need(all(r["status"] == "completed" for r in checks) and 0 < len(failed) <= 3 and
         {r["name"] for r in failed} == {rule["check"]}, "REPAIR_FAILURE_CHANGED_OR_AMBIGUOUS")
    for row in failed:
        match = re.fullmatch(r"https://github\.com/MichaelWave369/Agentora/actions/runs/(\d+)/job/(\d+)", row["details_url"] or "")
        need(match is not None, "REPAIR_JOB_IDENTITY")
        run_id, job_id = map(int, match.groups())
        job = api(BASE+f"/actions/jobs/{job_id}")
        need(job.get("head_sha") == previous_head and job.get("id") == job_id and
             job.get("run_id") == run_id and job.get("name") == rule["check"] and
             job.get("conclusion") == row["conclusion"], "REPAIR_JOB_IDENTITY")
        need(rule["log_contains"] in api.log_tail(job_id), "REPAIR_LOG_SIGNATURE_CHANGED")


def publish(api, task, value, sandbox, run_id, control_sha, previous_head=None):
    auth = authority(api, task, run_id, control_sha)
    originals = source_files(api, task)
    verify_proposal(task, originals, value, value["attempt"])
    sandbox_valid(task, value, sandbox)
    need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")
    if value["attempt"]:
        verify_repair(api, task, value, previous_head, originals)
    branch = branch_for(task, run_id)
    branches = api(BASE+"/git/matching-refs/heads/"+branch)
    need(isinstance(branches, list) and len(branches) <= 1, "BRANCH_AMBIGUOUS")
    existing = branches[0]["object"]["sha"] if branches else None
    message = f"Autonomous R1 {task['task_id']} attempt {value['attempt']}\n\nTask-SHA256: {task_digest(task)}"
    reuse = False
    if existing and existing != previous_head:
        commit = api(BASE+"/git/commits/"+existing)
        reuse = commit.get("message") == message
        need(reuse, "BRANCH_LEASE_CHANGED")
    if not reuse:
        need((value["attempt"] == 0 and existing is None and previous_head is None) or
             (value["attempt"] > 0 and HEX40.fullmatch(previous_head or "") and existing == previous_head), "BRANCH_LEASE_CHANGED")
        base_commit = api(BASE+"/git/commits/"+task["source_sha"])
        tree = api(BASE+"/git/trees", {"base_tree": base_commit["tree"]["sha"],
            "tree": [{"path": c["path"], "mode": "100644", "type": "blob", "content": c["content"]}
                     for c in value["changes"]]})
        commit = api(BASE+"/git/commits", {"message": message, "tree": tree["sha"],
                     "parents": [previous_head or task["source_sha"]]})
        head = commit["sha"]
        need(HEX40.fullmatch(head), "COMMIT_IDENTITY")
        # Revalidate authorization/expiry and source immediately before ref mutation.
        authority(api, task, run_id, control_sha)
        need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")
        if existing:
            api(BASE+"/git/refs/heads/"+branch, {"sha": head, "force": False}, method="PATCH")
        else:
            api(BASE+"/git/refs", {"ref": "refs/heads/"+branch, "sha": head})
    else:
        head = existing
    verify_commit_tree(api, task, head, value)
    prs = api(BASE+"/pulls?state=all&head=MichaelWave369:"+branch+"&base=main&per_page=100")
    need(isinstance(prs, list) and len(prs) <= 1, "TASK_PR_AMBIGUOUS")
    if prs:
        pr = api(BASE+f"/pulls/{prs[0]['number']}")
    else:
        pr = api(BASE+"/pulls", {"title": "Autonomous R1: "+task["task_id"], "head": branch,
            "base": "main", "body": "One owner-approved bounded task.\n\nTask SHA-256: `"+
            task_digest(task)+"`\n\nAuthorization: https://github.com/"+REPO+
            f"/actions/runs/{run_id}\n\nPolicy: `{task['merge_policy']}`. "
            "The PR body grants no authority. Product acceptance remains outstanding."})
    need(pr.get("head", {}).get("sha") == head, "PUBLISHED_HEAD_CHANGED")
    verify_pr(api, task, pr, value, run_id)
    return {"pr_number": pr["number"], "head_sha": head, "authorization": auth,
            "task_sha256": task_digest(task), "attempt": value["attempt"]}


OBSERVE_POLL_INTERVAL_SECONDS = 15
OBSERVE_MAX_POLLS = 96


def observe(api, task, published, proposal, run_id, control_sha,
            sleep=time.sleep, polls=OBSERVE_MAX_POLLS):
    authority(api, task, run_id, control_sha)
    head = published["head_sha"]
    need(published.get("task_sha256") == task_digest(task), "PUBLISHED_TASK_MISMATCH")
    result = {"task_sha256": task_digest(task), "head_sha": head,
              "attempt": proposal["attempt"], "pr_number": published["pr_number"]}
    for index in range(polls):
        validate(task)
        need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")
        pr = api(BASE+f"/pulls/{published['pr_number']}")
        need(pr.get("head", {}).get("sha") == head, "PR_HEAD_CHANGED")
        verify_pr(api, task, pr, proposal, run_id)
        checks = check_runs(api, head)
        if green(checks):
            return {**result, "state": "CI_PASSED", "checks": checks, "failures": []}
        failed = [r for r in checks if r["status"] == "completed" and
                  r["conclusion"] not in ("success", None)]
        # Wait for all required jobs to settle; multiple failures are ambiguous.
        if failed and all(r["status"] == "completed" for r in checks):
            need(len(failed) <= 6, "FAILURE_SET_TOO_LARGE")
            grouped = {}
            for check in failed:
                match = re.fullmatch(r"https://github\.com/MichaelWave369/Agentora/actions/runs/(\d+)/job/(\d+)", check["details_url"] or "")
                need(match is not None, "FAILED_LOG_IDENTITY")
                ci_run, job_id = map(int, match.groups())
                job = api(BASE+f"/actions/jobs/{job_id}")
                need(job.get("id") == job_id and job.get("run_id") == ci_run and
                     job.get("head_sha") == head and job.get("name") == check["name"] and
                     job.get("conclusion") == check["conclusion"], "FAILED_JOB_IDENTITY")
                item = grouped.setdefault(check["name"], {"name": check["name"], "job_ids": [], "log_tail": ""})
                item["job_ids"].append(job_id)
                item["log_tail"] += f"\nGitHub job {job_id}:\n"+api.log_tail(job_id)[-4096:]
            failures = list(grouped.values())
            return {**result, "state": "CI_FAILED", "checks": checks, "failures": failures}
        if index+1 < polls:
            sleep(OBSERVE_POLL_INTERVAL_SECONDS)
    return {**result, "state": "CI_PENDING_TIMEOUT", "checks": checks, "failures": []}


def rules(api):
    rows = api(BASE+"/rulesets?includes_parents=true&per_page=100")
    need(isinstance(rows, list) and len(rows) < 100, "RULESETS_INCOMPLETE")
    details = [api(BASE+f"/rulesets/{row['id']}") for row in rows if row.get("enforcement") == "active"]
    try:
        devloop.verify_rules(details)
    except devloop.Block:
        raise Held("EXISTING_REQUIRED_CI_RULESET_MISSING") from None
    return details


def finish(api, task, published, proposal, sandbox, run_id, control_sha):
    auth = authority(api, task, run_id, control_sha)
    verify_proposal(task, source_files(api, task), proposal, proposal["attempt"])
    sandbox_valid(task, proposal, sandbox)
    number, head = published["pr_number"], published["head_sha"]
    need(published.get("task_sha256") == task_digest(task), "PUBLISHED_TASK_MISMATCH")
    pr = api(BASE+f"/pulls/{number}")
    need(pr.get("head", {}).get("sha") == head, "PR_HEAD_CHANGED")
    # Recover a previous successful merge after a lost network response, but
    # still re-read GitHub's record and exact blobs/checks before reporting it.
    was_merged = pr.get("merged") is True
    files = verify_pr(api, task, pr, proposal, run_id, merged=was_merged)
    checks = check_runs(api, head)
    need(green(checks), "EXACT_HEAD_REQUIRED_CI_NOT_GREEN")
    decision = "PUBLISH_ONLY_OWNER_REVIEW_REQUIRED"
    if not was_merged and task["merge_policy"] != "publish-only":
        need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")
        rules(api)
        if task["merge_policy"] == "reviewed-code":
            try:
                require_independent_review(lambda token, path, payload=None: api(path, payload),
                    None, number, head, pr.get("user", {}).get("login"))
            except CodeHeld:
                return receipt(task, published, proposal, auth, checks,
                               "HELD_INDEPENDENT_CODE_REVIEW_REQUIRED", None, run_id)
        # Do not rely on an earlier checks/authorization/PR snapshot.
        authority(api, task, run_id, control_sha)
        latest = api(BASE+f"/pulls/{number}")
        need(latest.get("head", {}).get("sha") == head and
             latest.get("mergeable") is True and latest.get("mergeable_state") == "clean",
             "GITHUB_MERGE_REQUIREMENTS_UNSATISFIED")
        need(verify_pr(api, task, latest, proposal, run_id) == files, "PR_DIFF_CHANGED")
        need(green(check_runs(api, head)), "EXACT_HEAD_REQUIRED_CI_NOT_GREEN")
        rules(api)
        need(main_head(api) == task["source_sha"], "SOURCE_DRIFT")
        if task["merge_policy"] == "reviewed-code":
            try:
                require_independent_review(lambda token, path, payload=None: api(path, payload),
                    None, number, head, latest.get("user", {}).get("login"))
            except CodeHeld:
                raise Held("INDEPENDENT_REVIEW_CHANGED") from None
        response = api(BASE+f"/pulls/{number}/merge", {"sha": head, "merge_method": "squash"}, method="PUT")
        need(response.get("merged") is True and HEX40.fullmatch(response.get("sha", "")), "GITHUB_MERGE_NOT_CONFIRMED")
        decision = "EXACT_TASK_DOCS_SQUASH_MERGED" if task["merge_policy"] == "docs" else "EXACT_TASK_REVIEWED_CODE_SQUASH_MERGED"
        pr = api(BASE+f"/pulls/{number}")
        need(pr.get("merge_commit_sha") == response["sha"], "POSTMERGE_SHA_MISMATCH")
    if pr.get("merged") is True:
        merge_sha = pr.get("merge_commit_sha")
        need(HEX40.fullmatch(merge_sha or "") and pr.get("merged_at"), "POSTMERGE_RECORD_MISSING")
        commit = api(BASE+"/commits/"+merge_sha)
        need(commit.get("sha") == merge_sha, "POSTMERGE_COMMIT_MISSING")
        # A squash result must have precisely the authorized original as parent.
        need([p.get("sha") for p in commit.get("parents", [])] == [task["source_sha"]], "POSTMERGE_PARENT_DRIFT")
        for change in proposal["changes"]:
            data = api(BASE+"/contents/"+quote(change["path"], safe="/")+"?ref="+merge_sha)
            need(data.get("type") == "file" and digest(base64.b64decode(data.get("content", ""))) ==
                 change["after_sha256"], "POSTMERGE_CONTENT_MISMATCH")
        decision = "VERIFIED_EXISTING_MERGE" if was_merged else decision
        return receipt(task, published, proposal, auth, checks, decision, merge_sha, run_id)
    return receipt(task, published, proposal, auth, checks, decision, None, run_id)


def receipt(task, published, proposal, auth, checks, decision, merge_sha, run_id):
    return {"schema": "agentora.autonomous-turn-receipt.v1", "task_id": task["task_id"],
        "task_sha256": task_digest(task), "repository": REPO, "repository_id": REPO_ID,
        "source_sha": task["source_sha"], "pr_number": published["pr_number"],
        "pr_url": f"https://github.com/{REPO}/pull/{published['pr_number']}",
        "tested_pr_sha": published["head_sha"], "checks": checks,
        "repair_attempts": proposal["attempt"], "merge_decision": decision,
        "merge_commit_sha": merge_sha, "authorization": auth,
        "state": "MERGED" if merge_sha else "AUTOMATED_CHECKS_PASSED",
        "outstanding_acceptance": task["acceptance"], "project_verified_complete": False,
        "next_action": "Review outstanding project acceptance" if merge_sha else
                       "Obtain the required human review; no automatic code merge was authorized",
        "phimada_request_sha256": task["phimada_request_sha256"],
        "run_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
        "recorded_utc": datetime.now(timezone.utc).isoformat()}


def return_receipt(api, task, value):
    """Publish a read-only result surface without editing PhiMada source.

    PhiMada reads this GitHub-Actions check and independently correlates its
    current PR/CI/owner-review/merge records. The JSON is not authority.
    """
    text = canonical({"task": task, "receipt": value}).decode()
    need(len(text.encode()) <= 60000, "RETURN_RECEIPT_SIZE")
    name = "Autonomous Turn R1 receipt"
    existing = api(BASE+f"/commits/{value['tested_pr_sha']}/check-runs?per_page=100")
    need(type(existing.get("total_count")) is int and existing["total_count"] < 100 and
         len(existing.get("check_runs", [])) == existing["total_count"], "RETURN_CHECKS_INCOMPLETE")
    matches = [r for r in existing["check_runs"] if r.get("name") == name and
               r.get("external_id") == value["task_sha256"] and r.get("details_url") == value["run_url"] and
               r.get("app", {}).get("id") == 15368]
    need(len(matches) <= 1, "RETURN_RECEIPT_AMBIGUOUS")
    fields = {"name": name, "details_url": value["run_url"], "external_id": value["task_sha256"],
        "status": "completed", "conclusion": "success" if value["merge_commit_sha"] else "neutral",
        "output": {"title": value["merge_decision"], "summary":
                   "GitHub records were re-read. Project acceptance remains outstanding.", "text": text}}
    if matches:
        api(BASE+f"/check-runs/{matches[0]['id']}", fields, method="PATCH")
    else:
        api(BASE+"/check-runs", {**fields, "head_sha": value["tested_pr_sha"]})
