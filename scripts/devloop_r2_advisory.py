"""R2 cloud advisory: classify candidate UI PRs without granting merge authority.

GitHub read endpoints only, no PR-head checkout and no writes other than a
local temporary JSON receipt uploaded by Actions.
"""
import json
import os
import re
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from devloop_r2_policy import CodeHeld, REPO, classify_files, require_independent_review

SHA = re.compile(r"^[a-f0-9]{40}$")


def read(token, path, payload=None, method=None):
    if payload is not None or method not in (None, "GET"):
        raise CodeHeld("R2_ADVISORY_READ_ONLY")
    request = Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + token,
        "User-Agent": "agentora-devloop-r2-advisory",
        "X-GitHub-Api-Version": "2022-11-28",
    }, method="GET")
    try:
        with urlopen(request, timeout=15) as response:
            return json.load(response)
    except (HTTPError, URLError, ValueError, TimeoutError):
        raise CodeHeld("R2_GITHUB_READ_UNAVAILABLE") from None


def analyze(event, repo, api, token):
    if not isinstance(event, dict) or repo != REPO:
        raise CodeHeld("R2_INVALID_EVENT_REPO")
    pr_event = event.get("pull_request") or {}
    number = pr_event.get("number")
    if type(number) is not int or number < 1:
        raise CodeHeld("R2_INVALID_PR_NUMBER")
    pr = api(token, f"/repos/{REPO}/pulls/{number}")
    if not isinstance(pr, dict):
        raise CodeHeld("R2_INVALID_PR_DATA")
    sha = (pr.get("head") or {}).get("sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise CodeHeld("R2_INVALID_PR_SHA")
    receipt = {"schema": "agentora.devloop.r2-advisory.v1",
               "repository": REPO, "pr_number": number, "head_sha": sha,
               "disposition": "OUT_OF_SCOPE", "merge_authorized": False}
    if pr.get("state") != "open" or pr.get("draft") or (
            (pr.get("base") or {}).get("ref") != "main" or
            (pr.get("head") or {}).get("repo", {}).get("full_name") != REPO):
        receipt["reason"] = "R2_PR_NOT_SAME_REPO_MAIN_READY"
        return receipt
    count = pr.get("changed_files")
    if type(count) is not int or not 1 <= count <= 2:
        receipt["reason"] = "R2_FILE_COUNT_HELD"
        return receipt
    files = api(token, f"/repos/{REPO}/pulls/{number}/files?per_page=100")
    if not isinstance(files, list) or len(files) != count:
        raise CodeHeld("R2_INCOMPLETE_FILE_LIST")
    try:
        receipt["classification"] = classify_files(files)
    except CodeHeld as error:
        receipt["reason"] = str(error)
        return receipt
    receipt["disposition"] = "LOW_RISK_UI_CANDIDATE"
    try:
        reviewer_names = require_independent_review(
            api, token, number, sha, (pr.get("user") or {}).get("login"))
        receipt["reviewers"] = reviewer_names
        receipt["review_status"] = "CURRENT_SHA_INDEPENDENT_APPROVAL_VERIFIED"
    except CodeHeld as error:
        receipt["review_status"] = str(error)
    # Current CI and live owner authorization are checked at actual merge time.
    # Classification never grants merge authority.
    return receipt


def main():
    receipt = {"schema": "agentora.devloop.r2-advisory.v1",
               "disposition": "HELD", "merge_authorized": False}
    rc = 0
    try:
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as stream:
            event = json.load(stream)
        receipt = analyze(event, os.environ.get("GITHUB_REPOSITORY"),
                          read, os.environ["GH_TOKEN"])
        print("R2_ADVISORY " + receipt["disposition"])
    except (CodeHeld, KeyError, OSError, ValueError) as error:
        receipt["reason"] = str(error) if isinstance(error, CodeHeld) else "R2_INVALID_RUNTIME_INPUT"
        print("::error::R2_ADVISORY_HELD " + receipt["reason"])
        rc = 1
    finally:
        receipt["recorded_utc"] = datetime.now(timezone.utc).isoformat()
        os.makedirs("devloop-artifacts", exist_ok=True)
        with open("devloop-artifacts/r2-advisory.json", "w", encoding="utf-8") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True)
            stream.write("\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
