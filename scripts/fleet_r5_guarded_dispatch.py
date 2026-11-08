"""Fleet R5: guarded, fixed-scope GitHub Actions test dispatch.

An explicitly authorized operator can submit the EXISTING fixed PhiMadaPrime
R0.6 sandbox-test workflow, after R2/R3 steward & R0.4 lease checks and R0.5
independent HEAD observations. This does not run an arbitrary command, write
source code, deploy, approve, or merge anything.

GitHub workflow_dispatch acceptance is NOT a completed run or verified test.
The R0.7/R4 evidence chain is still required independently.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "server"))
from app.services.fleet_stewards import StewardRegistry, StewardHeld
import fleet_r04_leases as leases
import fleet_r05_source_observe as source
import fleet_r06_pilot as pilot
import fleet_r3_steward_claim as steward

SCHEMA = "agentora.fleet.guarded-fixed-dispatch.v0.5"
CONFIRM = "DISPATCH_FIXED_PHI_MADA_TESTS"
WORKFLOW = "fleet-r06-phimada-pilot.yml"
WORKFLOW_PATH = ".github/workflows/" + WORKFLOW
WORKFLOW_ENDPOINT = "/repos/MichaelWave369/Agentora/actions/workflows/" + WORKFLOW
REQUEST = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")


class DispatchHeld(ValueError):
    """Held without claiming that a GitHub job has been queued."""


def need(condition, reason):
    if not condition:
        raise DispatchHeld(reason)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_dispatch(token, sha, request_id=None):
    """Exactly one POST to a fixed workflow, optionally with R10 trace ID."""
    need(type(token) is str and bool(token.strip()), "ACTIONS_WRITE_TOKEN_REQUIRED")
    need(pilot.SHA40.fullmatch(sha) is not None, "SHA_INVALID")
    need(request_id is None or (type(request_id) is str and
         REQUEST.fullmatch(request_id) is not None), "DISPATCH_TRACE_ID_INVALID")
    inputs = {"source_sha": sha, "confirmation": pilot.CONFIRMATION}
    if request_id is not None:
        inputs["request_id"] = request_id
    body = json.dumps({"ref": "main", "inputs": inputs},
                      separators=(",", ":")).encode("utf-8")
    request = Request(
        "https://api.github.com" + WORKFLOW_ENDPOINT + "/dispatches",
        data=body, method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "agentora-r5-fixed-pilot-dispatch",
        },
    )
    try:
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=12) as response:
            # Standard workflow_dispatch returns 204 (no run ID).
            return response.status
    except HTTPError as exc:
        return exc.code
    except (URLError, TimeoutError, OSError) as exc:
        raise DispatchHeld("POST_OUTCOME_UNKNOWN") from None


def _workflow_is_trusted(get, token):
    response = get(WORKFLOW_ENDPOINT, token)
    need(type(response) is dict and
         response.get("path") == WORKFLOW_PATH and
         response.get("state") == "active" and
         type(response.get("id")) is int and response["id"] > 0,
         "WORKFLOW_NOT_ACTIVE_OR_CHANGED")


def _owned(ledger, capability, now_ms):
    with ledger._connection() as db:
        try:
            return dict(ledger._check_owned(db, capability, now_ms))
        except leases.LeaseHeld:
            raise DispatchHeld("LEASE_EXPIRED_OR_FENCED") from None


def _ready(registry, ledger, intake, capability, get, token, clock_ms, now):
    info = leases.validate_intake(intake)
    need(info["repository"] == pilot.REPOSITORY and
         info["repository_id"] == pilot.REPOSITORY_ID and
         intake.get("default_branch") == pilot.BRANCH,
         "ONLY_FIXED_PUBLIC_PHI_MADA_ALLOWED")
    selected = steward.eligible(registry, intake, now=now)
    moment = clock_ms()
    row = _owned(ledger, capability, moment)
    need(row["repository_id"] == info["repository_id"] and
         row["repository"] == info["repository"] and
         row["source_sha"] == info["source_sha"] and
         row["request_sha256"] == info["request_sha256"],
         "LEASE_INTAKE_MISMATCH")
    need(row["expires_ms"] - moment >= 60000, "LEASE_RENEWAL_REQUIRED")
    # Real GitHub HEAD, not the RepoNerve scan time or an untrusted receipt.
    observation = source.observe(intake, capability, ledger,
                                 get=get, token=token, clock=clock_ms)
    need(observation["state"] == "SOURCE_HEAD_MATCH_OBSERVED"
         and observation["source_head_observed_match"] is True,
         "SOURCE_HEAD_NOT_CURRENT")
    return selected, row


def _ensure_table(ledger):
    with ledger._transaction() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS r5_fixed_dispatches (
            request_id TEXT PRIMARY KEY,
            claim_key TEXT NOT NULL UNIQUE,
            source_sha TEXT NOT NULL,
            lease_generation INTEGER NOT NULL,
            worker TEXT NOT NULL,
            github_id INTEGER NOT NULL,
            state TEXT NOT NULL,
            attempted_ms INTEGER NOT NULL,
            updated_ms INTEGER NOT NULL
        )""")


