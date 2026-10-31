"""Agentora DevLoop R0: owner-authorized, documentation-only native auto-merge."""
import json
import os
import re
import sys
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

REPO = "MichaelWave369/Agentora"
OWNER = "MichaelWave369"
LABEL = "phi-automerge"
REQUIRED = {"backend (3.12)", "backend (3.13)", "web"}
HELD = {"hold", "do-not-merge", "needs-review", "security-review"}

class Block(Exception):
    pass

class AlreadyClean(Block):
    """GitHub declines auto-merge when all required conditions already passed."""
    pass

def api(token, path, payload=None, method=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    if method not in (None, "GET", "POST", "PUT"):
        raise Block("UNSUPPORTED_REQUEST_METHOD")
    request = Request("https://api.github.com" + path, data=data,
        method=method or ("POST" if data is not None else "GET"),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "Content-Type": "application/json",
                 "User-Agent": "agentora-devloop-r0"})
    try:
        with urlopen(request, timeout=15) as response:
            value = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise Block("API_UNAVAILABLE_" + type(exc).__name__) from None
    if not isinstance(value, (dict, list)):
        raise Block("INVALID_API_RESPONSE")
    return value

def is_doc(filename):
    if not isinstance(filename, str) or len(filename) > 240:
        return False
    if filename == "README.md":
        return True
    chunks = filename.split("/")
    return (len(chunks) >= 2 and chunks[0] == "docs" and
            filename.endswith(".md") and all(c not in ("", ".", "..") for c in chunks))

def verify_pr(pr, expected_head, files):
    if pr.get("state") != "open" or pr.get("draft") is not False:
        raise Block("PR_NOT_OPEN_AND_READY")
    if (pr.get("base") or {}).get("ref") != "main":
        raise Block("NOT_MAIN")
    if (pr.get("base") or {}).get("repo", {}).get("full_name") != REPO:
        raise Block("BASE_REPO_MISMATCH")
    if (pr.get("head") or {}).get("repo", {}).get("full_name") != REPO:
        raise Block("FORK_NOT_ELIGIBLE")
    sha = (pr.get("head") or {}).get("sha")
    if not isinstance(sha, str) or not re.fullmatch("[a-f0-9]{40}", sha) or sha != expected_head:
        raise Block("PR_HEAD_CHANGED")
    labels = {x.get("name", "").lower() for x in pr.get("labels", [])}
    if LABEL not in labels or HELD & labels:
        raise Block("LABEL_MISSING_OR_HELD")
    if (not isinstance(files, list) or not 1 <= len(files) <= 10 or
            pr.get("changed_files") != len(files)):
        raise Block("FILE_COUNT_INELIGIBLE")
    for f in files:
        if f.get("status") not in ("modified", "added") or not is_doc(f.get("filename")):
            raise Block("NON_DOC_CHANGE")

def verify_rules(rulesets):
    contexts = set()
    for rule in rulesets:
        if rule.get("target") != "branch" or rule.get("enforcement") != "active":
            continue
        includes = ((rule.get("conditions") or {}).get("ref_name") or {}).get("include") or []
        if not set(includes) & {"~DEFAULT_BRANCH", "main", "refs/heads/main"}:
            continue
        for r in rule.get("rules", []):
            if r.get("type") == "required_status_checks":
                contexts.update(c.get("context") for c in
                    ((r.get("parameters") or {}).get("required_status_checks") or []))
    if not REQUIRED.issubset(contexts):
        raise Block("MAIN_RULESET_MISSING_REQUIRED_CI")

def protected(token):
    rows = api(token, "/repos/" + REPO + "/rulesets?includes_parents=true")
    if not isinstance(rows, list) or len(rows) >= 100:
        raise Block("RULESETS_INCOMPLETE")
    details = []
    for row in rows:
        if row.get("enforcement") == "active":
            rid = row.get("id")
            if not isinstance(rid, int):
                raise Block("INVALID_RULESET_ID")
            detail = api(token, "/repos/" + REPO + "/rulesets/" + str(rid))
            if not isinstance(detail, dict):
                raise Block("INVALID_RULESET")
            details.append(detail)
    verify_rules(details)

