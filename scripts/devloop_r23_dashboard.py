"""Agentora DevLoop R2.3: bounded, read-only evidence dashboard.

Authoritative sources: live GitHub PR records, exact-head CI/branch rules,
and trusted-main GitHub Actions receipts (within artifact retention).
No repository mutations, label changes, merge calls, or worker dispatch.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from devloop_r22_review_queue import (
    REPO, QueueHeld, github_get, md_escape, snapshot as queue_snapshot,
)

WORKFLOWS = {
    "merge": ("devloop-automerge.yml", "devloop-merge-decision-", "merge-decision.json", 12),
    "handoff": ("devloop-r2-handoff.yml", "devloop-next-rung-", "next-rung.json", 12),
    "queue": ("devloop-r22-review-queue.yml", "devloop-r22-review-queue-", "review-queue.json", 6),
}
SCHEMAS = {
    "merge": "agentora.devloop.merge-decision.v2",
    "handoff": "agentora.devloop.next-rung-receipt.v1",
    "queue": "agentora.devloop.review-queue.v2.2",
}
EXPECTED_DECISIONS = {
    "EXACT_HEAD_REQUIRED_CI_GREEN_MERGED",
    "R21_SOLO_EXACT_HEAD_CI_GREEN_MERGED",
    "R2_CODE_EXACT_HEAD_REVIEWED_CI_GREEN_MERGED",
}
HEX40 = re.compile(r"^[0-9a-f]{40}$")
MAX_ZIP_BYTES = 96_000
MAX_JSON_BYTES = 32_000
MAX_ARTIFACT_COUNT = 100


class DashboardHeld(Exception):
    pass


class SafeRedirect(HTTPRedirectHandler):
    """Only follow HTTPS GitHub artifact redirects, without forwarding tokens."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        parsed = urlparse(newurl)
        host = (parsed.hostname or "").lower()
        # GitHub-generated signed download URLs use their own short-lived token.
        if (parsed.scheme != "https" or not (
                host.endswith(".githubusercontent.com") or
                host.endswith(".blob.core.windows.net") or
                host == "github.com" or host == "api.github.com")):
            raise DashboardHeld("R23_UNEXPECTED_ARTIFACT_REDIRECT")
        next_request = super().redirect_request(req, fp, code, msg, headers, newurl)
        if next_request is None:
            raise DashboardHeld("R23_ARTIFACT_REDIRECT_DENIED")
        next_request.remove_header("Authorization")
        next_request.remove_header("authorization")
        return next_request


def fetch_archive(token: str, artifact_id: int) -> bytes:
    if type(artifact_id) is not int or artifact_id < 1 or not token:
        raise DashboardHeld("R23_ARTIFACT_REFERENCE_INVALID")
    endpoint = f"https://api.github.com/repos/{REPO}/actions/artifacts/{artifact_id}/zip"
    request = Request(endpoint, method="GET", headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "agentora-devloop-r23-readonly",
    })
    try:
        with build_opener(SafeRedirect()).open(request, timeout=20) as response:
            data = response.read(MAX_ZIP_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError):
        raise DashboardHeld("R23_ARTIFACT_DOWNLOAD_UNAVAILABLE") from None
    if len(data) > MAX_ZIP_BYTES:
        raise DashboardHeld("R23_ARCHIVE_TOO_LARGE")
    return data


def extract_json(archive: bytes, basename: str):
    if not isinstance(archive, bytes) or len(archive) > MAX_ZIP_BYTES:
        raise DashboardHeld("R23_ARCHIVE_TOO_LARGE")
    try:
        with zipfile.ZipFile(BytesIO(archive)) as z:
            members = z.infolist()
            if not 1 <= len(members) <= 5:
                raise DashboardHeld("R23_ARCHIVE_FILE_COUNT_INVALID")
            candidates = []
            for member in members:
                path = member.filename
                if (path.startswith("/") or "\\" in path or
                        ".." in path.split("/") or member.is_dir()):
                    raise DashboardHeld("R23_ARCHIVE_PATH_INVALID")
                if path.split("/")[-1] == basename:
                    candidates.append(member)
            if len(candidates) != 1 or candidates[0].file_size > MAX_JSON_BYTES:
                raise DashboardHeld("R23_RECEIPT_NOT_UNIQUE_OR_TOO_LARGE")
            with z.open(candidates[0]) as stream:
                raw = stream.read(MAX_JSON_BYTES + 1)
    except (zipfile.BadZipFile, RuntimeError, OSError):
        raise DashboardHeld("R23_ARCHIVE_INVALID") from None
    if len(raw) > MAX_JSON_BYTES:
        raise DashboardHeld("R23_RECEIPT_TOO_LARGE")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError):
        raise DashboardHeld("R23_RECEIPT_INVALID_JSON") from None
    if not isinstance(payload, dict):
        raise DashboardHeld("R23_RECEIPT_INVALID_STRUCTURE")
    return payload