def dispatch(registry, ledger, intake, capability, *, request_id,
             execute=False, confirmation=None, token=None,
             get=source.github_get, post=github_dispatch,
             now=None, clock_ms=leases.epoch_ms):
    """Dry-run by default; a real POST requires opt-in, current fenced lease.

    The dispatch intent is persisted BEFORE the POST under the same SQLite
    transaction lock domain as the R0.4 lease. Unknown POST outcomes are not
    retried, preventing accidental duplicate jobs.
    """
    need(type(request_id) is str and REQUEST.fullmatch(request_id) is not None,
         "REQUEST_ID_INVALID")
    need(type(execute) is bool, "EXECUTION_FLAG_INVALID")
    need(confirmation == CONFIRM if execute else confirmation is None,
         "EXPLICIT_OPERATOR_CONFIRMATION_REQUIRED")
    need(callable(get) and callable(post) and callable(clock_ms), "CALLBACK_INVALID")
    if execute:
        need(type(token) is str and bool(token.strip()), "ACTIONS_WRITE_TOKEN_REQUIRED")
    now = now or datetime.now(timezone.utc)
    need(isinstance(now, datetime) and now.tzinfo is not None, "CLOCK_INVALID")
    first, _ = _ready(registry, ledger, intake, capability, get, token, clock_ms, now)
    _workflow_is_trusted(get, token)
    second, _ = _ready(registry, ledger, intake, capability, get, token, clock_ms, now)
    need(first == second, "STEWARD_CHANGED_DURING_PREFLIGHT")
    if not execute:
        return {
            "schema": SCHEMA, "state": "DRY_RUN_READY_NO_DISPATCH",
            "request_id": request_id, "repository": pilot.REPOSITORY,
            "source_sha": intake["source_sha"],
            "steward_key": first["steward_key"],
            "lease_generation": capability["generation"],
            "github_request_accepted": False, "run_id": None,
            "actual_jobs_dispatched": 0, "merge_authorized": False,
            "product_verified": False,
        }
    # Generate one idempotent intent per repo + fenced lease generation. Never
    # reissue even if a prior POST failed/returned an uncertain result.
    _ensure_table(ledger)
    claim_key = f'{pilot.REPOSITORY_ID}:{capability["generation"]}:{intake["source_sha"]}'
    moment = clock_ms()
    with ledger._transaction() as db:
        try:
            row = dict(ledger._check_owned(db, capability, moment))
        except leases.LeaseHeld:
            raise DispatchHeld("LEASE_EXPIRED_OR_FENCED") from None
        need(row["expires_ms"] - moment >= 60000, "LEASE_RENEWAL_REQUIRED")
        need(row["repository_id"] == pilot.REPOSITORY_ID and
             row["source_sha"] == intake["source_sha"] and
             row["request_sha256"] == intake["request_sha256"],
             "LEASE_CHANGED_DURING_DISPATCH")
        prior = db.execute(
            "SELECT request_id,state FROM r5_fixed_dispatches WHERE request_id=? OR claim_key=?",
            (request_id, claim_key)).fetchone()
        need(prior is None, "DISPATCH_ALREADY_ATTEMPTED_FOR_LEASE")
        db.execute("""INSERT INTO r5_fixed_dispatches
            (request_id,claim_key,source_sha,lease_generation,worker,github_id,
             state,attempted_ms,updated_ms) VALUES (?,?,?,?,?,?,?,?,?)""",
            (request_id, claim_key, intake["source_sha"],
             capability["generation"], capability["worker"], pilot.REPOSITORY_ID,
             "POST_OUTCOME_UNKNOWN", moment, moment))
    # No secret lease token is transferred to GitHub. The workflow itself
    # independently rechecks HEAD before and after fixed sandboxed checks.
    try:
        status = post(token, intake["source_sha"])
    except Exception:
        # Network failures are not retried. GitHub may already have accepted it.
        status = None
    state = ("REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED" if status == 204 else
             "GITHUB_REJECTED_REQUEST" if type(status) is int and 400 <= status < 500 else
             "POST_OUTCOME_UNKNOWN")
    with ledger._transaction() as db:
        db.execute("""UPDATE r5_fixed_dispatches SET state=?,updated_ms=?
            WHERE request_id=? AND state='POST_OUTCOME_UNKNOWN'""",
            (state, clock_ms(), request_id))
    return {
        "schema": SCHEMA, "state": state, "request_id": request_id,
        "repository": pilot.REPOSITORY, "repository_id": pilot.REPOSITORY_ID,
        "source_sha": intake["source_sha"], "steward_key": first["steward_key"],
        "lease_generation": capability["generation"],
        "github_request_accepted": status == 204, "run_id": None,
        "actual_jobs_dispatched": "UNKNOWN_UNTIL_GITHUB_RUN_DISCOVERED",
        "merge_authorized": False, "product_verified": False,
        "verified_complete": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--steward-db", required=True, type=Path)
    p.add_argument("--lease-db", required=True, type=Path)
    p.add_argument("--intake", required=True, type=Path)
    p.add_argument("--lease-file", required=True, type=Path)
    p.add_argument("--request-id", required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--confirm")
    a = p.parse_args(argv)
    try:
        result = dispatch(
            StewardRegistry(a.steward_db.expanduser()),
            leases.LeaseLedger(a.lease_db.expanduser()),
            leases.load_intake(a.intake.expanduser()),
            leases.load_capability(a.lease_file.expanduser()),
            request_id=a.request_id, execute=a.execute, confirmation=a.confirm,
            token=os.environ.get("GITHUB_TOKEN"))
        print(json.dumps(result, indent=2))
        return 0 if result["state"] in (
            "DRY_RUN_READY_NO_DISPATCH",
            "REQUEST_ACCEPTED_BY_GITHUB_NOT_RUN_VERIFIED") else 3
    except (DispatchHeld, steward.HandoffHeld, leases.LeaseHeld,
            source.ObservationHeld, StewardHeld, OSError, ValueError) as exc:
        print("FLEET_R5_HELD " + str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
