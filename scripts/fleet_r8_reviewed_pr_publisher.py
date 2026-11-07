"""Fleet R8: one reviewed R7 artifact -> one *draft* PhiMadaPrime pull request.

Dry-run by default. Explicit operator review of the exact patch SHA-256 plus
a limited-scope token are required before any GitHub write. The model and
the R7 GitHub Actions runner never receive those permissions.

No auto retry after an uncertain write, no automatic approvals, no merge,
no deployment and no product-complete claim. A partial branch is held for
operator reconciliation, not silently retried or deleted.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import base64
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

import fleet_r06_pilot as pilot
import fleet_r8_independent_review as audit

SCHEMA = "agentora.fleet.r8-draft-pr-handoff.v0.8"
CONFIRM = "PUBLISH_REVIEWED_PHI_MADA_DRAFT_PR"
REPO = "MichaelWave369/PhiMadaPrime"
BASE = "/repos/" + REPO
REF_PATH = BASE + "/git/refs"
CONTENT_PATH = BASE + "/contents/src/reponerve.jsx"
PULL_PATH = BASE + "/pulls"
REQUEST_ID = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
MAX_FILE_BYTES = 2_000_000


class PublishHeld(ValueError):
    """Publication held. Previous ambiguous writes must be reconciled manually."""


def require(condition, reason):
    if not condition:
        raise PublishHeld(reason)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_write(path, method, body, token):
    """Fixed-endpoint POST/PUT, no redirects, no proxy, no arbitrary URLs."""
    require((path, method) in {
        (REF_PATH, "POST"), (CONTENT_PATH, "PUT"), (PULL_PATH, "POST"),
    }, "GITHUB_WRITE_PATH_REFUSED")
    require(type(token) is str and bool(token.strip()),
            "GITHUB_WRITE_TOKEN_REQUIRED")
    require(type(body) is dict, "GITHUB_WRITE_BODY_INVALID")
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    require(len(raw) <= 400000, "GITHUB_WRITE_TOO_LARGE")
    request = Request(
        "https://api.github.com" + path,
        method=method, data=raw,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentora-r8-reviewed-draft-pr-publisher",
        },
    )
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(
            request, timeout=15
        ) as response:
            payload = response.read(96_001)
            require(len(payload) <= 96000, "GITHUB_WRITE_RESPONSE_TOO_LARGE")
            return response.status, json.loads(payload.decode("utf-8"))
    except HTTPError:
        raise PublishHeld("GITHUB_WRITE_REJECTED_RECONCILE_MANUALLY") from None
    except (URLError, TimeoutError, OSError, UnicodeError, ValueError):
        raise PublishHeld("GITHUB_WRITE_OUTCOME_UNKNOWN") from None


class PublishLedger:
    """Private same-host record of non-retryable mutation attempts."""
    def __init__(self, path):
        self.path = Path(path).expanduser()
        require(str(self.path) != ":memory:" and not self.path.is_symlink(),
                "JOURNAL_PATH_UNSAFE")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(not self.path.parent.is_symlink(), "JOURNAL_PARENT_SYMLINK")
        if os.name == "posix":
            require((self.path.parent.stat().st_mode & 0o022) == 0,
                    "JOURNAL_PARENT_WRITABLE")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        os.close(fd)
        if os.name == "posix":
            require((self.path.stat().st_mode & 0o077) == 0,
                    "JOURNAL_PERMISSIONS_UNSAFE")
        with self.transaction() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS r8_attempts (
                request_id TEXT PRIMARY KEY,
                run_id INTEGER NOT NULL UNIQUE,
                branch TEXT NOT NULL UNIQUE,
                artifact_sha256 TEXT NOT NULL,
                patch_sha256 TEXT NOT NULL,
                source_sha TEXT NOT NULL,
                state TEXT NOT NULL,
                pr_number INTEGER,
                recorded_utc TEXT NOT NULL
            )""")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        finally:
            db.close()

    def begin(self, request_id, report, branch, now):
        with self.transaction() as db:
            existing = db.execute(
                """SELECT request_id FROM r8_attempts
                   WHERE request_id=? OR run_id=? OR branch=?""",
                (request_id, report["github_run_id"], branch),
            ).fetchone()
            require(existing is None, "PUBLISH_ALREADY_ATTEMPTED_NO_RETRY")
            db.execute("""INSERT INTO r8_attempts(
                request_id,run_id,branch,artifact_sha256,patch_sha256,
                source_sha,state,recorded_utc) VALUES (?,?,?,?,?,?,?,?)""",
                (request_id, report["github_run_id"], branch,
                 report["github_artifact_sha256"], report["patch_sha256"],
                 report["source_sha"], "WRITE_OUTCOME_UNKNOWN",
                 now.isoformat()))

    def record(self, request_id, state, pr_number=None):
        with self.transaction() as db:
            db.execute("""UPDATE r8_attempts
                SET state=?,pr_number=? WHERE request_id=?""",
                (state, pr_number, request_id))


