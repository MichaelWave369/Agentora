"""Autonomous Turn R1: bounded exact-edit contracts, never authorization.

The initial worker is deterministic. It does not pretend a model was invoked.
Only a separate, live GitHub environment review can authorize a task.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from datetime import datetime, timezone
from pathlib import PurePosixPath
import re

from devloop_automerge import is_doc
from devloop_r2_policy import LOW_RISK_UI

REPO = "MichaelWave369/Agentora"
REPO_ID = 1167870912
OWNER_ID = 247459237
SCHEMA = "agentora.autonomous-task.v1"
RESULT_SCHEMA = "agentora.autonomous-proposal.v1"
MAX_JSON = 60000
MAX_SOURCE = 100000
HEX40 = re.compile(r"[0-9a-f]{40}\Z")
HEX64 = re.compile(r"[0-9a-f]{64}\Z")
TESTS = {"docs-contract", "web-build"}


class Held(Exception):
    """A fixed diagnostic; never include tokens or untrusted exception text."""


def need(value, code):
    if not value:
        raise Held(code)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def task_digest(task):
    return digest(b"agentora.autonomous-task.v1\n" + canonical(task))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def parse(raw):
    need(isinstance(raw, (str, bytes)) and 0 < len(raw) <= MAX_JSON, "JSON_SIZE")
    try:
        return json.loads(raw, object_pairs_hook=_unique,
                          parse_constant=lambda _: (_ for _ in ()).throw(Held("JSON_CONSTANT")))
    except (ValueError, UnicodeError, RecursionError):
        raise Held("JSON_INVALID") from None


def instant(value):
    need(isinstance(value, str) and len(value) <= 40, "TIME_INVALID")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Held("TIME_INVALID") from None
    need(result.tzinfo is not None, "TIME_ZONE_REQUIRED")
    return result


def safe_path(path):
    return (isinstance(path, str) and len(path) <= 180 and
            re.fullmatch(r"[A-Za-z0-9_./-]+", path) is not None and
            not path.startswith("/") and all(p not in ("", ".", "..")
                                              for p in path.split("/")) and
            str(PurePosixPath(path)) == path)


def edits_valid(edits, paths):
    need(isinstance(edits, list) and 1 <= len(edits) <= 10, "EDITS_COUNT")
    seen = set()
    for edit in edits:
        need(isinstance(edit, dict) and set(edit) ==
             {"path", "before_sha256", "old", "new"}, "EDIT_FIELDS")
        path = edit["path"]
        need(path in paths and path not in seen, "EDIT_PATH")
        seen.add(path)
        need(isinstance(edit["before_sha256"], str) and
             HEX64.fullmatch(edit["before_sha256"]), "EDIT_BEFORE_DIGEST")
        need(all(isinstance(edit[k], str) and 0 < len(edit[k].encode()) <= 16000
                 and "\x00" not in edit[k] for k in ("old", "new")) and
             edit["old"] != edit["new"], "EDIT_TEXT")


def validate(task, now=None):
    need(isinstance(task, dict) and set(task) == {
        "schema", "task_id", "repository", "repository_id", "target_branch",
        "source_sha", "created_utc", "expires_utc", "acceptance", "allowed_paths",
        "max_files", "max_changed_lines", "max_patch_bytes", "tests",
        "max_repairs", "merge_policy", "edits", "repairs", "human_scope",
        "phimada_request_sha256"}, "TASK_FIELDS")
    need(task["schema"] == SCHEMA and task["repository"] == REPO and
         type(task["repository_id"]) is int and task["repository_id"] == REPO_ID and
         task["target_branch"] == "main", "TASK_IDENTITY")
    need(isinstance(task["task_id"], str) and
         re.fullmatch(r"[a-z][a-z0-9-]{5,63}", task["task_id"]), "TASK_ID")
    need(isinstance(task["source_sha"], str) and HEX40.fullmatch(task["source_sha"]), "SOURCE_SHA")
    now = now or datetime.now(timezone.utc)
    created, expires = instant(task["created_utc"]), instant(task["expires_utc"])
    need(created <= now < expires and 0 < (expires-created).total_seconds() <= 86400,
         "AUTHORIZATION_EXPIRED_OR_CLOCK")
    paths = task["allowed_paths"]
    need(isinstance(paths, list) and 1 <= len(paths) <= 10 and
         all(safe_path(p) for p in paths) and len(set(paths)) == len(paths), "PATH_ALLOWLIST")
    policy = task["merge_policy"]
    need(policy in ("docs", "reviewed-code", "publish-only"), "MERGE_POLICY")
    need(all(is_doc(p) for p in paths) if policy == "docs" else
         all(p in LOW_RISK_UI for p in paths), "POLICY_PATH")
    for key, ceiling in (("max_files", 10), ("max_changed_lines", 100),
                         ("max_patch_bytes", 24000)):
        need(type(task[key]) is int and 1 <= task[key] <= ceiling, "CHANGE_BUDGET")
    need(len(paths) <= task["max_files"], "FILE_BUDGET")
    need(isinstance(task["tests"], list) and task["tests"] ==
         (["docs-contract"] if policy == "docs" else ["web-build"]), "TEST_ALLOWLIST")
    need(type(task["max_repairs"]) is int and 0 <= task["max_repairs"] <= 2 and
         isinstance(task["repairs"], list) and len(task["repairs"]) <= task["max_repairs"],
         "REPAIR_BUDGET")
    need(isinstance(task["acceptance"], list) and 1 <= len(task["acceptance"]) <= 10 and
         all(isinstance(s, str) and 1 <= len(s) <= 500 for s in task["acceptance"]), "ACCEPTANCE")
    need(isinstance(task["human_scope"], str) and 1 <= len(task["human_scope"]) <= 2000, "HUMAN_SCOPE")
    lineage = task["phimada_request_sha256"]
    need(lineage is None or isinstance(lineage, str) and HEX64.fullmatch(lineage), "LINEAGE_DIGEST")
    edits_valid(task["edits"], paths)
    for repair in task["repairs"]:
        need(isinstance(repair, dict) and set(repair) == {"check", "log_contains", "edits"}, "REPAIR_FIELDS")
        need(repair["check"] in ("backend (3.12)", "backend (3.13)", "web") and
             isinstance(repair["log_contains"], str) and
             12 <= len(repair["log_contains"]) <= 200, "REPAIR_SIGNATURE")
        edits_valid(repair["edits"], paths)
    return task


def apply_edits(files, edits):
    result = dict(files)
    for edit in edits:
        path = edit["path"]
        old = result.get(path)
        need(isinstance(old, str) and len(old.encode()) <= MAX_SOURCE and
             digest(old.encode()) == edit["before_sha256"] and
             old.count(edit["old"]) == 1, "EDIT_SOURCE_MISMATCH")
        result[path] = old.replace(edit["old"], edit["new"], 1)
        need(len(result[path].encode()) <= MAX_SOURCE, "RESULT_SIZE")
    return result


def expected_files(task, originals, attempt):
    need(type(attempt) is int and 0 <= attempt <= len(task["repairs"]) <= 2, "ATTEMPT_BUDGET")
    result = apply_edits(originals, task["edits"])
    for repair in task["repairs"][:attempt]:
        result = apply_edits(result, repair["edits"])
    return result


def proposal(task, originals, attempt):
    final = expected_files(task, originals, attempt)
    changes, patch = [], ""
    added = deleted = 0
    for path in sorted(final):
        before, after = originals[path], final[path]
        if before == after:
            continue
        diff = list(difflib.unified_diff(before.splitlines(keepends=True),
                     after.splitlines(keepends=True), fromfile="a/"+path, tofile="b/"+path))
        added += sum(line.startswith("+") and not line.startswith("+++") for line in diff)
        deleted += sum(line.startswith("-") and not line.startswith("---") for line in diff)
        patch += "".join(diff)
        changes.append({"path": path, "before_sha256": digest(before.encode()),
                        "after_sha256": digest(after.encode()), "content": after})
    need(1 <= len(changes) <= task["max_files"] and
         added+deleted <= task["max_changed_lines"] and
         len(patch.encode()) <= task["max_patch_bytes"], "FULL_DIFF_BUDGET")
    return {"schema": RESULT_SCHEMA, "task_sha256": task_digest(task),
            "source_sha": task["source_sha"], "attempt": attempt,
            "changes": changes, "patch": patch,
            "additions": added, "deletions": deleted}


def verify_proposal(task, originals, value, attempt):
    expected = proposal(task, originals, attempt)
    need(value == expected and canonical(value) == canonical(expected), "PROPOSAL_NOT_EXACT_AUTHORIZED_EDIT")
    return value


def permit_repair(task, failure, previous_head, attempt):
    need(type(attempt) is int and 1 <= attempt <= len(task["repairs"]) and
         attempt <= task["max_repairs"], "REPAIR_EXHAUSTED")
    need(isinstance(failure, dict) and failure.get("state") == "CI_FAILED" and
         failure.get("task_sha256") == task_digest(task) and
         failure.get("head_sha") == previous_head and
         failure.get("attempt") == attempt-1, "REPAIR_LINEAGE")
    failed = failure.get("failures")
    rule = task["repairs"][attempt-1]
    need(isinstance(failed, list) and len(failed) == 1 and
         failed[0].get("name") == rule["check"] and
         isinstance(failed[0].get("log_tail"), str) and
         rule["log_contains"] in failed[0]["log_tail"], "FAILURE_AMBIGUOUS_OR_OUT_OF_SCOPE")
    return True