def read_recent_runs(get, token, workflow: str, limit: int):
    if workflow not in {t[0] for t in WORKFLOWS.values()} or not 1 <= limit <= 20:
        raise DashboardHeld("R23_INVALID_WORKFLOW_SCOPE")
    data = get(token, f"/repos/{REPO}/actions/workflows/{workflow}/runs?per_page={limit}")
    if not isinstance(data, dict) or not isinstance(data.get("workflow_runs"), list):
        raise DashboardHeld("R23_WORKFLOW_RUNS_UNAVAILABLE")
    runs = data["workflow_runs"]
    if len(runs) > limit or any(not isinstance(x, dict) for x in runs):
        raise DashboardHeld("R23_WORKFLOW_RUN_LIST_INVALID")
    return runs


def find_receipt_artifact(get, token, run_id: int, kind: str):
    prefix = WORKFLOWS[kind][1]
    if type(run_id) is not int or run_id < 1:
        raise DashboardHeld("R23_RUN_ID_INVALID")
    response = get(token, f"/repos/{REPO}/actions/runs/{run_id}/artifacts?per_page=100")
    if (not isinstance(response, dict) or
            type(response.get("total_count")) is not int or
            response["total_count"] >= MAX_ARTIFACT_COUNT or
            not isinstance(response.get("artifacts"), list) or
            len(response["artifacts"]) != response["total_count"]):
        raise DashboardHeld("R23_ARTIFACT_LIST_INCOMPLETE")
    artifacts = [
        item for item in response["artifacts"]
        if isinstance(item, dict) and
        isinstance(item.get("name"), str) and
        item["name"].startswith(prefix) and
        item["name"].endswith("-" + str(run_id))
    ]
    if not artifacts:
        raise DashboardHeld("R23_RECEIPT_MISSING_OR_EXPIRED")
    if len(artifacts) != 1 or artifacts[0].get("expired") is True:
        raise DashboardHeld("R23_RECEIPT_AMBIGUOUS_OR_EXPIRED")
    a = artifacts[0]
    if (type(a.get("id")) is not int or type(a.get("size_in_bytes")) is not int or
            not 0 < a["size_in_bytes"] <= MAX_ZIP_BYTES):
        raise DashboardHeld("R23_RECEIPT_ARCHIVE_METADATA_INVALID")
    return a["id"]


def valid_sha(value):
    return isinstance(value, str) and bool(HEX40.fullmatch(value))


def verify_real_merge(get, token, number, expected_sha, expected_merge_sha=None):
    """Check GitHub's actual PR merge record; success from a log alone is not proof."""
    if type(number) is not int or number < 1 or not valid_sha(expected_sha):
        return "INVALID_PR_OR_HEAD"
    pr = get(token, f"/repos/{REPO}/pulls/{number}")
    if not isinstance(pr, dict):
        return "PR_RECORD_UNAVAILABLE"
    if (pr.get("number") != number or
            (pr.get("head") or {}).get("sha") != expected_sha or
            (pr.get("base") or {}).get("ref") != "main"):
        return "PR_IDENTITY_MISMATCH"
    if pr.get("merged") is not True:
        return "PR_NOT_MERGED"
    if expected_merge_sha is not None and pr.get("merge_commit_sha") != expected_merge_sha:
        return "MERGE_SHA_MISMATCH"
    return ("BOT_MERGE_VERIFIED" if (pr.get("merged_by") or {}).get("login") ==
            "github-actions[bot]" else "MERGED_BY_OTHER_ACTOR")


