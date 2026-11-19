"""Connect the existing R9 queue to Agentora's owner-reviewed R1 docs workflow.

The local ledger takes the one-shot submission fence. GitHub controls owner
review, execution, publishing and merging. This adapter never touches refs,
labels, approvals or pull requests, and has no publisher credential.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener
import zipfile

import autonomous_turn as turn
import autonomous_turn_contract as contract
import autonomous_turn_github as github
import fleet_r04_leases as leases
import fleet_r11_cloud_evidence as artifacts
import fleet_r9_mission_control as r9
from fleet_stewards_r2 import output_json
from app.integrations.phireponerve_client import collect_public_observations, RepoNerveUnavailable

REPO_URL = "https://github.com/" + contract.REPO
RUNS = github.BASE + "/actions/runs"
DISPATCH = github.BASE + "/actions/workflows/autonomous-turn-r1.yml/dispatches"
SCHEMA = "agentora.fleet.r9-r1-turns.v1"
CONFIRM = "QUEUE_AGENTORA_R1_DOCS"
WORKER = "autonomous-r1"
PUBLISHER_ID = 352553105
MAX_ARCHIVE = 512_000
JOB_NAMES = {"plan", "owner-authorization", "attempt-0 / worker",
             "attempt-0 / publish", "attempt-0 / observe", "merge-gate"}
need = contract.need


def held_intake(task):
    return {
        "schema": leases.INTAKE_SCHEMA, "state": "HELD_FOR_OPERATOR_REVIEW",
        "owner": leases.OWNER, "repository": contract.REPO, "repository_id": contract.REPO_ID,
        "source_sha": task["source_sha"], "request_sha256": contract.task_digest(task),
        "verified_complete": False, "operator_approved": False,
        "dispatch_authorized": False, "merge_authorized": False,
        "head_revalidated_by_agentora": False, "digest_is_authentication": False,
        "independent_checks_run": 0,
        "checks": [{"check_id": "docs-contract", "verification_state": "NOT_RUN",
                    "evidence_receipt": None}],
    }


def prepare(source, task_id, path, before, after, objective, acceptance, now=None):
    now = r9._now(now)
    need(contract.safe_path(path) and github.devloop.is_doc(path), "DOCS_PATH_REQUIRED")
    git = ["git", "-C", str(source)]
    sha = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    need(not subprocess.check_output(
        [*git, "status", "--porcelain", "--untracked-files=all"], text=True), "CHECKOUT_DIRTY")
    original = turn.originals_from_checkout({"allowed_paths": [path]}, source)[path]
    # Preserve the existing R1 wire format and exact-edit contract.
    task = {"schema": contract.SCHEMA, "task_id": task_id, "repository": contract.REPO,
            "repository_id": contract.REPO_ID, "target_branch": "main", "source_sha": sha,
            "created_utc": now.isoformat(), "expires_utc": (now + timedelta(hours=4)).isoformat(),
            "acceptance": [acceptance], "allowed_paths": [path], "max_files": 1,
            "max_changed_lines": 20, "max_patch_bytes": 4000, "tests": ["docs-contract"],
            "max_repairs": 0, "merge_policy": "docs", "repairs": [],
            "edits": [{"path": path, "before_sha256": contract.digest(original.encode()),
                       "old": before, "new": after}],
            "human_scope": objective, "phimada_request_sha256": None}
    contract.validate(task, now=now)
    contract.proposal(task, {path: original}, 0)
    return task


def github_request(token, path, payload=None):
    """The sole write endpoint is the fixed R1 dispatch, with the owner token."""
    need(bool(token) and path in {"/user", DISPATCH} and
         (payload is not None) == (path == DISPATCH), "DISPATCH_TOKEN_OR_PATH_INVALID")
    req = Request("https://api.github.com" + path,
                  data=contract.canonical(payload) if payload is not None else None,
                  headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                           "Content-Type": "application/json", "X-GitHub-Api-Version": "2026-03-10",
                           "User-Agent": "Agentora-R9-R1"})
    try:
        with build_opener(github.NoRedirect()).open(req, timeout=20) as response:
            if response.status == 204:
                return {}
            need(response.status == 200, "GITHUB_WRITE_RESPONSE_UNEXPECTED")
            return contract.parse(response.read(contract.MAX_JSON + 1))
    except HTTPError as exc:
        raise contract.Held(f"GITHUB_HTTP_{exc.code}") from None
    except (URLError, OSError, ValueError):
        raise contract.Held("GITHUB_DISPATCH_RESPONSE_UNAVAILABLE") from None


def positive(value):
    return type(value) is int and 0 < value <= 9_007_199_254_740_991


def job_records(api, run_id, task):
    result = api(f"{RUNS}/{run_id}/jobs?per_page=20")
    rows = result.get("jobs")
    need(isinstance(rows, list) and len(rows) == result.get("total_count") < 20,
         "R1_JOBS_INCOMPLETE")
    jobs = {}
    for row in rows:
        name = row.get("name")
        if name not in JOB_NAMES:
            continue
        need(name not in jobs and row.get("run_id") == run_id and
             row.get("run_attempt") == 1 and row.get("head_sha") == task["source_sha"] and
             positive(row.get("id")), "R1_JOB_IDENTITY")
        jobs[name] = row
    return jobs


def job_passed(jobs, name):
    row = jobs.get(name, {})
    return row.get("status") == "completed" and row.get("conclusion") == "success"


def frozen_plan(api, download, task, run_id):
    """Digest-check the original GitHub-owned plan ZIP, never extract to disk."""
    catalog = api(f"{RUNS}/{run_id}/artifacts?per_page=20")
    rows = catalog.get("artifacts")
    need(isinstance(rows, list) and len(rows) == catalog.get("total_count") < 20,
         "PLAN_ARTIFACT_LIST_INCOMPLETE")
    matches = [a for a in rows if a.get("name") == f"autonomous-task-{run_id}"]
    need(len(matches) == 1, "ORIGINAL_PLAN_ARTIFACT_UNAVAILABLE")
    artifact = matches[0]
    size = artifact.get("size_in_bytes")
    need(positive(artifact.get("id")) and positive(size) and size <= MAX_ARCHIVE and
         artifact.get("expired") is False and
         re.fullmatch(r"sha256:[0-9a-f]{64}", artifact.get("digest") or ""),
         "ORIGINAL_PLAN_ARTIFACT_INVALID")
    origin = artifact.get("workflow_run")
    if origin is not None:
        need(origin.get("id") == run_id and origin.get("repository_id") == contract.REPO_ID and
             origin.get("head_sha") == task["source_sha"], "ORIGINAL_PLAN_ARTIFACT_ORIGIN")
    raw = download(artifact["id"])
    need(len(raw) == size and artifact["digest"] == "sha256:" + contract.digest(raw),
         "ORIGINAL_PLAN_ARTIFACT_DIGEST")
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [a for a in archive.infolist() if a.filename == "task.json"]
            need(len(members) == 1 and 0 < members[0].file_size <= contract.MAX_JSON,
                 "ORIGINAL_PLAN_TASK_ENTRY")
            recorded = contract.parse(archive.read(members[0]))
    except (OSError, RuntimeError, zipfile.BadZipFile):
        raise contract.Held("ORIGINAL_PLAN_ZIP_INVALID") from None
    need(contract.canonical(recorded) == contract.canonical(task), "ORIGINAL_PLAN_TASK_MISMATCH")


def independent_result(api, task, run_id, jobs):
    """Read App PR, exact patch and both CI events independently of run success."""
    branch = github.branch_for(task, run_id)
    candidates = api(github.BASE + "/pulls?state=all&head=MichaelWave369:" + branch +
                     "&base=main&per_page=100")
    need(isinstance(candidates, list) and len(candidates) <= 1, "R1_PR_AMBIGUOUS")
    if not candidates:
        return {}, "AUTHORIZED", None
    number = candidates[0].get("number")
    need(positive(number), "R1_PR_NUMBER")
    pr = api(github.BASE + f"/pulls/{number}")
    head = pr.get("head", {}).get("sha")
    need(pr.get("number") == number and pr.get("user", {}).get("id") == PUBLISHER_ID and
         pr.get("user", {}).get("type") == "Bot" and
         contract.HEX40.fullmatch(head or ""), "R1_PUBLISHER_OR_HEAD_MISMATCH")
    result = {"pr_number": number, "tested_sha": head}
    merged = pr.get("merged") is True
    if pr.get("state") == "closed" and not merged:
        return result, "HELD", "PR_CLOSED_UNMERGED"
    proposal = contract.proposal(task, github.source_files(api, task), 0)
    github.verify_pr(api, task, pr, proposal, run_id, merged=merged)
    checks = github.check_runs(api, head)
    ci_ids = {int(c["details_url"].split("/")[7]) for c in checks if c["details_url"]}
    result["ci_runs"] = json.dumps(sorted(ci_ids))
    if not github.green(checks):
        result["ci_status"] = ("FAILED" if any(c["status"] == "completed" and
                               c["conclusion"] not in (None, "success") for c in checks)
                               else "PENDING")
        return result, "CI_PENDING", None
    result["ci_status"] = "PASSED"
    if not merged:
        return result, "CI_PASSED", None
    need(job_passed(jobs, "merge-gate") and pr.get("merged_by", {}).get("id") == 41898282,
         "R1_MERGE_GATE_NOT_CORROBORATED")
    sha = pr.get("merge_commit_sha")
    need(contract.HEX40.fullmatch(sha or "") and pr.get("merged_at"), "R1_MERGE_NOT_RECORDED")
    commit = api(github.BASE + "/commits/" + sha)
    need(commit.get("sha") == sha and [p.get("sha") for p in commit.get("parents", [])] ==
         [task["source_sha"]], "R1_MERGE_PARENT_DRIFT")
    github.verify_commit_tree(api, task, sha, proposal)
    latest = api(github.BASE + f"/pulls/{number}")
    need(latest.get("merged") is True and latest.get("merge_commit_sha") == sha and
         latest.get("head", {}).get("sha") == head, "R1_PR_CHANGED_DURING_VERIFICATION")
    return {**result, "merge_sha": sha}, "MERGED", None


class TurnLane:
    def __init__(self, control, api, *, clock=None):
        self.control, self.api = control, api
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def enqueue(self, task, observation, event_id, confirmation):
        need(confirmation == CONFIRM, "R1_ADMISSION_CONFIRMATION_REQUIRED")
        now = self.clock()
        contract.validate(task, now=now)
        github.identity(self.api)
        need(github.main_head(self.api) == task["source_sha"], "SOURCE_DRIFT")
        contract.proposal(task, github.source_files(self.api, task), 0)
        result = self.control.enqueue_observed(
            observation, event_id, held_intake(task), confirmation=r9.CONFIRM,
            now=now, r1_task=task)
        return {**result, "head_revalidated": True}

    def snapshot(self):
        now = self.clock()
        # Current local visibility plus a live repository identity read. Never
        # export titles, instructions, task bytes, worker handles or local paths.
        visible, _ = r9._present(self.control.registry, now)
        need(visible.get(contract.REPO_ID) == contract.REPO, "R1_REPO_NOT_VISIBLE")
        github.identity(self.api)
        with self.control.leases._connection() as db:
            rows = db.execute("""SELECT m.mission_id,m.repository,m.github_id,m.source_sha,
                m.intake_digest AS task_sha256,m.updated_ms,e.source_event_id,e.source_scan_id,
                e.source_payload_digest,t.expires_utc,t.state,t.run_id,t.pr_number,t.tested_sha,
                t.merge_sha,t.reason,t.active_job,t.ci_status,t.ci_runs FROM r10_r1_turns t
                JOIN r9_missions m USING(mission_id) JOIN r10_event_links e USING(mission_id)
                ORDER BY m.updated_ms DESC, m.rowid DESC LIMIT 31""").fetchall()
        return {"schema": SCHEMA, "generated_utc": now.isoformat(),
                "truncated": len(rows) > 30,
                "turns": [{**r, "ci_runs": json.loads(r["ci_runs"])} for r in rows[:30]]}

    def row(self, mission_id=None):
        with self.control.leases._connection() as db:
            if mission_id is None:
                return db.execute("""SELECT m.mission_id,m.source_sha,m.intake_digest,t.*
                    FROM r9_missions m JOIN r10_r1_turns t USING(mission_id)
                    WHERE t.state NOT IN ('MERGED','ARCHIVED') ORDER BY m.created_ms LIMIT 1""").fetchone()
            result = db.execute("""SELECT m.mission_id,m.source_sha,m.intake_digest,t.*
                FROM r9_missions m JOIN r10_r1_turns t USING(mission_id)
                WHERE m.mission_id=?""", (mission_id,)).fetchone()
            need(result is not None, "R1_MISSION_NOT_FOUND")
            return result

    @staticmethod
    def task(row):
        task = contract.parse(row["task_json"])
        need(contract.task_digest(task) == row["intake_digest"] and
             task["source_sha"] == row["source_sha"], "R1_FROZEN_TASK_CHANGED")
        return task

    def update(self, row, state, reason=None, *, db=None, **fields):
        if db is None:
            with self.control.leases._transaction() as transaction:
                self.update(row, state, reason, db=transaction, **fields)
            return
        if all(row[k] == v for k, v in {"state": state, "reason": reason, **fields}.items()):
            return
        columns = ("origin", "run_id", "pr_number", "tested_sha", "merge_sha",
                   "active_job", "ci_status", "ci_runs", "run_terminal")
        changes = {k: fields[k] if k in fields else row[k] for k in columns}
        changed = db.execute("""UPDATE r10_r1_turns SET state=?,reason=?,origin=?,run_id=?,
            pr_number=?,tested_sha=?,merge_sha=?,active_job=?,ci_status=?,ci_runs=?,
            run_terminal=?,version=version+1
            WHERE mission_id=? AND version=?""",
            (state, reason, *changes.values(), row["mission_id"], row["version"])).rowcount
        need(changed == 1, "R1_RECONCILE_VERSION_CHANGED")
        parent = {"REQUESTED": "QUEUED", "HELD": "HELD_RECONCILE", "MERGED": "R1_MERGED"}.get(
            state, "ASSIGNED_IMPLEMENT")
        db.execute("""UPDATE r9_missions SET state=?,updated_ms=?,
            worker=CASE WHEN ?='QUEUED' THEN NULL ELSE ? END WHERE mission_id=?""",
                   (parent, int(self.clock().timestamp() * 1000), parent, WORKER, row["mission_id"]))

    def reserve(self, row, origin):
        # R9 fairness and one-repo exclusion remain local; GitHub is the only
        # execution fence. Store the intent before the possibly irreversible POST.
        need(row["state"] == "REQUESTED" and row["origin"] is None and
             origin in {"issues", "workflow_dispatch"}, "R1_SUBMISSION_ALREADY_FENCED")
        with self.control.leases._transaction() as db:
            available, _ = self.control._eligible(self.clock(), "implement", db=db)
            busy = db.execute("SELECT COUNT(*) FROM r9_missions WHERE state IN (" +
                              ",".join("?" for _ in r9.SLOTS) + ")", r9.SLOTS).fetchone()[0]
            need(busy < self.control.capacity and available and
                 available[0]["mission_id"] == row["mission_id"], "R1_WAITING_FOR_R9_TURN")
            self.update(row, "SUBMISSION_UNCERTAIN", "RECONCILE_BEFORE_ANY_NEW_REQUEST",
                        db=db, origin=origin)

    def dispatch(self, row, authenticate, submit):
        need(row["state"] == "REQUESTED" and row["origin"] is None, "R1_SUBMISSION_ALREADY_FENCED")
        task = self.task(row)
        try:
            owner = authenticate()
            need(owner.get("id") == contract.OWNER_ID and owner.get("type") == "User",
                 "R1_DISPATCH_REQUIRES_OWNER_CREDENTIAL")
            contract.validate(task, now=self.clock())
            github.identity(self.api)
            github.owner_environment(self.api)
            github.rules(self.api)
            need(github.main_head(self.api) == task["source_sha"], "SOURCE_DRIFT")
        except contract.Held as exc:
            self.update(row, "HELD", str(exc))
            return
        self.reserve(row, "workflow_dispatch")
        fenced = self.row(row["mission_id"])
        try:
            response = submit({"ref": "main", "inputs": {"task_json": row["task_json"]}})
            run_id = response.get("workflow_run_id")
            need(positive(run_id) and response.get("html_url") ==
                 f"{REPO_URL}/actions/runs/{run_id}", "R1_DISPATCH_RUN_ID_UNAVAILABLE")
        except contract.Held as exc:
            self.update(fenced, "SUBMISSION_UNCERTAIN", str(exc))
            return
        self.update(fenced, "DISPATCHED", run_id=run_id)

    def attach(self, row, run_id, download):
        """Recover a lost response or import an owner-initiated issue run."""
        need(positive(run_id) and row["state"] not in {"MERGED", "ARCHIVED"} and
             row["run_id"] in (None, run_id), "R1_RUN_ALREADY_BOUND_OR_INVALID")
        task = self.task(row)
        github.identity(self.api)
        run = self.api(f"{RUNS}/{run_id}")
        github.run_identity(run, task, run_id, task["source_sha"])
        need(row["origin"] in (None, run["event"]), "R1_RUN_EVENT_MISMATCH")
        jobs = job_records(self.api, run_id, task)
        need(job_passed(jobs, "plan"), "R1_PLAN_NOT_SUCCESSFUL")
        frozen_plan(self.api, download, task, run_id)
        if row["state"] == "REQUESTED":
            self.reserve(row, run["event"])
            row = self.row(row["mission_id"])
        if row["run_id"] is None:
            self.update(row, "DISPATCHED", origin=run["event"], run_id=run_id)

    def recover_submission(self, row, download):
        """Bound lookup to one page and never repeat a network write."""
        task = self.task(row)
        event = row["origin"]
        need(event in {"issues", "workflow_dispatch"}, "R1_NO_SUBMISSION_TO_RECOVER")
        try:
            listed = self.api(f"{RUNS}?head_sha={task['source_sha']}&event={event}&per_page=12")
            runs = listed.get("workflow_runs")
            need(isinstance(runs, list) and len(runs) == listed.get("total_count") < 12,
                 "R1_RUN_LOOKUP_INCOMPLETE")
            matches = []
            for run in runs:
                if run.get("path", "").split("@")[0] != github.WORKFLOW:
                    continue
                run_id = run.get("id")
                github.run_identity(run, task, run_id, task["source_sha"])
                if not job_passed(job_records(self.api, run_id, task), "plan"):
                    continue
                try:
                    frozen_plan(self.api, download, task, run_id)
                except contract.Held as exc:
                    if str(exc) in {"ORIGINAL_PLAN_TASK_MISMATCH", "ORIGINAL_PLAN_ARTIFACT_INVALID",
                                    "ORIGINAL_PLAN_ARTIFACT_UNAVAILABLE"}:
                        continue
                    raise
                matches.append(run_id)
            need(len(matches) == 1, "R1_SUBMISSION_NEEDS_ORIGINAL_RUN_REVIEW")
            self.attach(row, matches[0], download)
        except (contract.Held, artifacts.CloudReviewHeld) as exc:
            self.update(row, "HELD", str(exc))

    def retry_preflight(self, row):
        need(row["state"] == "HELD" and row["origin"] is None and row["run_id"] is None,
             "R1_ONLY_UNSUBMITTED_PREFLIGHT_CAN_RETRY")
        contract.validate(self.task(row), now=self.clock())
        self.update(row, "REQUESTED")

    def reconcile(self, row):
        run_id = row["run_id"]
        if run_id is None or row["state"] in {"MERGED", "ARCHIVED"}:
            return
        task = self.task(row)
        try:
            github.identity(self.api)
            run = self.api(f"{RUNS}/{run_id}")
            github.run_identity(run, task, run_id, task["source_sha"])
            need(run.get("event") == row["origin"], "R1_RUN_EVENT_MISMATCH")
            jobs = job_records(self.api, run_id, task)
            active = next((name for name, job in jobs.items()
                           if job.get("status") == "in_progress"), None)
            done = run.get("status") == "completed"
            fields = {"active_job": active, "run_terminal": int(done)}
            if not job_passed(jobs, "owner-authorization"):
                if done:
                    self.update(row, "HELD", "R1_PLAN_OR_OWNER_REVIEW_DID_NOT_PASS", **fields)
                elif self.clock() >= contract.instant(task["expires_utc"]):
                    self.update(row, "HELD", "OWNER_REVIEW_WINDOW_EXPIRED", **fields)
                else:
                    self.update(row, "OWNER_REVIEW" if job_passed(jobs, "plan") else "DISPATCHED", **fields)
                return
            approved_at = contract.instant(jobs["owner-authorization"].get("completed_at"))
            need(contract.instant(task["created_utc"]) <= approved_at <
                 contract.instant(task["expires_utc"]), "R1_OWNER_JOB_OUTSIDE_TASK_WINDOW")
            # The trusted job validated the environment at authorization time.
            # Historical readback uses the original review record even after
            # the repository's current environment configuration changes.
            github.original_owner_review(self.api, task, run_id, task["source_sha"])
            if active == "attempt-0 / worker":
                state, reason = "RUNNING", None
            elif "attempt-0 / publish" not in jobs:
                state, reason = "AUTHORIZED", None
            else:
                evidence, state, reason = independent_result(self.api, task, run_id, jobs)
                fields.update(evidence)
                if fields.get("pr_number") and state == "CI_PENDING" and active == "attempt-0 / publish":
                    state = "PUBLISHED"
            if done and state not in {"MERGED", "HELD"}:
                state, reason = "HELD", {
                    "CI_PENDING": "R1_FINISHED_WITHOUT_ALL_REQUIRED_CI",
                    "CI_PASSED": "R1_CI_PASSED_MERGE_UNCONFIRMED",
                }.get(state, "R1_FINISHED_BEFORE_VERIFIED_PUBLISH")
        except contract.Held as exc:
            state, reason = "HELD", str(exc)
            fields = {"active_job": None}
        self.update(row, state, reason, **fields)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steward-db", type=Path, default=Path("~/.agentora/fleet-stewards.sqlite3"))
    parser.add_argument("--lease-db", type=Path, default=Path("~/.agentora/fleet-leases.sqlite3"))
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source", type=Path, default=Path("."))
    prep.add_argument("--out", type=Path, required=True)
    for key in ("task-id", "path", "before", "after", "objective", "acceptance"):
        prep.add_argument("--" + key, required=True)
    queue = sub.add_parser("enqueue")
    queue.add_argument("--task", type=Path, required=True)
    queue.add_argument("--observations", type=Path, help="Otherwise read local RepoNerve directly")
    queue.add_argument("--event-id", type=int, required=True)
    queue.add_argument("--confirm", required=True)
    tick = sub.add_parser("tick")
    tick.add_argument("--dispatch", action="store_true")
    tick.add_argument("--snapshot", type=Path)
    attach = sub.add_parser("attach")
    attach.add_argument("--mission-id", required=True)
    attach.add_argument("--run-id", type=int, required=True)
    retry = sub.add_parser("retry-preflight")
    retry.add_argument("--mission-id", required=True)
    status = sub.add_parser("snapshot")
    status.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            need(not args.out.exists() and not args.out.is_symlink(), "TASK_OUTPUT_ALREADY_EXISTS")
            task = prepare(args.source, args.task_id, args.path, args.before, args.after,
                           args.objective, args.acceptance)
            turn.write(args.out, task)
            return 0
        read_token = os.environ.get("AGENTORA_R1_READ_TOKEN")
        write_token = os.environ.get("AGENTORA_R1_DISPATCH_TOKEN")
        lane = TurnLane(r9.MissionControl(r9.StewardRegistry(args.steward_db.expanduser()),
                        leases.LeaseLedger(args.lease_db.expanduser())), github.GitHub(read_token))
        if args.action == "enqueue":
            if args.observations:
                path = args.observations
                need(path.is_file() and not path.is_symlink() and
                     0 < path.stat().st_size <= r9.MAX_INPUT_BYTES, "OBSERVATION_FILE_UNSAFE")
                observation = json.loads(path.read_bytes())
            else:
                observation = collect_public_observations()
            need(args.confirm == CONFIRM, "R1_ADMISSION_CONFIRMATION_REQUIRED")
            lane.control.registry.ingest(observation)
            result = lane.enqueue(turn.read(args.task), observation, args.event_id, args.confirm)
            output_json(result)
        elif args.action == "attach":
            lane.attach(lane.row(args.mission_id), args.run_id,
                        lambda aid: artifacts.download_artifact(aid, read_token))
            lane.reconcile(lane.row(args.mission_id))
            output_json(lane.snapshot())
        elif args.action == "retry-preflight":
            lane.retry_preflight(lane.row(args.mission_id))
            output_json(lane.snapshot())
        elif args.action == "tick":
            row = lane.row()
            if row is not None:
                if args.dispatch and row["state"] == "REQUESTED":
                    if write_token:
                        lane.dispatch(row, lambda: github_request(write_token, "/user"),
                                      lambda payload: github_request(write_token, DISPATCH, payload))
                    else:
                        lane.update(row, "HELD", "AGENTORA_R1_DISPATCH_TOKEN_REQUIRED")
                elif row["state"] == "SUBMISSION_UNCERTAIN":
                    lane.recover_submission(row, lambda aid: artifacts.download_artifact(aid, read_token))
                else:
                    lane.reconcile(row)
            output_json(lane.snapshot(), args.snapshot)
        else:
            output_json(lane.snapshot(), args.out)
        return 0
    except (contract.Held, r9.MissionHeld, r9.StewardHeld, r9.stewardship.HandoffHeld, RepoNerveUnavailable,
            leases.LeaseHeld, artifacts.CloudReviewHeld) as exc:
        print("R9_R1_HELD " + str(exc), file=sys.stderr)
        return 3
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, subprocess.SubprocessError):
        print("R9_R1_HELD INPUT_OR_RECONCILIATION_UNAVAILABLE", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
