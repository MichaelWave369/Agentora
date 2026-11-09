"""Fleet R14: correlate real R13 audit/QA ZIPs to one owner-authored mission.

GitHub Actions only; no operator-installed CLI, SQLite or local agent.
One explicit owner-confirmed write may append a bounded Issue comment.
A second, separately confirmed owner acknowledgement does not approve code,
confer independent human QA, authorize dispatch, or merge/deploy anything.
"""
from datetime import datetime, timedelta, timezone
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import sys

import fleet_r11_cloud_evidence as storage
import fleet_r12_github_missions as r12
import fleet_r13_independent_qa as qa

SCHEMA = "agentora.fleet.r14.evidence-handoff.v1"
MARK = "<!-- agentora-fleet-r14-handoff-v1 -->"
QA_WORKFLOW = ".github/workflows/fleet-r13-independent-qa.yml"
QA_STATE = "AUDIT_METADATA_CORROBORATED_PENDING_HUMAN_QA"
PHASE_EVIDENCE = "EVIDENCE_LINKED_PENDING_OWNER_REVIEW"
PHASE_ACK = "OWNER_REVIEW_ACKNOWLEDGED_NO_APPROVAL"
CONFIRM_LINK = "LINK_VERIFIED_R13_EVIDENCE"
CONFIRM_REVIEW = "I_REVIEWED_R13_RECEIPTS_NO_MERGE_APPROVAL"
COMMANDS = {"link", "acknowledge"}
MAX_ZIP = 1_000_000
MAX_COMMENT_PAGES = 3


def need(ok, reason):
    if not ok:
        raise r12.MissionHeld(reason)


def utc(value):
    need(type(value) is str, "R14_TIMESTAMP_INVALID")
    try:
        out = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise r12.MissionHeld("R14_TIMESTAMP_INVALID") from None
    need(out.tzinfo is not None, "R14_TIMESTAMP_INVALID")
    return out.astimezone(timezone.utc)


def history(get, token, number, issue_digest):
    """Strict one/two-entry R14 subjournal, isolated from R12's state machine."""
    found = []
    for page in range(1, MAX_COMMENT_PAGES + 1):
        rows = get(f"/repos/{r12.HOME}/issues/{number}/comments?per_page=100&page={page}",
                   token)
        need(type(rows) is list and len(rows) <= 100,
             "R14_COMMENT_LIST_INVALID")
        for comment in rows:
            need(type(comment) is dict, "R14_COMMENT_INVALID")
            body = comment.get("body")
            if type(body) is not str or not body.startswith(MARK):
                continue
            need((comment.get("user") or {}).get("login") == "github-actions[bot]"
                 and comment.get("created_at") == comment.get("updated_at"),
                 "R14_UNTRUSTED_OR_EDITED_COMMENT")
            prefix, suffix = MARK + "\n~~~json\n", "\n~~~"
            need(body.startswith(prefix) and body.endswith(suffix)
                 and len(body) <= 9000, "R14_RECORD_FORMAT_INVALID")
            try:
                item = json.loads(body[len(prefix):-len(suffix)])
            except ValueError:
                raise r12.MissionHeld("R14_RECORD_JSON_INVALID") from None
            need(type(item) is dict and item.get("schema") == SCHEMA
                 and item.get("mission_issue") == number
                 and item.get("issue_sha256") == issue_digest
                 and item.get("seq") == len(found) + 1
                 and item.get("worker_execution_authorized") is False
                 and item.get("independent_human_qa_complete") is False
                 and item.get("merge_authorized") is False
                 and item.get("deployment_authorized") is False,
                 "R14_RECORD_IDENTITY_OR_AUTHORITY_INVALID")
            if not found:
                need(item.get("state") == PHASE_EVIDENCE
                     and item.get("command") == "link"
                     and item.get("owner_acknowledged") is False,
                     "R14_FIRST_RECORD_INVALID")
            else:
                previous = found[-1]
                need(len(found) == 1
                     and item.get("state") == PHASE_ACK
                     and item.get("command") == "acknowledge"
                     and item.get("owner_acknowledged") is True
                     and item.get("audit_run_id") == previous.get("audit_run_id")
                     and item.get("qa_run_id") == previous.get("qa_run_id")
                     and item.get("qa_artifact_sha256") ==
                         previous.get("qa_artifact_sha256")
                     and item.get("audit_artifact_sha256") ==
                         previous.get("audit_artifact_sha256"),
                     "R14_ACKNOWLEDGEMENT_CHAIN_INVALID")
            found.append(item)
        if len(rows) < 100:
            break
        need(page < MAX_COMMENT_PAGES, "R14_COMMENT_PAGINATION_LIMIT")
    return found


