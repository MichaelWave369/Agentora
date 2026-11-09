"""Fleet R13: independently recheck one real GitHub-hosted read-only audit.

This is a separate GitHub Actions workflow and separate verifier implementation
from the deterministic audit worker. The verifier downloads the original
GitHub artifact ZIP, checks GitHub-owned SHA-256, validates the mission's live
Issue journal and target source identity, then rechecks actual public metadata.

An automated evidence recheck is NOT independent human QA approval.
No source writes, Issue writes, worker dispatch, merges, or deployment.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from zipfile import ZipFile, BadZipFile

import fleet_r11_cloud_evidence as blob
import fleet_r12_github_missions as mission

SCHEMA = "agentora.fleet.r13.independent-evidence-qa.v1"
AUDIT_SCHEMA = "agentora.fleet.r13.hosted-readonly-audit.v1"
WORKFLOW = ".github/workflows/fleet-r13-readonly-audit.yml"
HOME = mission.HOME
MAX_ZIP = 1_000_000
MAX_JSON = 20_000


def need(ok, why):
    if not ok:
        raise mission.MissionHeld(why)


def read_receipt(data):
    need(type(data) is bytes and 0 < len(data) <= MAX_ZIP,
         "QA_ARTIFACT_ZIP_OUT_OF_BOUNDS")
    try:
        with ZipFile(BytesIO(data)) as z:
            files = {}
            for m in z.infolist():
                if m.is_dir():
                    need(m.filename == "fleet-r13/", "QA_UNEXPECTED_ZIP_DIR")
                    continue
                path = m.filename
                if path.startswith("fleet-r13/"):
                    path = path[len("fleet-r13/"):]
                need(path in ("receipt.json", "summary.md") and
                     path not in files and (m.flag_bits & 1) == 0 and
                     m.file_size <= MAX_JSON,
                     "QA_UNEXPECTED_OR_UNSAFE_ZIP_ENTRY")
                file_type = (m.external_attr >> 16) & 0o170000
                need(file_type in (0, 0o100000), "QA_ZIP_NONREGULAR_ENTRY")
                contents = z.read(m)
                need(len(contents) <= MAX_JSON, "QA_ZIP_ENTRY_TOO_LARGE")
                files[path] = contents
            need(set(files) == {"receipt.json", "summary.md"},
                 "QA_REQUIRED_RECEIPT_FILES_MISSING")
        receipt = json.loads(files["receipt.json"].decode("utf-8"))
    except (BadZipFile, UnicodeError, ValueError, RuntimeError, OSError):
        raise mission.MissionHeld("QA_ARTIFACT_UNREADABLE") from None
    need(type(receipt) is dict, "QA_RECEIPT_NOT_OBJECT")
    return receipt


def review(run_id, *, token, get=None, download=None, now=None):
    mission.positive(run_id, "AUDIT_RUN")
    get = get or (lambda path, tok: mission.github("GET", path, tok))
    download = download or blob.download_artifact
    moment = now or datetime.now(timezone.utc)
    need(type(moment) is datetime and moment.tzinfo is not None,
         "QA_CLOCK_INVALID")
    moment = moment.astimezone(timezone.utc)
    base = "/repos/" + HOME + "/actions/runs/" + str(run_id)
    run = get(base, token)
    need(type(run) is dict and run.get("id") == run_id
         and run.get("path") == WORKFLOW
         and run.get("event") == "workflow_dispatch"
         and run.get("status") == "completed"
         and run.get("conclusion") == "success"
         and run.get("run_attempt") == 1
         and run.get("head_branch") == "main"
         and (run.get("repository") or {}).get("full_name") == HOME
         and (run.get("actor") or {}).get("login") == mission.OWNER,
         "QA_AUDIT_RUN_IDENTITY_NOT_TRUSTED")
    raw_time = run.get("created_at")
    need(type(raw_time) is str, "QA_RUN_TIME_INVALID")
    try:
        created = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
    except ValueError:
        raise mission.MissionHeld("QA_RUN_TIME_INVALID") from None
    need(created.tzinfo is not None and
         -timedelta(minutes=5) <= moment - created <= timedelta(days=7),
         "QA_RUN_TOO_OLD_OR_FROM_FUTURE")
    catalog = get(base + "/artifacts?per_page=100", token)
    need(type(catalog) is dict and
         type(catalog.get("total_count")) is int and
         0 < catalog["total_count"] <= 100 and
         type(catalog.get("artifacts")) is list and
         len(catalog["artifacts"]) == catalog["total_count"],
         "QA_ARTIFACT_CATALOG_NOT_COMPLETE")
    found = [a for a in catalog["artifacts"] if type(a) is dict and
             a.get("name") == "fleet-r13-audit-" + str(run_id)]
    need(len(found) == 1, "QA_ARTIFACT_MISSING_OR_AMBIGUOUS")
    art = found[0]
    need(type(art.get("id")) is int and art["id"] > 0
         and type(art.get("size_in_bytes")) is int
         and 0 < art["size_in_bytes"] <= MAX_ZIP
         and art.get("expired") is False
         and type(art.get("digest")) is str
         and art["digest"].startswith("sha256:")
         and mission.HEX64.fullmatch(art["digest"][7:]) is not None,
         "QA_ARTIFACT_METADATA_INVALID")
    if art.get("workflow_run") is not None:
        need((art["workflow_run"] or {}).get("id") == run_id,
             "QA_ARTIFACT_WRONG_ORIGIN")
    archive = download(art["id"], token)
    actual = hashlib.sha256(archive).hexdigest()
    need(actual == art["digest"][7:], "QA_GITHUB_ARTIFACT_DIGEST_MISMATCH")
    receipt = read_receipt(archive)
    number = receipt.get("mission_issue")
    mission.positive(number, "MISSION_ISSUE")
    issue = get("/repos/" + HOME + "/issues/" + str(number), token)
    form, issue_digest = mission.issue_identity(issue, number)
    state, last, seq = mission.journal(get, token, number, issue_digest)
    need(state == "ROLE_PROPOSED" and type(last) is dict
         and last.get("worker_role") == "builder_a"
         and form["Mission kind"] == "Read-only audit",
         "QA_MISSION_NOT_IN_READONLY_REVIEW_LANE")
    target = form["Target repository"]
    repo_id, branch, head = mission.source(get, token, target)
    repo = get("/repos/" + target, token)
    need(type(repo) is dict and repo.get("id") == repo_id
         and repo.get("full_name") == target
         and repo.get("private") is False
         and repo.get("archived") is False
         and repo.get("disabled") is False,
         "QA_TARGET_NO_LONGER_PUBLIC_ACTIVE")
    br = get("/repos/" + target + "/branches/" + branch, token)
    need(type(br) is dict and
         (br.get("commit") or {}).get("sha") == head and
         type(br.get("protected")) is bool,
         "QA_BRANCH_METADATA_UNAVAILABLE")
    commit = get("/repos/" + target + "/commits/" + head, token)
    need(type(commit) is dict and commit.get("sha") == head
         and type(commit.get("parents")) is list,
         "QA_HEAD_COMMIT_INVALID")
    sig = ((commit.get("commit") or {}).get("verification") or {}).get("verified")
    need(sig is None or type(sig) is bool, "QA_SIGNATURE_VALUE_INVALID")
    expected_obs = {
        "public_repository": True, "not_archived": True,
        "not_disabled": True, "default_branch_protected": br["protected"],
        "head_commit_found": True, "head_commit_signature_verified": sig,
    }
    need(receipt.get("schema") == AUDIT_SCHEMA
         and receipt.get("state") == "AUDIT_RECEIPT_CAPTURED_PENDING_SEPARATE_QA"
         and receipt.get("mission_issue") == number
         and receipt.get("mission_issue_sha256") == issue_digest
         and receipt.get("mission_journal_seq") == seq
         and receipt.get("mission_kind") == "Read-only audit"
         and receipt.get("proposed_worker") == "builder_a"
         and receipt.get("target_repository") == target
         and receipt.get("target_repository_id") == repo_id
         and receipt.get("default_branch") == branch
         and receipt.get("exact_source_sha") == head
         and receipt.get("observations") == expected_obs
         and receipt.get("audit_scope") == "PUBLIC_GITHUB_METADATA_ONLY"
         and receipt.get("target_source_executed") is False
         and receipt.get("worker_is_model_agent") is False
         and receipt.get("independent_qa_complete") is False
         and receipt.get("verified_complete") is False
         and receipt.get("merge_authorized") is False
         and receipt.get("dispatch_authorized") is False
         and receipt.get("deployment_authorized") is False,
         "QA_AUDIT_RECEIPT_NOT_CORROBORATED")
    # Detect concurrent source drift during independent review.
    need(mission.source(get, token, target) == (repo_id, branch, head),
         "QA_SOURCE_MOVED_DURING_REVIEW")
    return {
        "schema": SCHEMA,
        "state": "AUDIT_METADATA_CORROBORATED_PENDING_HUMAN_QA",
        "audit_run_id": run_id,
        "audit_run_url": "https://github.com/" + HOME +
                         "/actions/runs/" + str(run_id),
        "mission_issue": number,
        "target_repository": target,
        "source_sha": head,
        "artifact_sha256": actual,
        "automated_independent_evidence_recheck": True,
        "independent_human_qa_complete": False,
        "independent_qa_complete": False,
        "verified_complete": False,
        "merge_authorized": False,
        "deployment_authorized": False,
    }


def summary(data):
    if data.get("state") != "AUDIT_METADATA_CORROBORATED_PENDING_HUMAN_QA":
        return ("## Fleet R13: QA evidence HELD\n\n"
                "No verified completion, independent human QA or merge.\n")
    return "\n".join([
        "## Fleet R13: separate automated evidence QA",
        "",
        "- Audit run: " + data["audit_run_url"],
        "- Mission Issue #" + str(data["mission_issue"]),
        "- Exact source SHA: " + data["source_sha"],
        "- Verified GitHub artifact ZIP SHA-256: " + data["artifact_sha256"],
        "- Rechecked live GitHub repository metadata: matched",
        "- Independent human QA: NOT PERFORMED",
        "- Merge and deployment: NOT AUTHORIZED",
        "",
    ])


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--audit-run-id", required=True, type=int)
    p.add_argument("--out", type=Path, default=Path("fleet-r13-qa"))
    args = p.parse_args(argv)
    try:
        result = review(args.audit_run_id, token=os.environ.get("GITHUB_TOKEN"))
        status = 0
    except (mission.MissionHeld, blob.CloudReviewHeld, OSError,
            ValueError, TypeError) as exc:
        result = {"schema": SCHEMA, "state": "HELD_INDEPENDENT_EVIDENCE_QA",
                  "reason": str(exc) if isinstance(
                      exc, (mission.MissionHeld, blob.CloudReviewHeld)) else
                      "INPUT_OR_RUNTIME_UNAVAILABLE",
                  "independent_qa_complete": False, "merge_authorized": False,
                  "verified_complete": False}
        status = 3
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "receipt.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.out / "summary.md").write_text(summary(result), encoding="utf-8")
    print(json.dumps({"state": result["state"], "merge_authorized": False,
                      "verified_complete": False}))
    return status


if __name__ == "__main__":
    sys.exit(main())
