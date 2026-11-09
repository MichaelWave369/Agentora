"""Fleet R12: GitHub-native mission board, no local installation.

The only permitted write is one bounded journal comment on an owner-created
Agentora Issue, from an owner-confirmed GitHub Actions workflow. Role proposal
does NOT launch an agent. PR and evidence links are NOT independent QA.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

OWNER = "MichaelWave369"
HOME = OWNER + "/Agentora"
SCHEMA = "agentora.fleet.github-mission.v1"
MARK = "<!-- agentora-fleet-r12-journal-v1 -->"
CONFIRM = "RECORD_FLEET_MISSION_TRANSITION"
REPO = re.compile(r"MichaelWave369/[A-Za-z0-9_.-]{1,100}\Z")
HEX40 = re.compile(r"[a-f0-9]{40}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
ROLE = re.compile(r"[a-z0-9][a-z0-9_-]{1,39}\Z")
FIELDS = ("Target repository", "Mission kind", "Requested outcome", "Acceptance criteria")
KINDS = {"Read-only audit", "Feature proposal", "Documentation", "Fixed PhiMada test review"}
NEXT = {"triage": ("UNTRIAGED", "TRIAGED"),
        "propose_worker": ("TRIAGED", "ROLE_PROPOSED"),
        "queue_qa": ("ROLE_PROPOSED", "QA_QUEUED_UNVERIFIED"),
        "qa_hold": ("QA_QUEUED_UNVERIFIED", "QA_HELD")}
ACTIONS = set(NEXT) | {"link_evidence"}


class MissionHeld(ValueError):
    pass


def need(ok, msg):
    if not ok:
        raise MissionHeld(msg)


def positive(value, name):
    need(type(value) is int and 0 < value < 9223372036854775807, name + "_INVALID")
    return value


def github(method, path, token, payload=None):
    need(isinstance(token, str) and bool(token.strip()), "GITHUB_TOKEN_REQUIRED")
    need(type(path) is str and path.startswith("/repos/" + OWNER + "/")
         and all(c not in path for c in ("..", "%", "#", "\\", "//")),
         "UNSAFE_GITHUB_API_PATH")
    headers = {"Authorization": "Bearer " + token,
               "Accept": "application/vnd.github+json",
               "User-Agent": "agentora-r12-cloud",
               "X-GitHub-Api-Version": "2022-11-28"}
    raw = json.dumps(payload).encode() if payload is not None else None
    if raw is not None:
        headers["Content-Type"] = "application/json"
    try:
        req = Request("https://api.github.com" + path, data=raw,
                      headers=headers, method=method)
        with urlopen(req, timeout=15) as r:
            body = r.read(1000001)
        need(len(body) <= 1000000, "GITHUB_RESPONSE_TOO_LARGE")
        result = json.loads(body)
        need(type(result) in (dict, list), "GITHUB_RESPONSE_INVALID")
        return result
    except (HTTPError, URLError, OSError, ValueError):
        raise MissionHeld("GITHUB_REQUEST_UNAVAILABLE") from None


def fields(body):
    need(type(body) is str and 0 < len(body) <= 12000, "ISSUE_BODY_INVALID")
    values, active, lines = {}, None, []
    for line in body.splitlines() + ["### END"]:
        match = re.fullmatch(r"### ([A-Za-z ]+)", line.strip())
        if match:
            if active in FIELDS:
                need(active not in values, "DUPLICATE_ISSUE_FIELD")
                values[active] = "\n".join(lines).strip()
            active, lines = match.group(1), []
        elif active is not None:
            lines.append(line)
    need(set(values) == set(FIELDS)
         and all(0 < len(values[k]) <= 3000 and
                 values[k] != "_No response_" for k in FIELDS),
         "MISSING_ISSUE_FORM_FIELDS")
    need(REPO.fullmatch(values["Target repository"]) is not None,
         "REPOSITORY_OUTSIDE_PUBLIC_OWNER_SCOPE")
    need(values["Mission kind"] in KINDS, "MISSION_KIND_INVALID")
    return values


def issue_identity(issue, number):
    need(type(issue) is dict and issue.get("number") == number
         and "pull_request" not in issue and issue.get("state") == "open"
         and type(issue.get("title")) is str
         and issue["title"].startswith("[Fleet Mission] ")
         and len(issue["title"]) <= 180
         and (issue.get("user") or {}).get("login") == OWNER,
         "OPEN_OWNER_CREATED_MISSION_REQUIRED")
    form = fields(issue.get("body"))
    digest = hashlib.sha256(issue["body"].encode()).hexdigest()
    return form, digest


def journal(get, token, number, digest):
    state, last, seq = "UNTRIAGED", None, 0
    for page in range(1, 4):
        rows = get("/repos/" + HOME + "/issues/" + str(number)
                   + "/comments?per_page=100&page=" + str(page), token)
        need(type(rows) is list and len(rows) <= 100,
             "JOURNAL_COMMENTS_UNAVAILABLE")
        for item in rows:
            need(type(item) is dict, "JOURNAL_COMMENT_INVALID")
            raw = item.get("body")
            if type(raw) is not str or not raw.startswith(MARK):
                continue
            need((item.get("user") or {}).get("login") == "github-actions[bot]"
                 and item.get("created_at") == item.get("updated_at"),
                 "UNTRUSTED_OR_EDITED_JOURNAL")
            prefix, suffix = MARK + "\n~~~json\n", "\n~~~"
            need(raw.startswith(prefix) and raw.endswith(suffix)
                 and len(raw) <= 9000, "JOURNAL_FORMAT_INVALID")
            try:
                record = json.loads(raw[len(prefix):-len(suffix)])
            except ValueError:
                raise MissionHeld("JOURNAL_JSON_INVALID") from None
            seq += 1
            need(type(record) is dict and record.get("schema") == SCHEMA
                 and record.get("issue_number") == number
                 and record.get("issue_digest") == digest
                 and record.get("seq") == seq and record.get("prior_state") == state
                 and record.get("merge_authorized") is False
                 and record.get("worker_started") is False
                 and record.get("independent_qa_complete") is False,
                 "JOURNAL_CHAIN_OR_AUTHORITY_INVALID")
            cmd, new = record.get("command"), record.get("state")
            if cmd == "link_evidence":
                need(state in ("ROLE_PROPOSED", "QA_QUEUED_UNVERIFIED")
                     and new == state, "JOURNAL_EVIDENCE_TRANSITION_INVALID")
            else:
                need(cmd in NEXT and NEXT[cmd] == (state, new),
                     "JOURNAL_STATE_TRANSITION_INVALID")
            state, last = new, record
        if len(rows) < 100:
            break
        need(page < 3, "JOURNAL_PAGINATION_INCOMPLETE")
    return state, last, seq


def source(get, token, target):
    repo = get("/repos/" + target, token)
    need(type(repo) is dict and repo.get("full_name") == target
         and type(repo.get("id")) is int and repo["id"] > 0
         and repo.get("private") is False and repo.get("archived") is False
         and (repo.get("owner") or {}).get("login") == OWNER,
         "TARGET_NOT_PUBLIC_ACTIVE_OWNER_REPO")
    branch = repo.get("default_branch")
    need(type(branch) is str and re.fullmatch(r"[A-Za-z0-9._/-]{1,80}", branch)
         and not branch.startswith("/") and ".." not in branch,
         "DEFAULT_BRANCH_INVALID")
    ref = get("/repos/" + target + "/branches/" + branch, token)
    sha = (ref.get("commit") or {}).get("sha") if type(ref) is dict else None
    need(type(sha) is str and HEX40.fullmatch(sha) is not None,
         "LIVE_SOURCE_HEAD_UNVERIFIED")
    return repo["id"], branch, sha


def linked_pr(get, token, target, branch, number):
    positive(number, "PR")
    pr = get("/repos/" + target + "/pulls/" + str(number), token)
    need(type(pr) is dict and pr.get("number") == number
         and pr.get("state") == "open" and pr.get("merged_at") is None
         and (pr.get("base") or {}).get("ref") == branch
         and ((pr.get("base") or {}).get("repo") or {}).get("full_name") == target,
         "PR_NOT_OPEN_ON_TARGET_DEFAULT_BRANCH")
    sha = (pr.get("head") or {}).get("sha")
    need(type(sha) is str and HEX40.fullmatch(sha) is not None,
         "PR_HEAD_INVALID")
    return sha


def linked_r11(get, token, run_id):
    positive(run_id, "EVIDENCE_RUN")
    run = get("/repos/" + HOME + "/actions/runs/" + str(run_id), token)
    need(type(run) is dict and run.get("id") == run_id
         and run.get("path") == ".github/workflows/fleet-r11-cloud-evidence.yml"
         and run.get("status") == "completed" and run.get("conclusion") == "success"
         and (run.get("repository") or {}).get("full_name") == HOME,
         "R11_RUN_NOT_SUCCESSFUL")
    listed = get("/repos/" + HOME + "/actions/runs/" + str(run_id)
                 + "/artifacts?per_page=100", token)
    need(type(listed) is dict and type(listed.get("total_count")) is int
         and 0 < listed["total_count"] <= 100
         and type(listed.get("artifacts")) is list
         and len(listed["artifacts"]) == listed["total_count"],
         "R11_ARTIFACT_LIST_INVALID")
    matches = [a for a in listed["artifacts"]
               if type(a) is dict and a.get("name") ==
               "fleet-r11-cloud-review-" + str(run_id)]
    need(len(matches) == 1 and matches[0].get("expired") is False
         and type(matches[0].get("digest")) is str
         and matches[0]["digest"].startswith("sha256:")
         and HEX64.fullmatch(matches[0]["digest"][7:]) is not None,
         "R11_RECEIPT_NOT_RETAINED")
    # Merely linking an R11 result is never a claim that its pilot belongs
    # to this Issue's mission or has passed independent QA.
    return "https://github.com/" + HOME + "/actions/runs/" + str(run_id)


def transition(number, action, *, worker=None, reviewer=None, pr_number=None,
               evidence_run_id=None, confirmation=None, actor=None, token=None,
               get=None, post=None):
    need(action in ACTIONS and confirmation == CONFIRM and actor == OWNER,
         "OWNER_MANUAL_CONFIRMATION_REQUIRED")
    positive(number, "ISSUE")
    get = get or (lambda path, tok: github("GET", path, tok))
    post = post or (lambda path, tok, obj: github("POST", path, tok, obj))
    issue = get("/repos/" + HOME + "/issues/" + str(number), token)
    form, digest = issue_identity(issue, number)
    state, last, seq = journal(get, token, number, digest)
    target = form["Target repository"]
    repo_id, branch, head = source(get, token, target)
    if last:
        need(last.get("target_repo") == target
             and last.get("target_repo_id") == repo_id
             and last.get("branch") == branch,
             "MISSION_REPO_IDENTITY_DRIFT")
    old = state
    role = last.get("worker_role") if last else None
    reviewer_role = last.get("reviewer_role") if last else None
    pr = last.get("pr_number") if last else None
    pr_sha = last.get("pr_sha") if last else None
    run = last.get("evidence_run_id") if last else None
    url = last.get("evidence_url") if last else None
    if action in NEXT:
        required, state = NEXT[action]
        need(old == required, "TRANSITION_OUT_OF_ORDER")
    elif action == "link_evidence":
        need(old in ("ROLE_PROPOSED", "QA_QUEUED_UNVERIFIED")
             and target == OWNER + "/PhiMadaPrime" and run is None,
             "R11_LINK_NOT_ELIGIBLE")
        state = old
        url = linked_r11(get, token, evidence_run_id)
        run = evidence_run_id
    if action == "propose_worker":
        need(type(worker) is str and ROLE.fullmatch(worker) is not None,
             "WORKER_ROLE_INVALID")
        role = worker
    if action == "queue_qa":
        need(type(reviewer) is str and ROLE.fullmatch(reviewer) is not None
             and reviewer != role, "QA_REVIEWER_MUST_BE_DIFFERENT")
        reviewer_role = reviewer
        pr_sha = linked_pr(get, token, target, branch, pr_number)
        pr = pr_number
    record = {"schema": SCHEMA, "issue_number": number,
              "issue_digest": digest, "seq": seq + 1, "command": action,
              "prior_state": old, "state": state, "target_repo": target,
              "target_repo_id": repo_id, "branch": branch,
              "observed_source_head": head, "mission_kind": form["Mission kind"],
              "worker_role": role, "reviewer_role": reviewer_role,
              "pr_number": pr, "pr_sha": pr_sha,
              "evidence_run_id": run, "evidence_url": url,
              "worker_started": False, "independent_qa_complete": False,
              "verified_complete": False, "merge_authorized": False,
              "dispatch_authorized": False}
    body = MARK + "\n~~~json\n" + json.dumps(
        record, sort_keys=True, separators=(",", ":")) + "\n~~~"
    need(len(body) < 9000, "JOURNAL_RECORD_TOO_LARGE")
    state2, _, seq2 = journal(get, token, number, digest)
    need(state2 == old and seq2 == seq, "JOURNAL_CHANGED_BEFORE_WRITE")
    posted = post("/repos/" + HOME + "/issues/" + str(number) + "/comments",
                  token, {"body": body})
    need(type(posted) is dict and type(posted.get("id")) is int
         and posted["id"] > 0, "JOURNAL_WRITE_NOT_CONFIRMED")
    return {"schema": SCHEMA, "issue_number": number, "state": state,
            "command": action, "comment_id": posted["id"],
            "worker_started": False, "independent_qa_complete": False,
            "verified_complete": False, "merge_authorized": False}


def board(*, token=None, get=None):
    get = get or (lambda path, tok: github("GET", path, tok))
    rows, truncated = [], False
    for page in range(1, 3):
        issues = get("/repos/" + HOME +
                     "/issues?state=open&per_page=100&page=" + str(page), token)
        need(type(issues) is list and len(issues) <= 100,
             "BOARD_LIST_NOT_AVAILABLE")
        for item in issues:
            if (type(item) is not dict or "pull_request" in item
                or type(item.get("title")) is not str
                or not item["title"].startswith("[Fleet Mission] ")):
                continue
            if len(rows) >= 40:
                truncated = True
                break
            number = item.get("number")
            try:
                positive(number, "ISSUE")
                form, digest = issue_identity(item, number)
                state, last, _ = journal(get, token, number, digest)
                target = form["Target repository"]
                role = last.get("worker_role") if last else None
                pr = last.get("pr_number") if last else None
                run = last.get("evidence_run_id") if last else None
            except MissionHeld:
                state, target, role, pr, run = (
                    "HELD_INVALID_OR_CHANGED", None, None, None, None)
            rows.append({"issue_number": number, "title": item["title"][:180],
                         "state": state, "target_repo": target,
                         "proposed_role": role, "pr_number": pr,
                         "evidence_run_id": run})
        if truncated or len(issues) < 100:
            break
        if page == 2:
            truncated = True
    return {"schema": SCHEMA, "state": "READ_ONLY_BOARD_SNAPSHOT",
            "missions": rows, "truncated": truncated,
            "worker_started": False, "independent_qa_complete": False,
            "verified_complete": False, "merge_authorized": False}


def summary(report):
    if report["state"] == "READ_ONLY_BOARD_SNAPSHOT":
        rows = ["## Phi Fleet R12 mission board", "",
                "Proposed roles are not live workers. QA and merges are not approved.", ""]
        for mission in report["missions"]:
            rows.append("- [Issue #" + str(mission["issue_number"]) +
                "](https://github.com/" + HOME + "/issues/" +
                str(mission["issue_number"]) + "): **" + mission["state"] +
                "** · " + str(mission["target_repo"] or "identity held"))
        if not report["missions"]:
            rows.append("No owner-created Fleet Mission issues yet.")
        if report["truncated"]:
            rows.append("Warning: board truncated; more Issues may exist.")
    else:
        rows = ["## Phi Fleet R12 mission journal", "",
                "Issue #" + str(report["issue_number"]) + ": **" +
                report["state"] + "**", "",
                "No worker execution, independent QA, merge or deployment authorized."]
    return "\n".join(rows) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=sorted(ACTIONS | {"board"}))
    p.add_argument("--issue-number", type=int)
    p.add_argument("--worker")
    p.add_argument("--reviewer")
    p.add_argument("--pr-number", type=int)
    p.add_argument("--evidence-run-id", type=int)
    p.add_argument("--confirmation")
    p.add_argument("--out", default="fleet-r12")
    args = p.parse_args(argv)
    try:
        if args.action == "board":
            report = board(token=os.environ.get("GITHUB_TOKEN"))
        else:
            report = transition(args.issue_number, args.action,
                worker=args.worker, reviewer=args.reviewer,
                pr_number=args.pr_number, evidence_run_id=args.evidence_run_id,
                confirmation=args.confirmation, actor=os.environ.get("GITHUB_ACTOR"),
                token=os.environ.get("GITHUB_TOKEN"))
        status = 0
    except MissionHeld as exc:
        report = {"schema": SCHEMA, "state": "HELD_" + str(exc),
                  "verified_complete": False, "merge_authorized": False}
        status = 3
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "receipt.json"), "w",
              encoding="utf-8") as f:
        json.dump(report, f, sort_keys=True, indent=2)
        f.write("\n")
    with open(os.path.join(args.out, "summary.md"), "w",
              encoding="utf-8") as f:
        f.write(summary(report) if status == 0 else
                "## Fleet R12 HELD\n\nNo execution, QA, merge or deployment authorized.\n")
    print(json.dumps({"state": report["state"], "merge_authorized": False}))
    return status


if __name__ == "__main__":
    sys.exit(main())