def interpret_receipt(get, token, kind, run, payload):
    if payload.get("schema") != SCHEMAS[kind]:
        raise DashboardHeld("R23_RECEIPT_SCHEMA_MISMATCH")
    if kind == "merge":
        num = payload.get("pr_number")
        sha = payload.get("head_sha")
        if type(num) is not int or num < 1 or not valid_sha(sha):
            raise DashboardHeld("R23_MERGE_RECEIPT_IDENTITY_INVALID")
        outcome = payload.get("decision")
        disposition = payload.get("disposition")
        if not isinstance(outcome, str) or not isinstance(disposition, str):
            raise DashboardHeld("R23_MERGE_DECISION_INVALID")
        if disposition == "SUCCESS" and outcome in EXPECTED_DECISIONS:
            verified = verify_real_merge(get, token, num, sha)
            verdict = "VERIFIED_BOT_MERGE" if verified == "BOT_MERGE_VERIFIED" else verified
        elif disposition == "HELD":
            verdict = "HELD_DECISION_ONLY"
        else:
            verdict = "UNRECOGNIZED_MERGE_DECISION"
        return {
            "pr_number": num, "head_sha": sha, "lane": payload.get("lane"),
            "decision": outcome[:128], "receipt_disposition": disposition,
            "verification": verdict,
        }
    if kind == "handoff":
        num = payload.get("source_pr")
        sha = payload.get("source_head_sha")
        merge_sha = payload.get("merge_commit_sha")
        if type(num) is not int or num < 1 or not valid_sha(sha) or not valid_sha(merge_sha):
            raise DashboardHeld("R23_HANDOFF_IDENTITY_INVALID")
        if payload.get("executable") is not False:
            raise DashboardHeld("R23_HANDOFF_EXECUTABLE_CLAIM_INVALID")
        outcome = payload.get("disposition")
        if outcome not in ("NO_PREAPPROVED_NEXT_RUNG", "READY_FOR_OPERATOR_DISPATCH", "HELD"):
            raise DashboardHeld("R23_HANDOFF_DECISION_INVALID")
        verified = verify_real_merge(get, token, num, sha, merge_sha)
        return {
            "pr_number": num, "head_sha": sha,
            "merge_sha": merge_sha, "decision": outcome,
            "task_id": (payload.get("task_id") or "") if outcome == "READY_FOR_OPERATOR_DISPATCH" else "",
            "verification": verified if verified in ("BOT_MERGE_VERIFIED", "MERGED_BY_OTHER_ACTOR")
                            else "SOURCE_" + verified,
            "executable": False,
        }
    if payload.get("mode") != "READ_ONLY_ADVISORY_NOT_MERGE_AUTHORITY":
        raise DashboardHeld("R23_QUEUE_NOT_ADVISORY")
    if payload.get("can_merge") is not False or not isinstance(payload.get("rows"), list):
        raise DashboardHeld("R23_QUEUE_CLAIMS_AUTHORITY")
    return {
        "open_pr_count": payload.get("open_pr_count"),
        "decision": "READ_ONLY_SNAPSHOT",
        "verification": "RECEIPT_READ_ONLY",
    }


def history(get, fetch, token, kind):
    workflow, _, basename, count = WORKFLOWS[kind]
    output = []
    for run in read_recent_runs(get, token, workflow, count):
        run_id = run.get("id")
        if type(run_id) is not int or run_id < 1:
            raise DashboardHeld("R23_RUN_ID_INVALID")
        entry = {
            "run_id": run_id,
            "url": f"https://github.com/{REPO}/actions/runs/{run_id}",
            "created_at": run.get("created_at"),
            "workflow_conclusion": run.get("conclusion"),
            "verification": "NOT_ASSESSED",
        }
        if run.get("status") != "completed":
            entry["verification"] = "RUN_INCOMPLETE"
        else:
            try:
                artifact_id = find_receipt_artifact(get, token, run_id, kind)
                payload = extract_json(fetch(token, artifact_id), basename)
                entry["artifact_url"] = entry["url"] + "/artifacts/" + str(artifact_id)
                entry.update(interpret_receipt(get, token, kind, run, payload))
            except (DashboardHeld, QueueHeld) as exc:
                entry["verification"] = "EVIDENCE_HELD"
                entry["reason"] = str(exc)
        output.append(entry)
    return output


def assemble(get, fetch, token):
    # Read current queue once, then sample recent receipts from three trusted workflows.
    result = {
        "schema": "agentora.devloop.review-dashboard.v2.3",
        "repository": REPO,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "READ_ONLY_EVIDENCE_NOT_AUTHORIZATION",
        "can_merge": False, "can_dispatch": False,
        "coverage": "RECENT_SAMPLED_WORKFLOW_RUNS_WITH_RETAINED_ARTIFACTS_ONLY",
        "current_queue": queue_snapshot(get, token),
        "history": {},
    }
    for kind in WORKFLOWS:
        result["history"][kind] = history(get, fetch, token, kind)
    merges = result["history"]["merge"]
    handoffs = result["history"]["handoff"]
    result["metrics"] = {
        "open_prs": result["current_queue"]["open_pr_count"],
        "verified_bot_merges": sum(x["verification"] == "VERIFIED_BOT_MERGE" for x in merges),
        "held_merge_decisions": sum(x["verification"] == "HELD_DECISION_ONLY" for x in merges),
        "handoffs_ready_for_operator": sum(
            x.get("decision") == "READY_FOR_OPERATOR_DISPATCH"
            and x.get("verification") in ("BOT_MERGE_VERIFIED", "MERGED_BY_OTHER_ACTOR")
            for x in handoffs
        ),
        "no_preapproved_next_rung": sum(
            x.get("decision") == "NO_PREAPPROVED_NEXT_RUNG" for x in handoffs),
        "evidence_unverified": sum(
            x.get("verification") in ("EVIDENCE_HELD", "RUN_INCOMPLETE")
            for group in result["history"].values() for x in group
        ),
    }
    return result