def graphql(token, pr, enable, head=None):
    node = pr.get("node_id")
    if not isinstance(node, str) or not node:
        raise Block("PR_NODE_ID_MISSING")
    if enable:
        query = ("mutation($id:ID!,$head:GitObjectID!){"
                 "enablePullRequestAutoMerge(input:{pullRequestId:$id,"
                 "expectedHeadOid:$head,mergeMethod:SQUASH}){pullRequest{number}}}")
        variables = {"id": node, "head": head}
        field = "enablePullRequestAutoMerge"
    else:
        query = ("mutation($id:ID!){disablePullRequestAutoMerge(input:"
                 "{pullRequestId:$id}){pullRequest{number}}}")
        variables = {"id": node}
        field = "disablePullRequestAutoMerge"
    result = api(token, "/graphql", {"query": query, "variables": variables})
    if not isinstance(result, dict):
        raise Block("GRAPHQL_RESPONSE_INVALID")
    errors = result.get("errors") or []
    if errors:
        # Never print arbitrary GitHub response text or caller-controlled content.
        if (len(errors) == 1 and isinstance(errors[0], dict) and
                "clean status" in str(errors[0].get("message", "")).lower()):
            raise AlreadyClean("AUTO_MERGE_ALREADY_CLEAN")
        if any("resource not accessible" in str(e.get("message", "")).lower()
               for e in errors if isinstance(e, dict)):
            raise Block("GRAPHQL_TOKEN_ACCESS_REJECTED")
        raise Block("GRAPHQL_REJECTED_OTHER")
    if not (result.get("data") or {}).get(field):
        raise Block("GRAPHQL_SUCCESS_NOT_CONFIRMED")

def require_required_checks_green(token, sha):
    """Read exact-commit CI check runs; missing, failing or incomplete means HOLD."""
    data = api(token, "/repos/" + REPO + "/commits/" + sha +
               "/check-runs?per_page=100")
    if (not isinstance(data, dict) or type(data.get("total_count")) is not int
            or data["total_count"] >= 100 or
            not isinstance(data.get("check_runs"), list) or
            len(data["check_runs"]) != data["total_count"]):
        raise Block("CHECK_RUN_EVIDENCE_INCOMPLETE")
    observed = {name: [] for name in REQUIRED}
    for item in data["check_runs"]:
        name = item.get("name")
        if name in REQUIRED:
            # Do not accept a forged same-name context from another check app.
            if (item.get("app") or {}).get("slug") != "github-actions":
                raise Block("REQUIRED_CHECK_WRONG_SOURCE")
            observed[name].append(item)
    for name, items in observed.items():
        if not items:
            raise Block("REQUIRED_CHECK_MISSING")
        if any(i.get("status") != "completed" or
               i.get("conclusion") != "success" for i in items):
            raise Block("REQUIRED_CHECK_NOT_GREEN")


def merge_already_clean(token, number, expected, files):
    """Merge only the exact already-approved docs head, with GitHub rules enforced."""
    require_required_checks_green(token, expected)
    protected(token)
    latest = api(token, "/repos/" + REPO + "/pulls/" + str(number))
    if not isinstance(latest, dict):
        raise Block("REVALIDATED_PR_INVALID")
    verify_pr(latest, expected, files)
    response = api(token, "/repos/" + REPO + "/pulls/" + str(number) +
                   "/merge", {"sha": expected, "merge_method": "squash"},
                   method="PUT")
    if not isinstance(response, dict) or response.get("merged") is not True:
        raise Block("EXACT_HEAD_DIRECT_MERGE_NOT_CONFIRMED")
    return "EXACT_HEAD_REQUIRED_CI_GREEN_MERGED"