def correlate(number, audit_run_id, qa_run_id, *, token, get,
              download, now=None):
    """Fresh independent cross-check of two genuine GitHub-owned receipts."""
    r12.positive(number, "MISSION")
    r12.positive(audit_run_id, "AUDIT_RUN")
    r12.positive(qa_run_id, "QA_RUN")
    need(audit_run_id != qa_run_id, "R14_RUN_IDS_MUST_DIFFER")
    now = now or datetime.now(timezone.utc)
    need(isinstance(now, datetime) and now.tzinfo is not None,
         "R14_CLOCK_INVALID")
    now = now.astimezone(timezone.utc)

    # R13 verifier independently rechecks the audit ZIP, actual GitHub digest,
    # exact R12 Issue journal, source SHA and live repository metadata.
    fresh = qa.review(audit_run_id, token=token, get=get,
                      download=download, now=now)
    need(fresh["state"] == QA_STATE and fresh["mission_issue"] == number
         and fresh["independent_qa_complete"] is False
         and fresh["merge_authorized"] is False,
         "R14_AUDIT_MISSION_OR_QA_MISMATCH")
    root = f"/repos/{r12.HOME}/actions/runs/{qa_run_id}"
    run = get(root, token)
    need(type(run) is dict and run.get("id") == qa_run_id
         and run.get("path") == QA_WORKFLOW
         and run.get("event") == "workflow_run"
         and run.get("run_attempt") == 1
         and run.get("status") == "completed"
         and run.get("conclusion") == "success"
         and run.get("head_branch") == "main"
         and (run.get("repository") or {}).get("full_name") == r12.HOME,
         "R14_QA_GITHUB_RUN_IDENTITY_INVALID")
    # QA is downstream of this audit, not an unrelated successful workflow.
    qa_created = utc(run.get("created_at"))
    audit_run = get(f"/repos/{r12.HOME}/actions/runs/{audit_run_id}", token)
    audit_created = utc(audit_run.get("created_at")) if type(audit_run) is dict else None
    need(audit_created is not None and
         audit_created <= qa_created <= now + timedelta(minutes=5)
         and now - qa_created <= timedelta(days=7),
         "R14_QA_TIME_NOT_CORRELATED")
    artifacts = get(root + "/artifacts?per_page=100", token)
    need(type(artifacts) is dict and type(artifacts.get("total_count")) is int
         and 1 <= artifacts["total_count"] <= 100
         and type(artifacts.get("artifacts")) is list
         and len(artifacts["artifacts"]) == artifacts["total_count"],
         "R14_QA_ARTIFACT_CATALOG_INCOMPLETE")
    found = [a for a in artifacts["artifacts"]
             if type(a) is dict
             and a.get("name") == f"fleet-r13-qa-{qa_run_id}"]
    need(len(found) == 1, "R14_QA_ARTIFACT_MISSING_OR_AMBIGUOUS")
    art = found[0]
    need(type(art.get("id")) is int and art["id"] > 0
         and type(art.get("size_in_bytes")) is int
         and 0 < art["size_in_bytes"] <= MAX_ZIP
         and art.get("expired") is False
         and type(art.get("digest")) is str
         and art["digest"].startswith("sha256:")
         and r12.HEX64.fullmatch(art["digest"][7:]) is not None,
         "R14_QA_ARTIFACT_METADATA_UNTRUSTED")
    if art.get("workflow_run") is not None:
        need((art["workflow_run"] or {}).get("id") == qa_run_id,
             "R14_QA_ARTIFACT_WRONG_RUN")
    raw = download(art["id"], token)
    need(type(raw) is bytes and 0 < len(raw) <= MAX_ZIP
         and hashlib.sha256(raw).hexdigest() == art["digest"][7:],
         "R14_QA_ORIGINAL_ZIP_DIGEST_MISMATCH")
    recorded = qa.read_receipt(raw)
    # Compare every field, not just the green flag. The synthetic status is
    # not a substitute for the original ZIP + rechecked R13 verifier output.
    need(recorded == fresh
         and recorded.get("schema") == qa.SCHEMA
         and recorded.get("automated_independent_evidence_recheck") is True
         and recorded.get("independent_human_qa_complete") is False,
         "R14_QA_RECEIPT_NOT_INDEPENDENTLY_CORROBORATED")
    branch_path = (f"/repos/{fresh['target_repository']}/branches/main")
    branch = get(branch_path, token)
    need(type(branch) is dict and type(branch.get("protected")) is bool
         and (branch.get("commit") or {}).get("sha") == fresh["source_sha"],
         "R14_BRANCH_STATUS_OR_HEAD_UNVERIFIED")
    issue = get(f"/repos/{r12.HOME}/issues/{number}", token)
    form, digest = r12.issue_identity(issue, number)
    need(form["Target repository"] == fresh["target_repository"]
         and form["Mission kind"] == "Read-only audit",
         "R14_MISSION_ISSUE_IDENTITY_CHANGED")
    state, last, seq = r12.journal(get, token, number, digest)
    need(state == "ROLE_PROPOSED" and seq >= 2
         and last["worker_role"] == "builder_a",
         "R14_MISSION_ROLE_OR_STATE_CHANGED")
    return {
        "mission_issue": number,
        "issue_sha256": digest,
        "target_repository": fresh["target_repository"],
        "source_sha": fresh["source_sha"],
        "audit_run_id": audit_run_id,
        "qa_run_id": qa_run_id,
        "audit_artifact_sha256": fresh["artifact_sha256"],
        "qa_artifact_sha256": art["digest"][7:],
        "default_branch_protected": branch["protected"],
        "branch_protection_gate_passed": branch["protected"] is True,
        "code_write_blocked": True,  # No code write authority in R14.
    }