def markdown_report(data):
    m = data.get("metrics") or {}
    lines = [
        "# Φ Agentora · Solo Sovereign Review Dashboard",
        "",
        "**Read-only evidence, never merge or dispatch authority.**",
        "",
        f"Captured UTC: {md_escape(data.get('captured_utc', 'unknown'))}",
        "Coverage: recent bounded workflow runs whose artifacts are still retained; not a lifetime ledger.",
        "",
    ]
    if data.get("error"):
        lines += [f"**DASHBOARD HELD:** {md_escape(data['error'])}", ""]
        return "\n".join(lines)
    lines += [
        "## Current state",
        f"- Open PRs: **{m.get('open_prs', 'UNVERIFIED')}**",
        f"- Verified automated merges in sampled receipts: **{m.get('verified_bot_merges', 'UNVERIFIED')}**",
        f"- Held merge decisions in sampled receipts: **{m.get('held_merge_decisions', 'UNVERIFIED')}**",
        f"- Read-only handoffs ready for operator in sample: **{m.get('handoffs_ready_for_operator', 'UNVERIFIED')}**",
        f"- Handoffs with no preapproved next rung in sample: **{m.get('no_preapproved_next_rung', 'UNVERIFIED')}**",
        f"- Missing/incomplete evidence items: **{m.get('evidence_unverified', 'UNVERIFIED')}**",
        "",
    ]
    current = data.get("current_queue") or {}
    lines += ["## Open PR review queue"]
    rows = current.get("rows") or []
    if not rows:
        lines.append("No open PRs in this captured snapshot.")
    else:
        lines += ["| PR | Lane | Required CI | Next step |",
                  "|---|---|---|---|"]
        for row in rows:
            num = row.get("number")
            if type(num) is not int:
                continue
            lines.append(
                f"| [#{num}](https://github.com/{REPO}/pull/{num}) | "
                f"{md_escape(row.get('lane'))} | "
                f"{md_escape((row.get('ci') or {}).get('state'))} | "
                f"{md_escape(row.get('next_action'))} |"
            )
    lines.append("")
    for kind, heading in [
        ("merge", "Merge decisions and GitHub attribution"),
        ("handoff", "Post-merge next-rung handoffs"),
        ("queue", "Review Queue snapshots"),
    ]:
        lines += [f"## {heading}", "| Run | PR | Receipt decision | Verification |",
                  "|---|---|---|---|"]
        for item in (data.get("history") or {}).get(kind, []):
            run_id = item["run_id"]
            number = item.get("pr_number")
            pr_cell = f"[#{number}](https://github.com/{REPO}/pull/{number})" if number else "—"
            lines.append(
                f"| [#{run_id}]({item['url']}) | {pr_cell} | "
                f"{md_escape(item.get('decision', item.get('reason', 'UNVERIFIED')))} | "
                f"{md_escape(item['verification'])} |"
            )
        if not (data.get("history") or {}).get(kind):
            lines.append("| None sampled | — | — | — |")
        lines.append("")
    lines += [
        "### Boundaries",
        "The dashboard never applies labels, approves PRs, merges changes, dispatches agents "
        "or treats a green workflow as proof of an actual merge. "
        "Verified automated merges require the matching live GitHub PR record and bot attribution.",
        "Artifact retention, rate limits and bounded recent-run sampling mean absence of a receipt "
        "does not prove an event never occurred.",
        "",
    ]
    return "\n".join(lines)


def main():
    data = {
        "schema": "agentora.devloop.review-dashboard.v2.3",
        "mode": "READ_ONLY_EVIDENCE_NOT_AUTHORIZATION",
        "can_merge": False, "can_dispatch": False,
        "captured_utc": datetime.now(timezone.utc).isoformat(),
    }
    rc = 0
    try:
        data = assemble(github_get, fetch_archive, os.environ["GH_TOKEN"])
        print("R23_DASHBOARD_READ_ONLY_SUCCESS sampled=" +
              str(sum(len(x) for x in data["history"].values())))
    except (DashboardHeld, QueueHeld, OSError, ValueError, KeyError, TypeError) as exc:
        data["error"] = str(exc) if isinstance(exc, (DashboardHeld, QueueHeld)) else "R23_INVALID_RUNTIME"
        print("::error::R23_DASHBOARD_HELD " + data["error"], file=sys.stderr)
        rc = 1
    finally:
        output = Path("devloop-artifacts")
        output.mkdir(exist_ok=True)
        (output / "review-dashboard.json").write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as stream:
                stream.write(markdown_report(data))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
