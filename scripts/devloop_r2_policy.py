"""R2 low-risk UI PR policy. Pure file gate + independently verified review gate.

This module is imported only from the trusted base branch of Agentora.
It never reads, checks out, or executes PR-provided code.
"""
from __future__ import annotations

import re

REPO = "MichaelWave369/Agentora"
LABEL = "phi-code-automerge"
HOLDS = frozenset({"hold", "do-not-merge", "needs-review", "security-review"})
# Deliberately tiny first code lane. No authentication, routing, backend,
# dependencies, config, workflows, policy, or tests can use this gate.
LOW_RISK_UI = frozenset({
    "web/src/components/Nav.tsx",
    "web/src/components/TemplateGallery.tsx",
})
REVIEWER_PERMISSIONS = frozenset({"write", "admin"})
_SHA = re.compile(r"^[a-f0-9]{40}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37})$")


class CodeHeld(Exception):
    """R2 code eligibility rejected without performing a repository write."""


def classify_files(files):
    """Return an advisory description or refuse the candidate's diff."""
    if not isinstance(files, list) or not 1 <= len(files) <= 2:
        raise CodeHeld("R2_FILE_COUNT_HELD")
    additions = deletions = 0
    paths = []
    for item in files:
        if not isinstance(item, dict):
            raise CodeHeld("R2_INVALID_DIFF_ITEM")
        path = item.get("filename")
        if path not in LOW_RISK_UI or item.get("status") != "modified":
            raise CodeHeld("R2_PATH_OR_STATUS_OUT_OF_SCOPE")
        if type(item.get("additions")) is not int or type(item.get("deletions")) is not int:
            raise CodeHeld("R2_MISSING_DIFF_COUNTS")
        a, d = item["additions"], item["deletions"]
        if a < 0 or d < 0:
            raise CodeHeld("R2_INVALID_DIFF_COUNTS")
        patch = item.get("patch")
        if not isinstance(patch, str) or not patch.startswith("@@") or len(patch) > 12000:
            raise CodeHeld("R2_DIFF_PATCH_UNAVAILABLE")
        additions += a
        deletions += d
        paths.append(path)
    if len(set(paths)) != len(paths):
        raise CodeHeld("R2_DUPLICATE_PATH")
    if additions > 75 or deletions > 40 or additions + deletions > 100:
        raise CodeHeld("R2_CHANGE_SIZE_HELD")
    return {"lane": "LOW_RISK_UI", "paths": sorted(paths),
            "additions": additions, "deletions": deletions}


def verify_code_pr(pr, expected_head, files):
    if not isinstance(pr, dict) or pr.get("state") != "open" or pr.get("draft") is not False:
        raise CodeHeld("R2_PR_NOT_OPEN_READY")
    base = pr.get("base") or {}
    head = pr.get("head") or {}
    if base.get("ref") != "main" or (base.get("repo") or {}).get("full_name") != REPO:
        raise CodeHeld("R2_BASE_NOT_MAIN")
    if (head.get("repo") or {}).get("full_name") != REPO:
        raise CodeHeld("R2_FORK_NOT_ELIGIBLE")
    sha = head.get("sha")
    if not isinstance(sha, str) or not _SHA.fullmatch(sha) or sha != expected_head:
        raise CodeHeld("R2_HEAD_CHANGED")
    labels = {str(x.get("name", "")).lower() for x in pr.get("labels", [])}
    if LABEL not in labels or HOLDS & labels or "phi-automerge" in labels:
        raise CodeHeld("R2_LABEL_MISSING_OR_HELD")
    if pr.get("changed_files") != len(files):
        raise CodeHeld("R2_DIFF_COUNT_MISMATCH")
    return classify_files(files)


def require_independent_review(api, token, number, head_sha, author_login):
    """Review must be on exact SHA, by a non-bot, non-author WRITE/ADMIN collaborator.

    Disregard self-attested PR body, labels, comments, stale approvals, and bot reviews.
    Any outstanding latest CHANGES_REQUESTED is a hard hold.
    """
    if not isinstance(author_login, str) or not _LOGIN.fullmatch(author_login):
        raise CodeHeld("R2_AUTHOR_IDENTITY_INVALID")
    reviews = api(token, f"/repos/{REPO}/pulls/{number}/reviews?per_page=100")
    if not isinstance(reviews, list) or len(reviews) >= 100:
        raise CodeHeld("R2_REVIEW_LIST_INCOMPLETE")
    most_recent = {}
    for r in reviews:
        if not isinstance(r, dict) or not isinstance(r.get("user"), dict):
            raise CodeHeld("R2_REVIEW_EVIDENCE_INVALID")
        login = r["user"].get("login")
        if not isinstance(login, str) or not _LOGIN.fullmatch(login):
            raise CodeHeld("R2_REVIEWER_IDENTITY_INVALID")
        most_recent[login.lower()] = r
    if any(r.get("state") == "CHANGES_REQUESTED" for r in most_recent.values()):
        raise CodeHeld("R2_CHANGES_REQUESTED")
    trusted = []
    for login, r in most_recent.items():
        if login == author_login.lower() or login.endswith("[bot]"):
            continue
        if r["user"].get("type") != "User":
            continue
        if r.get("state") != "APPROVED" or r.get("commit_id") != head_sha:
            continue
        permission = api(token, f"/repos/{REPO}/collaborators/{login}/permission")
        if (not isinstance(permission, dict)
                or permission.get("permission") not in REVIEWER_PERMISSIONS):
            continue
        trusted.append(login)
    if not trusted:
        raise CodeHeld("R2_INDEPENDENT_WRITE_REVIEW_REQUIRED")
    return sorted(trusted)