def transition(number, command, audit_run_id, qa_run_id, *,
               confirmation, actor, token, get=None, post=None,
               download=None, now=None):
    expected = {"link": CONFIRM_LINK, "acknowledge": CONFIRM_REVIEW}
    need(command in COMMANDS and actor == r12.OWNER
         and confirmation == expected[command],
         "R14_EXPLICIT_OWNER_CONFIRMATION_REQUIRED")
    get = get or (lambda path, tok: r12.github("GET", path, tok))
    post = post or (lambda path, tok, payload:
                    r12.github("POST", path, tok, payload))
    download = download or storage.download_artifact
    facts = correlate(number, audit_run_id, qa_run_id, token=token, get=get,
                      download=download, now=now)
    prior = history(get, token, number, facts["issue_sha256"])
    if command == "link":
        need(not prior, "R14_EVIDENCE_ALREADY_LINKED_NO_REPLAY")
        state = PHASE_EVIDENCE
    else:
        need(len(prior) == 1
             and prior[0]["audit_run_id"] == audit_run_id
             and prior[0]["qa_run_id"] == qa_run_id
             and prior[0]["source_sha"] == facts["source_sha"]
             and prior[0]["qa_artifact_sha256"] == facts["qa_artifact_sha256"]
             and prior[0]["audit_artifact_sha256"] == facts["audit_artifact_sha256"],
             "R14_REVIEW_REQUIRES_IDENTICAL_VERIFIED_HANDOFF")
        state = PHASE_ACK
    entry = {
        "schema": SCHEMA, "seq": len(prior) + 1,
        "command": command, "state": state, **facts,
        "owner_acknowledged": command == "acknowledge",
        "independent_human_qa_complete": False,
        "worker_execution_authorized": False,
        "merge_authorized": False,
        "deployment_authorized": False,
    }
    body = MARK + "\n~~~json\n" + json.dumps(
        entry, sort_keys=True, separators=(",", ":")) + "\n~~~"
    need(len(body) <= 9000, "R14_COMMENT_TOO_LARGE")
    # Per-Issue workflow concurrency and a final read guard against a
    # changed history before the sole, narrowly permitted GitHub API write.
    again = history(get, token, number, facts["issue_sha256"])
    need(again == prior, "R14_JOURNAL_CHANGED_BEFORE_WRITE")
    answer = post(f"/repos/{r12.HOME}/issues/{number}/comments", token,
                  {"body": body})
    need(type(answer) is dict and type(answer.get("id")) is int
         and answer["id"] > 0, "R14_COMMENT_WRITE_NOT_CONFIRMED")
    return {
        **entry,
        "comment_id": answer["id"],
        "mission_url": f"https://github.com/{r12.HOME}/issues/{number}",
        "audit_url": f"https://github.com/{r12.HOME}/actions/runs/{audit_run_id}",
        "qa_url": f"https://github.com/{r12.HOME}/actions/runs/{qa_run_id}",
    }


