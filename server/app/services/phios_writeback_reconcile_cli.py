"""One-shot local R4d operator reconciliation. No web endpoint or scheduler.

Usage: PYTHONPATH=server python -m app.services.phios_writeback_reconcile_cli
       --database /absolute/path/agentora.sqlite --run-id 42
       --expected-operation-id <64-lowercase-hex> [--apply]

Without --apply: offline inspection, no network or write.
With --apply: one GET-only receipt lookup and conditional SQLite update.
"""
from __future__ import annotations

import argparse
import json
import re
import stat
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlmodel import Session

from app.core.config import settings
from app.integrations.phios_client import IntegrationClientError
from app.models import IntegrationRun
from app.services.integration_orchestrator import IntegrationOrchestrator

_OPERATION_RE = re.compile(r"[0-9a-f]{64}")


def _existing_sqlite_file(path: str) -> Path:
    requested = Path(path).expanduser()
    if not requested.is_absolute() or requested.is_symlink():
        raise ValueError("operator database must be an existing absolute regular file")
    if not requested.is_file() or not stat.S_ISREG(requested.stat().st_mode):
        raise ValueError("operator database must be an existing absolute regular file")
    return requested.resolve(strict=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local operator-only R4d receipt reconciliation, GET-only"
    )
    parser.add_argument("--database", required=True, help="Existing absolute SQLite database")
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--expected-operation-id", required=True, help="Exact saved SHA-256 identity")
    parser.add_argument("--apply", action="store_true",
                        help="Perform one PhiOS GET and conditionally mark published receipt")
    args = parser.parse_args(argv)
    if args.run_id < 1 or _OPERATION_RE.fullmatch(args.expected_operation_id) is None:
        parser.error("run ID or expected operation ID is invalid")
    try:
        db = _existing_sqlite_file(args.database)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    engine = create_engine(
        URL.create("sqlite", database=str(db)),
        connect_args={"check_same_thread": False},
    )
    try:
        with Session(engine) as session:
            row = session.get(IntegrationRun, args.run_id)
            if row is None:
                print(json.dumps({"ok": False, "error_code": "RUN_NOT_FOUND"}))
                return 2
            if (row.writeback_operation_id != args.expected_operation_id
                    or row.writeback_status not in {"dispatching", "needs_reconciliation"}):
                print(json.dumps({"ok": False, "error_code": "NOT_HELD_OR_ID_MISMATCH"}))
                return 2
            if not args.apply:
                print(json.dumps({
                    "ok": False, "dry_run": True, "held": True,
                    "run_id": row.id,
                    "operation_id": row.writeback_operation_id,
                    "status": row.writeback_status,
                    "network_request_made": False,
                }, sort_keys=True))
                return 0
            if not settings.agentora_phios_writeback_v1_enabled:
                print(json.dumps({"ok": False, "error_code": "R4C_DISABLED"}))
                return 2
            try:
                result = IntegrationOrchestrator(session).reconcile_writeback_v1(args.run_id)
            except IntegrationClientError:
                # Never print raw remote errors or credentials.
                print(json.dumps({"ok": False, "error_code": "RECONCILIATION_HELD"}))
                return 2
            if not result["ok"]:
                print(json.dumps({
                    "ok": False, "held": True,
                    "status": result["status"],
                    "operation_id": args.expected_operation_id,
                    "network_operation": "GET_ONLY",
                }))
                return 2
            print(json.dumps({
                "ok": True, "reconciled": True,
                "run_id": args.run_id,
                "operation_id": args.expected_operation_id,
                "network_operation": "GET_ONLY",
            }))
            return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
