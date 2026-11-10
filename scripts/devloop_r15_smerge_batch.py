"""R15: explicit-owner batch of exact-SHA Agentora documentation PRs.

This is deliberately NOT a standing authorization, cross-repo publisher,
agent-generated approval or exception to GitHub rulesets. Every merge requires
a new main-branch owner workflow_dispatch containing exact PR head SHAs.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import devloop_automerge as guard

REPO = "MichaelWave369/Agentora"
OWNER = "MichaelWave369"
OWNER_ID = 247459237
REPO_ID = 1167870912
CONFIRM = "SMERGE_AGENTORA_DOCS_EXACT_SHA"
MAX_BATCH = 5
_SHA = re.compile(r"[a-f0-9]{40}\Z")
_ENTRY = re.compile(r"([1-9][0-9]{0,6})@([a-f0-9]{40})\Z")
HELD = guard.HELD | {guard.CODE_LABEL, guard.SOLO_LABEL, "phi-automerge"}
OUT = Path("smerge-r15/receipt.json")


class Hold(ValueError):
    pass


def need(condition, reason):
    if not condition:
        raise Hold(reason)


def parse_heads(raw):
    need(type(raw) is str and 1 <= len(raw) <= 550, "BATCH_FORMAT_OR_SIZE")
    parts = [p.strip() for p in raw.split(",")]
    need(1 <= len(parts) <= MAX_BATCH, "BATCH_COUNT_LIMIT")
    rows, seen = [], set()
    for value in parts:
        match = _ENTRY.fullmatch(value)
        need(match is not None, "PR_NUMBER_AT_EXACT_SHA_REQUIRED")
        number, sha = int(match.group(1)), match.group(2)
        need(number not in seen, "DUPLICATE_PR")
        seen.add(number)
        rows.append((number, sha))
    return rows


def check_dispatch(env, event):
    need(env.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "NOT_MANUAL_DISPATCH")
    need(env.get("GITHUB_REPOSITORY") == REPO
         and env.get("GITHUB_REPOSITORY_ID") == str(REPO_ID), "WRONG_REPOSITORY")
    need(env.get("GITHUB_REF") == "refs/heads/main", "NOT_TRUSTED_MAIN")
    need(env.get("GITHUB_ACTOR") == OWNER
         and env.get("GITHUB_ACTOR_ID") == str(OWNER_ID), "NOT_OWNER_ACTOR")
    need(env.get("GITHUB_RUN_ATTEMPT") == "1", "REPLAYED_RUN_NOT_AUTHORIZED")
    need(type(event) is dict and type(event.get("sender")) is dict
         and event["sender"].get("id") == OWNER_ID
         and event["sender"].get("login") == OWNER, "SENDER_NOT_OWNER")
    repository = event.get("repository")
    need(type(repository) is dict
         and repository.get("full_name") == REPO
         and repository.get("id") == REPO_ID, "EVENT_REPOSITORY_MISMATCH")
    inputs = event.get("inputs")
    need(type(inputs) is dict, "MISSING_INPUTS")
    mode = inputs.get("mode")
    need(mode in ("preview", "merge"), "INVALID_MODE")
    if mode == "merge":
        need(inputs.get("confirmation") == CONFIRM, "EXPLICIT_OWNER_CONFIRMATION_REQUIRED")
    return mode, parse_heads(inputs.get("pr_heads"))


def api(token, path, payload=None, method=None):
    return guard.api(token, path, payload=payload, method=method)


def fetch_files(token, number, expected_count):
    need(type(expected_count) is int and 1 <= expected_count <= 10,
         "DOC_FILE_COUNT_OUT_OF_SCOPE")
    rows = api(token, f"/repos/{REPO}/pulls/{number}/files?per_page=100")
    need(type(rows) is list and len(rows) == expected_count,
         "INCOMPLETE_PR_DIFF")
    return rows


def file_fingerprint(files):
    """Fingerprint the actual displayed patch, not merely blob/count metadata.

    A changed base can alter diff context without changing the head blob SHA
    or line totals. Missing/truncated/binary patches therefore HOLD.
    """
    entries = []
    for row in files:
        patch = row.get("patch")
        need(type(patch) is str and patch.startswith("@@ ")
             and len(patch.encode("utf8")) <= 30_000,
             "DOC_PATCH_MISSING_OR_TOO_LARGE")
        item = {key: row.get(key) for key in
            ("filename", "status", "sha", "additions", "deletions", "changes")}
        item["patch_sha256"] = hashlib.sha256(patch.encode("utf8")).hexdigest()
        entries.append(item)
    encoded = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def docs_snapshot(pr, number, sha, files):
    need(type(pr) is dict and pr.get("number") == number, "PR_IDENTITY_MISMATCH")
    need(pr.get("state") == "open" and pr.get("draft") is False, "PR_NOT_READY")
    need((pr.get("base") or {}).get("ref") == "main"
         and ((pr.get("base") or {}).get("repo") or {}).get("full_name") == REPO,
         "BASE_NOT_AGENTORA_MAIN")
    need(((pr.get("head") or {}).get("repo") or {}).get("full_name") == REPO,
         "FORK_NOT_ALLOWED")
    need((pr.get("head") or {}).get("sha") == sha and _SHA.fullmatch(sha),
         "HEAD_SHA_DRIFT")
    owner = pr.get("user") or {}
    need(owner.get("login") == OWNER and owner.get("id") == OWNER_ID,
         "ONLY_OWNER_AUTHORED_DOCS")
    labels = pr.get("labels")
    need(type(labels) is list
         and all(type(l) is dict and type(l.get("name")) is str for l in labels),
         "LABEL_EVIDENCE_INVALID")
    label_set = {l["name"].lower() for l in labels}
    need(not label_set & HELD, "HOLD_OR_CONFLICTING_AUTOMERGE_LABEL")
    # The owner-entered exact SHA in the trusted workflow is this lane's
    # one-shot approval. Do not invent an owner label or alter DevLoop R0.
    need(type(pr.get("changed_files")) is int
         and pr["changed_files"] == len(files), "DOC_DIFF_INCOMPLETE")
    for row in files:
        need(type(row) is dict
             and row.get("status") in ("added", "modified")
             and guard.is_doc(row.get("filename")), "NON_DOC_CHANGE")
        need(type(row.get("additions")) is int
             and type(row.get("deletions")) is int
             and 0 <= row["additions"] <= 1000
             and 0 <= row["deletions"] <= 1000, "DOC_DIFF_COUNT_INVALID")
    base_sha = (pr.get("base") or {}).get("sha")
    need(type(base_sha) is str and _SHA.fullmatch(base_sha), "BASE_SHA_MISSING")
    need(pr.get("mergeable") is True, "GITHUB_MERGEABILITY_NOT_READY")
    return {"number":number, "head_sha":sha, "base_sha":base_sha,
            "files_sha256":file_fingerprint(files),
            "url":f"https://github.com/{REPO}/pull/{number}"}


def all_checks_green(token, sha):
    data = api(token, f"/repos/{REPO}/commits/{sha}/check-runs?per_page=100")
    need(type(data) is dict and type(data.get("total_count")) is int
         and 1 <= data["total_count"] < 100 and type(data.get("check_runs")) is list
         and len(data["check_runs"]) == data["total_count"],
         "ALL_CHECK_EVIDENCE_INCOMPLETE")
    for item in data["check_runs"]:
        need(type(item) is dict and item.get("status") == "completed"
             and item.get("conclusion") == "success",
             "NON_GREEN_OR_SKIPPED_CHECK")
    # GitHub legacy commit status contexts are separate from check runs.
    statuses = api(token, f"/repos/{REPO}/commits/{sha}/status")
    need(type(statuses) is dict and type(statuses.get("statuses")) is list,
         "COMMIT_STATUS_UNAVAILABLE")
    need(all(type(s) is dict and s.get("state") == "success"
             for s in statuses["statuses"]), "NON_GREEN_COMMIT_STATUS")
    guard.require_required_checks_green(token, sha)


def inspect_candidate(token, number, sha):
    pr = api(token, f"/repos/{REPO}/pulls/{number}")
    files = fetch_files(token, number, pr.get("changed_files") if type(pr) is dict else None)
    snapshot = docs_snapshot(pr, number, sha, files)
    guard.protected(token)
    all_checks_green(token, sha)
    return snapshot


def verify_live_main(token, expected_sha, fetch=api):
    """Require that the actual branch ref equals the last verified merge.

    PR metadata may lag a squash merge, and another actor may advance main
    between batch items. Neither condition grants an implicit rebase.
    """
    need(type(expected_sha) is str and _SHA.fullmatch(expected_sha),
         "EXPECTED_MAIN_SHA_INVALID")
    ref = fetch(token, f"/repos/{REPO}/git/ref/heads/main")
    need(type(ref) is dict and ref.get("ref") == "refs/heads/main"
         and type(ref.get("object")) is dict
         and ref["object"].get("type") == "commit"
         and ref["object"].get("sha") == expected_sha,
         "MAIN_HEAD_CHANGED_OR_NOT_YET_OBSERVED")
    return expected_sha


def run_batch(token, mode, rows, reader=inspect_candidate, fetch=api):
    decisions = []
    # All candidates must pass before the first write. A single HOLD means
    # ZERO merges, even if earlier entries were green.
    for number, sha in rows:
        try:
            evidence = reader(token, number, sha)
            decisions.append({"pr":number,"sha":sha,"state":"READY_FOR_OWNER_DISPATCH",
                              "snapshot":evidence})
        except (Hold, guard.Block, KeyError, ValueError, TypeError) as error:
            reason = str(error) if isinstance(error,(Hold, guard.Block)) else "INVALID_REMOTE_EVIDENCE"
            decisions.append({"pr":number,"sha":sha,"state":"HELD","reason":reason[:90]})
    if mode == "preview" or any(d["state"] == "HELD" for d in decisions):
        return decisions

    # Every candidate must begin against the same source baseline. If this
    # is not true, no PR is attempted, even when all checks are green.
    baseline = decisions[0]["snapshot"].get("base_sha")
    for row in decisions:
        if row["snapshot"].get("base_sha") != baseline:
            row.update(state="HELD", reason="INITIAL_MAIN_BASES_DIVERGE")
    if any(row["state"] == "HELD" for row in decisions):
        return decisions

    expected_main = baseline
    for i, row in enumerate(decisions):
        number, sha, original = row["pr"], row["sha"], row["snapshot"]
        try:
            # Fresh GitHub PR/diff/rules/CI, not the earlier preflight result.
            latest = reader(token, number, sha)
            need(type(latest) is dict, "FRESH_PR_SNAPSHOT_INVALID")
            if i == 0:
                need(latest == original, "PR_OR_BASE_CHANGED_DURING_BATCH")
            else:
                # Permit precisely one change after our preceding squash
                # merge: the base ref can advance to that *verified merge SHA*.
                # All other approved identity/diff fields must remain exact.
                unchanged = {k:v for k,v in latest.items() if k != "base_sha"}
                approved = {k:v for k,v in original.items() if k != "base_sha"}
                need(unchanged == approved,
                     "PR_OR_PATCH_CHANGED_AFTER_PRIOR_MERGE")
                need(latest.get("base_sha") == expected_main,
                     "SUBSEQUENT_PR_BASE_NOT_PREVIOUS_MERGE")
            verify_live_main(token, expected_main, fetch)
            response = fetch(token, f"/repos/{REPO}/pulls/{number}/merge",
                             {"sha":sha,"merge_method":"squash"}, "PUT")
            need(type(response) is dict and response.get("merged") is True
                 and type(response.get("sha")) is str
                 and _SHA.fullmatch(response["sha"]),
                 "GITHUB_DID_NOT_CONFIRM_MERGE")
            readback = fetch(token, f"/repos/{REPO}/pulls/{number}")
            need(type(readback) is dict and readback.get("merged") is True
                 and readback.get("merge_commit_sha") == response["sha"],
                 "MERGE_READBACK_UNVERIFIED")
            # Do not proceed if another writer advanced main meanwhile.
            expected_main = response["sha"]
            verify_live_main(token, expected_main, fetch)
            row.update(state="MERGED_GITHUB_READBACK", merge_commit_sha=expected_main)
        except (Hold, guard.Block, ValueError, KeyError, TypeError) as error:
            reason = str(error) if isinstance(error,(Hold,guard.Block)) else "INVALID_REMOTE_EVIDENCE"
            row.update(state="HELD_AFTER_WRITE_ATTEMPT",reason=reason[:90])
            for remaining in decisions[i+1:]:
                remaining["state"]="NOT_ATTEMPTED_AFTER_HOLD"
            break
    return decisions


def write_receipt(mode, decisions, run_id):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    receipt = {"schema":"agentora.smerge-r15.batch-docs.v1",
        "repository":REPO, "mode":mode, "run_id":run_id,
        "time_utc":datetime.now(timezone.utc).isoformat(),
        "scope":"OWNER_DISPATCH_AGENTORA_DOCS_ONLY",
        "standing_approval":False, "code_write_policy_changed":False,
        "items":decisions}
    OUT.write_text(json.dumps(receipt,sort_keys=True,indent=2)+"\n",encoding="utf8")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary,"a",encoding="utf8") as f:
            f.write("# R15 Smerge Batch · "+str(mode)+"\n\n")
            f.write("| PR | State | Reason |\n| --- | --- | --- |\n")
            for d in decisions:
                f.write(f"| #{d['pr']} | {d['state']} | {d.get('reason','')} |\n")
            f.write("\nOwner approval applies only to listed exact SHAs. No cross-repo or code merges.\n")
    return receipt


def main():
    mode, decisions = "unverified", []
    try:
        path = os.environ.get("GITHUB_EVENT_PATH")
        need(path and Path(path).is_file(), "MISSING_GITHUB_EVENT")
        event = json.loads(Path(path).read_text(encoding="utf8"))
        mode, rows = check_dispatch(os.environ,event)
        token = os.environ.get("GH_TOKEN")
        need(type(token) is str and len(token) > 10, "GITHUB_TOKEN_MISSING")
        decisions = run_batch(token,mode,rows)
        return 1 if mode == "merge" and any(d["state"] != "MERGED_GITHUB_READBACK" for d in decisions) else 0
    except (Hold, guard.Block, ValueError, OSError, KeyError, TypeError) as error:
        reason = str(error) if isinstance(error,(Hold,guard.Block)) else "INVALID_RUNTIME_INPUT"
        decisions.append({"pr":None,"state":"HELD","reason":reason[:90]})
        return 1
    finally:
        receipt = write_receipt(mode,decisions,os.environ.get("GITHUB_RUN_ID"))
        print("AGENTORA_SMERGE_R15:"+json.dumps({
            "mode":receipt["mode"],"states":[d["state"] for d in decisions]}))


if __name__ == "__main__":
    raise SystemExit(main())