def summary(data):
    if data.get("schema") != SCHEMA:
        return ("## Fleet R14: evidence HELD\n\n"
                "No QA approval, worker write, merge or deployment.\n")
    status = data.get("state", "")
    return "\n".join([
        "## Fleet R14: mission evidence / human gate",
        "",
        "- Mission: " + data["mission_url"],
        "- Audit: " + data["audit_url"],
        "- Separate automated QA: " + data["qa_url"],
        "- State: **" + status + "**",
        "- Exact source: " + data["source_sha"],
        "- GitHub audit ZIP SHA-256: " + data["audit_artifact_sha256"],
        "- GitHub QA ZIP SHA-256: " + data["qa_artifact_sha256"],
        "- Default branch protected: " +
          str(data["default_branch_protected"]).lower(),
        "- Code writes: **BLOCKED** (R14 never grants write authority)",
        "- Owner evidence acknowledgement: " +
          str(data["owner_acknowledged"]).lower(),
        "- Independent human QA approval: **NOT PERFORMED**",
        "- Merge or deployment authorization: **NONE**",
        "",
    ])


def parse_cli_id(raw):
    """Accept pasted outer ASCII whitespace, reject all internal junk.

    GitHub Actions workflow_dispatch text inputs often include an accidental
    leading tab or trailing newline. Tolerating only boundary whitespace
    preserves the strict positive-integer trust boundary.
    """
    need(type(raw) is str and
         re.fullmatch(r"[ \t\r\n]*[1-9][0-9]{0,15}[ \t\r\n]*", raw)
         is not None, "R14_NUMERIC_INPUT_INVALID")
    return int(raw.strip(" \t\r\n"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("--issue-number", required=True)
    p.add_argument("--audit-run-id", required=True)
    p.add_argument("--qa-run-id", required=True)
    p.add_argument("--confirmation", required=True)
    p.add_argument("--out", type=Path, default=Path("fleet-r14"))
    args = p.parse_args(argv)
    try:
        # Normalize only boundary ASCII whitespace inside the guarded
        # receipt-producing CLI; invalid inputs still emit a HELD artifact.
        number = parse_cli_id(args.issue_number)
        audit_id = parse_cli_id(args.audit_run_id)
        qa_id = parse_cli_id(args.qa_run_id)
        value = transition(number, args.command, audit_id,
                           qa_id, confirmation=args.confirmation,
                           actor=os.getenv("GITHUB_ACTOR"),
                           token=os.getenv("GITHUB_TOKEN"))
        status = 0
    except (r12.MissionHeld, storage.CloudReviewHeld, ValueError, OSError,
            TypeError) as exc:
        value = {
            "schema": SCHEMA, "state": "HELD_R14_MISSION_EVIDENCE",
            "reason": str(exc) if isinstance(
                exc, (r12.MissionHeld, storage.CloudReviewHeld)) else
                "INPUT_OR_RUNTIME_UNAVAILABLE",
            "independent_human_qa_complete": False,
            "merge_authorized": False, "deployment_authorized": False,
        }
        status = 3
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "receipt.json").write_text(
        json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    (args.out / "summary.md").write_text(
        summary(value), encoding="utf-8")
    print(json.dumps({"state": value["state"], "merge_authorized": False,
                      "deployment_authorized": False}))
    return status


if __name__ == "__main__":
    sys.exit(main())