def _head_matches(sha, get, token, now):
    observed = pilot.observe_public_head(
        sha, get=get, token=token, clock=lambda: now)
    require(observed["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
            and observed["head_match"] is True
            and observed["identity_match"] is True,
            "MAIN_HEAD_CHANGED_HOLD")


def publish(run_id, zip_bytes, trusted_agentora_sha, *,
            request_id, reviewed_patch_sha256=None, execute=False,
            confirmation=None, token=None, get=audit.fixed_get,
            writer=github_write, journal_path=None, clock=None):
    """Explicit action separated from the R7 worker and R8 independent audit.

    Dry-run verifies live GitHub evidence and patch content but never writes.
    An executing call records a nonretryable intent *before* the first POST.
    """
    require(type(request_id) is str and REQUEST_ID.fullmatch(request_id) is not None,
            "REQUEST_ID_INVALID")
    require(type(execute) is bool, "EXECUTE_FLAG_INVALID")
    require(confirmation == CONFIRM if execute else confirmation is None,
            "EXPLICIT_PUBLISH_CONFIRMATION_REQUIRED")
    require(callable(get) and callable(writer), "CALLBACK_INVALID")
    if execute:
        require(type(token) is str and bool(token.strip()),
                "GITHUB_WRITE_TOKEN_REQUIRED")
        require(type(reviewed_patch_sha256) is str
                and audit.HEX64.fullmatch(reviewed_patch_sha256) is not None,
                "EXACT_REVIEWED_PATCH_DIGEST_REQUIRED")
    now = (clock or (lambda: datetime.now(timezone.utc)))()
    require(isinstance(now, datetime) and now.tzinfo is not None,
            "CLOCK_INVALID")
    now = now.astimezone(timezone.utc)
    report, revised_bytes = audit.review(
        run_id, zip_bytes, trusted_agentora_sha,
        get=get, token=token, clock=lambda: now)
    if execute:
        require(reviewed_patch_sha256 == report["patch_sha256"],
                "OPERATOR_REVIEWED_PATCH_MISMATCH")
    branch = ("fleet/r8-" + report["source_sha"][:10]
              + "-" + report["proposal_sha256"][:12])
    require(len(revised_bytes) <= 200000, "PROPOSED_CONTENT_LIMIT")
    result = {
        "schema": SCHEMA, "state": "DRY_RUN_VERIFIED_NOT_PUBLISHED",
        "request_id": request_id,
        "repository": REPO, "base_sha": report["source_sha"],
        "file": report["source_file"],
        "branch": branch, "github_run_id": run_id,
        "github_artifact_sha256": report["github_artifact_sha256"],
        "patch_sha256": report["patch_sha256"],
        "candidate_sha256": report["candidate_sha256"],
        "draft_pr_number": None, "draft_pr_url": None,
        "github_writes_attempted": False,
        "model_output_is_untrusted": True,
        "independent_artifact_review": True,
        "manual_code_review_required": True,
        "merge_authorized": False, "verified_complete": False,
        "product_verified": False,
    }
    if not execute:
        return result

    require(journal_path is not None, "PRIVATE_JOURNAL_REQUIRED")
    journal = PublishLedger(journal_path)
    # Refresh HEAD just before creating durable one-shot mutation intent.
    _head_matches(report["source_sha"], get, token, now)
    journal.begin(request_id, report, branch, now)
    result["github_writes_attempted"] = True

    try:
        _head_matches(report["source_sha"], get, token, now)
        code, body = writer(REF_PATH, "POST", {
            "ref": "refs/heads/" + branch, "sha": report["source_sha"],
        }, token)
        require(code == 201 and type(body) is dict
                and body.get("ref") == "refs/heads/" + branch,
                "BRANCH_CREATE_OUTCOME_UNKNOWN")
        journal.record(request_id, "BRANCH_CREATED_NOT_PR")

        # If main moved, leave branch for manual review without writing code.
        _head_matches(report["source_sha"], get, token, now)
        code, body = writer(CONTENT_PATH, "PUT", {
            "message": "Propose reviewed R7 patch for separate code review",
            "content": base64.b64encode(revised_bytes).decode("ascii"),
            "branch": branch, "sha": report["source_blob_sha"],
        }, token)
        require(code in (200, 201) and type(body) is dict
                and type(body.get("content")) is dict
                and body["content"].get("path") == report["source_file"],
                "BRANCH_EDIT_OUTCOME_UNKNOWN")
        journal.record(request_id, "BRANCH_EDITED_NOT_PR")

        _head_matches(report["source_sha"], get, token, now)
        pr_body = (
            "## Manual review required\n\n"
            "Bounded untrusted R7 model proposal from a GitHub-verified "
            "run and SHA-256-correlated artifact. This PR is **draft only**.\n\n"
            "Source SHA: " + report["source_sha"] + "\n\n"
            "Reviewed patch SHA-256: " + report["patch_sha256"] + "\n\n"
            "Artifact SHA-256: " + report["github_artifact_sha256"] + "\n\n"
            "Evidence: https://github.com/MichaelWave369/Agentora/actions/runs/"
            + str(run_id) + "\n\n"
            "Tests/build were reported passed by the fixed workflow. "
            "Independent artifact and patch reconstruction were checked; "
            "security, product acceptance and deployment are **not** certified. "
            "No agent can approve or merge this PR."
        )
        code, body = writer(PULL_PATH, "POST", {
            "title": "Review bounded R7 source proposal",
            "head": branch, "base": "main",
            "body": pr_body, "draft": True,
            "maintainer_can_modify": True,
        }, token)
        require(code == 201 and type(body) is dict
                and type(body.get("number")) is int
                and body["number"] > 0
                and body.get("draft") is True
                and body.get("state") == "open"
                and body.get("html_url") ==
                "https://github.com/" + REPO + "/pull/" + str(body["number"]),
                "DRAFT_PR_RESPONSE_UNTRUSTED")
        journal.record(request_id, "DRAFT_PR_CREATED_AWAITING_REVIEW",
                       body["number"])
        result.update({
            "state": "DRAFT_PR_CREATED_AWAITING_REVIEW",
            "draft_pr_number": body["number"],
            "draft_pr_url": body["html_url"],
        })
        return result
    except Exception:
        # Unknown/partial writes must not be automatically retried. Do not
        # delete a branch in an uncertain state or accidentally create a PR.
        raise PublishHeld("WRITE_HELD_RECONCILE_GITHUB_AND_LOCAL_JOURNAL") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--trusted-agentora-sha", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--reviewed-patch-sha256")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--journal", type=Path,
                        default=Path("~/.agentora/fleet-r8-pr-publish.sqlite3"))
    args = parser.parse_args(argv)
    try:
        path = args.artifact_zip.expanduser()
        require(path.is_file() and not path.is_symlink()
                and 0 < path.stat().st_size <= audit.MAX_ARCHIVE,
                "ARTIFACT_FILE_UNSAFE")
        result = publish(
            args.run_id, path.read_bytes(), args.trusted_agentora_sha,
            request_id=args.request_id,
            reviewed_patch_sha256=args.reviewed_patch_sha256,
            execute=args.execute, confirmation=args.confirm,
            token=os.environ.get("GITHUB_TOKEN"),
            journal_path=args.journal.expanduser())
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (PublishHeld, audit.ReviewHeld,
            pilot.PilotHeld, pilot.source.ObservationHeld,
            OSError, ValueError) as exc:
        print("FLEET_R8_HELD " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
