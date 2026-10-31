"""Read-only, exact-head next-rung handoff from a *pre-merge* approval manifest.

No issue creation, model invocation, workflow dispatch, credential transmission,
or repository mutation. This emits a receipt only.
"""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO = "MichaelWave369/Agentora"
OWNER = "MichaelWave369"
SCHEMA = "agentora.devloop.approved-next-rung.v1"
MANIFEST_PATH = "examples/development-board/approved-next-rung.json"
_SHA = re.compile(r"^[a-f0-9]{40}$")
_TASK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
MAX_ITEMS = 25


class HandoffHeld(Exception):
    pass


def read_approved_manifest(token: str, base_sha: str) -> dict:
    if not _SHA.fullmatch(base_sha or ""):
        raise HandoffHeld("INVALID_PREMERGE_BASE_SHA")
    # Fetch from the PR's pre-merge base commit, not the just-merged PR code.
    url = "https://api.github.com/repos/" + REPO + "/contents/" + (
        MANIFEST_PATH + "?ref=" + quote(base_sha, safe=""))
    req = Request(url, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "User-Agent": "agentora-devloop-r2-handoff",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        with urlopen(req, timeout=15) as response:
            raw = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            # The first deployment may predate this manifest. Do not invent approval.
            return {"schema": SCHEMA, "items": []}
        raise HandoffHeld("PREMERGE_MANIFEST_UNAVAILABLE") from None
    except (URLError, ValueError, TimeoutError):
        raise HandoffHeld("PREMERGE_MANIFEST_UNAVAILABLE") from None
    if not isinstance(raw, dict) or raw.get("encoding") != "base64":
        raise HandoffHeld("INVALID_MANIFEST_RESPONSE")
    encoded = raw.get("content")
    if not isinstance(encoded, str) or len(encoded) > 60000:
        raise HandoffHeld("INVALID_MANIFEST_SIZE")
    try:
        decoded = base64.b64decode(encoded, validate=False)
        if len(decoded) > 24000:
            raise HandoffHeld("MANIFEST_TOO_LARGE")
        content = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise HandoffHeld("INVALID_MANIFEST_JSON") from None
    return content


def assess(event: dict, repository: str, manifest: dict) -> dict:
    if repository != REPO or not isinstance(event, dict):
        raise HandoffHeld("UNEXPECTED_REPOSITORY")
    pr = event.get("pull_request") or {}
    base, head = pr.get("base") or {}, pr.get("head") or {}
    if (event.get("action") != "closed" or pr.get("merged") is not True or
            base.get("ref") != "main" or
            (base.get("repo") or {}).get("full_name") != REPO):
        raise HandoffHeld("NOT_MERGED_TO_MAIN")
    number = pr.get("number")
    source_sha, merge_sha = head.get("sha"), pr.get("merge_commit_sha")
    if (type(number) is not int or number < 1 or
            not isinstance(source_sha, str) or not _SHA.fullmatch(source_sha) or
            not isinstance(merge_sha, str) or not _SHA.fullmatch(merge_sha)):
        raise HandoffHeld("INVALID_MERGE_IDENTITY")
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise HandoffHeld("INVALID_APPROVAL_SCHEMA")
    items = manifest.get("items")
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        raise HandoffHeld("INVALID_APPROVAL_LIST")
    matched = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise HandoffHeld("INVALID_APPROVAL_ENTRY")
        key = item.get("source_pr")
        if type(key) is not int or key in seen:
            raise HandoffHeld("DUPLICATE_OR_INVALID_SOURCE_PR")
        seen.add(key)
        if key == number:
            matched.append(item)
    if not matched:
        return {"disposition": "NO_PREAPPROVED_NEXT_RUNG",
                "source_pr": number, "source_head_sha": source_sha,
                "merge_commit_sha": merge_sha, "executable": False}
    item = matched[0]
    task_id, title = item.get("task_id"), item.get("title")
    if (item.get("source_head_sha") != source_sha or
            item.get("approved_by") != OWNER or
            item.get("target_repo") != REPO or
            not isinstance(task_id, str) or not _TASK.fullmatch(task_id) or
            not isinstance(title, str) or not 1 <= len(title) <= 140 or
            any(ord(c) < 32 for c in title)):
        raise HandoffHeld("PREAPPROVAL_NOT_VALID_FOR_THIS_MERGE")
    return {"disposition": "READY_FOR_OPERATOR_DISPATCH",
            "source_pr": number, "source_head_sha": source_sha,
            "merge_commit_sha": merge_sha, "task_id": task_id,
            "title": title, "target_repo": REPO,
            "approved_by": OWNER, "executable": False}


def main():
    result = {"schema": "agentora.devloop.next-rung-receipt.v1",
              "disposition": "HELD", "executable": False,
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "approval_source": "premerge-base-sha"}
    rc = 0
    try:
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as handle:
            event = json.load(handle)
        if not isinstance(event, dict):
            raise HandoffHeld("INVALID_EVENT")
        pr = event.get("pull_request") or {}
        base_sha = (pr.get("base") or {}).get("sha")
        # Required for correctly scoped approval. Do not fall back to latest main.
        if not isinstance(base_sha, str) or not _SHA.fullmatch(base_sha):
            raise HandoffHeld("INVALID_PREMERGE_BASE_SHA")
        manifest = read_approved_manifest(os.environ["GH_TOKEN"], base_sha)
        result.update(assess(event, os.environ.get("GITHUB_REPOSITORY"), manifest))
        print("DEVLOOP_HANDOFF " + result["disposition"])
    except (HandoffHeld, KeyError, OSError, ValueError) as exc:
        result["reason"] = str(exc) if isinstance(exc, HandoffHeld) else "INVALID_HANDOFF_INPUT"
        print("::error::DEVLOOP_HANDOFF_HELD " + result["reason"])
        rc = 1
    finally:
        os.makedirs("devloop-artifacts", exist_ok=True)
        with open("devloop-artifacts/next-rung.json", "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