def run(event, token, repo):
    if repo != REPO:
        raise Block("WRONG_REPOSITORY")
    snapshot = event.get("pull_request") or {}
    number = snapshot.get("number")
    if type(number) is not int or number < 1:
        raise Block("INVALID_PR")
    pr = api(token, "/repos/" + REPO + "/pulls/" + str(number))
    action = event.get("action")
    event_label = (event.get("label") or {}).get("name")
    current_labels = {x.get("name", "").lower() for x in pr.get("labels", [])}
    if action in ("synchronize", "converted_to_draft") or (action == "unlabeled" and event_label == LABEL):
        if pr.get("auto_merge") and (LABEL in current_labels or (action == "unlabeled" and event_label == LABEL)):
            graphql(token, pr, False)
            return "AUTO_MERGE_REVOKED"
        return "NO_ACTIVE_AUTO_MERGE"
    if action != "labeled" or event_label != LABEL:
        raise Block("NO_OPT_IN_EVENT")
    if (event.get("sender") or {}).get("login") != OWNER:
        raise Block("NOT_OWNER_LABEL_EVENT")
    metadata = api(token, "/repos/" + REPO)
    if not isinstance(metadata, dict) or "allow_auto_merge" not in metadata:
        # GitHub omits merge-related fields from GET /repos unless the token
        # has both contents:read and contents:write. Missing != disabled.
        raise Block("AUTO_MERGE_SETTING_HIDDEN_CHECK_TOKEN_CONTENTS_WRITE")
    if metadata["allow_auto_merge"] is not True:
        raise Block("NATIVE_AUTO_MERGE_DISABLED")
    protected(token)
    if type(pr.get("changed_files")) is not int or not 1 <= pr["changed_files"] <= 10:
        raise Block("FILE_COUNT_INELIGIBLE")
    files = api(token, "/repos/" + REPO + "/pulls/" + str(number) + "/files?per_page=100")
    expected = (snapshot.get("head") or {}).get("sha")
    verify_pr(pr, expected, files)
    latest = api(token, "/repos/" + REPO + "/pulls/" + str(number))
    if latest.get("head", {}).get("sha") != expected:
        raise Block("PR_CHANGED_DURING_RECHECK")
    verify_pr(latest, expected, files)
    # GitHub's native auto-merge mutation is for PRs still waiting for checks.
    # It is invalid to depend on an error string to identify already-green PRs.
    # Read the exact-head check evidence BEFORE choosing the merge mechanism.
    try:
        require_required_checks_green(token, expected)
    except Block as exc:
        if str(exc) not in ("REQUIRED_CHECK_NOT_GREEN", "REQUIRED_CHECK_MISSING"):
            # Truncated, forged, or otherwise invalid check evidence is a HOLD,
            # not permission to queue a merge or fall back to another action.
            raise
        # Required CI has not passed. Only ask GitHub to wait for conditions;
        # never use the direct-merge route with failed or pending checks.
        try:
            graphql(token, latest, True, expected)
        except AlreadyClean:
            # Checks may complete between the first read and GraphQL request.
            # Re-check every safety condition before any exact-head merge.
            return merge_already_clean(token, number, expected, files)
        return "NATIVE_SHA_BOUND_AUTO_MERGE_REQUESTED"
    # Already green at the moment of authorization. Re-check all required
    # contexts, ruleset, labels, diff, and head, then send GitHub a normal
    # squash merge pinned to the immutable head SHA. GitHub still enforces
    # every repository merge restriction.
    return merge_already_clean(token, number, expected, files)

def main():
    try:
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
            event = json.load(stream)
        result = run(event, os.environ["GH_TOKEN"], os.environ.get("GITHUB_REPOSITORY"))
        print(result)
        return 0
    except (Block, KeyError, ValueError, OSError) as err:
        reason = str(err) if isinstance(err, Block) else "INVALID_RUNTIME_INPUT"
        print("::error::DEVLOOP_HELD " + reason, file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
