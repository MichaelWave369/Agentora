"""Phi Desktop Bridge R8: local, privacy-minimal field-test ledger.

Operator reports are NOT external attestations, security certifications,
cryptographic evidence, or permissions for desktop execution. This module
never imports or invokes the desktop broker, network stack, or R0 CLI.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import sys
import time
from typing import Any

from app.services.desktop_bridge import DesktopBridgeError

RECEIPT_KEYS = frozenset({
    "schema", "receipt_id", "created_at", "probe",
    "broker_reports_click_disabled", "r6_transport_marker_observed",
    "transport_identity_cryptographically_attested", "labels_redacted",
    "observation_metadata_valid", "observations_checked",
    "distinct_snapshot_ids", "first_observation_target_count", "truncated",
    "user_task_verified", "cross_user_dacl_negative_test",
    "real_windows_desktop_compatibility", "independent_security_review",
    "autonomous_execution_authorized", "mutating_action_requested",
})
ID_RE = re.compile(r"[0-9a-f]{24}\Z")
FILE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.json\Z")
STATUS = frozenset({"observed", "issue", "inconclusive"})
ISSUES = frozenset({
    "none", "inaccessible-ui", "transport-failure",
    "unexpected-observation", "operator-interrupted", "other",
})
MAX_FILE = 4096


def _private_dir(path: Path) -> Path:
    path = Path(path).expanduser()
    if path.is_symlink():
        raise DesktopBridgeError("field_symlink_directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir() or path.is_symlink():
        raise DesktopBridgeError("field_insecure_directory")
    if os.name == "posix":
        st = path.stat()
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            raise DesktopBridgeError("field_insecure_directory")
    return path


def default_receipts_dir() -> Path:
    return Path.home() / ".agentora" / "field-trials"


def validate_receipt(value: Any) -> dict[str, Any]:
    """Exact R7 schema, fail closed if anything unknown could contain secrets."""
    if not isinstance(value, dict) or set(value) != RECEIPT_KEYS:
        raise DesktopBridgeError("field_receipt_schema_denied")
    if type(value["schema"]) is not int or value["schema"] != 1:
        raise DesktopBridgeError("field_receipt_schema_denied")
    if not isinstance(value["receipt_id"], str) or not ID_RE.fullmatch(value["receipt_id"]):
        raise DesktopBridgeError("field_receipt_schema_denied")
    stamp = value["created_at"]
    if not isinstance(stamp, str) or len(stamp) > 48:
        raise DesktopBridgeError("field_receipt_schema_denied")
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        raise DesktopBridgeError("field_receipt_schema_denied") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DesktopBridgeError("field_receipt_schema_denied")
    expected = {
        "probe": "r6_user_restricted_read_only_pipe",
        "broker_reports_click_disabled": True,
        "r6_transport_marker_observed": True,
        "transport_identity_cryptographically_attested": False,
        "labels_redacted": True,
        "observation_metadata_valid": True,
        "user_task_verified": False,
        "cross_user_dacl_negative_test": "NOT_PERFORMED",
        "real_windows_desktop_compatibility": "NOT_VERIFIED_BY_THIS_RECEIPT",
        "independent_security_review": "NOT_PERFORMED",
        "autonomous_execution_authorized": False,
        "mutating_action_requested": False,
    }
    for key, answer in expected.items():
        actual = value[key]
        if type(actual) is not type(answer) or actual != answer:
            raise DesktopBridgeError("field_receipt_claim_denied")
    n = value["observations_checked"]
    distinct = value["distinct_snapshot_ids"]
    if (type(n) is not int or n not in (1, 2)
            or (distinct is not None if n == 1 else distinct is not True)
            or type(value["first_observation_target_count"]) is not int
            or not 0 <= value["first_observation_target_count"] <= 100000
            or type(value["truncated"]) is not bool):
        raise DesktopBridgeError("field_receipt_schema_denied")
    # Only these fields may leave the parsed receipt and enter the local ledger.
    return {
        "receipt_id": value["receipt_id"],
        "receipt_created_at": parsed.astimezone(timezone.utc).isoformat(),
        "observations_checked": n,
        "first_observation_target_count": value["first_observation_target_count"],
        "truncated": value["truncated"],
    }


def read_receipt_data(path: Path) -> dict[str, Any]:
    """Read at most 4096 bytes with nofollow where supported, then validate."""
    path = Path(path)
    if path.is_symlink():
        raise DesktopBridgeError("field_receipt_file_denied")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise DesktopBridgeError("field_receipt_file_denied")
            data = stream.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise DesktopBridgeError("field_receipt_file_denied")
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        raise DesktopBridgeError("field_receipt_file_denied") from None
    validate_receipt(value)
    return value


def load_receipt(path: Path) -> dict[str, Any]:
    """Expose only the five allowed summary fields to the caller."""
    return validate_receipt(read_receipt_data(path))


def _json(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


class FieldLedger:
    """Local SQLite report journal. Neither signed nor tamper-resistant."""

    def __init__(self, path: Path):
        self.path = Path(path).expanduser()
        _private_dir(self.path.parent)
        if self.path.is_symlink():
            raise DesktopBridgeError("field_ledger_symlink_denied")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            st = self.path.lstat()
            if not stat.S_ISREG(st.st_mode):
                raise DesktopBridgeError("field_ledger_invalid_file")
            if os.name == "posix" and (st.st_uid != os.getuid() or st.st_mode & 0o077):
                raise DesktopBridgeError("field_ledger_insecure_file")
        else:
            os.close(fd)
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS field_reports ("
                "id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,"
                "record_json TEXT NOT NULL, recorded_at TEXT NOT NULL)"
            )
            db.commit()

    def _connect(self):
        return closing(sqlite3.connect(self.path, timeout=5.0))

    def record(self, receipt: dict[str, Any], *, status: str, issue: str) -> dict[str, Any]:
        if status not in STATUS or issue not in ISSUES:
            raise DesktopBridgeError("field_invalid_operator_status")
        if (status == "observed" and issue != "none"
                or status != "observed" and issue == "none"):
            raise DesktopBridgeError("field_invalid_operator_status")
        # validate_receipt always reconstructs the compact summary anew.
        safe = validate_receipt(receipt)
        record = {
            "schema": 1,
            "entry_id": secrets.token_hex(16),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "receipt": safe,
            "operator_reported_status": status,
            "operator_issue_category": issue,
            "operator_statement_independently_verified": False,
            "cross_account_denial_verified": False,
            "external_security_review_verified": False,
            "real_desktop_compatibility_certified": False,
            "execution_authorization": False,
            "autonomous_readiness": False,
            "source_signature_validated": False,
        }
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute(
                    "INSERT INTO field_reports (id,receipt_id,record_json,recorded_at)"
                    " VALUES (?,?,?,?)",
                    (record["entry_id"], safe["receipt_id"], _json(record),
                     record["recorded_at"]),
                )
                db.commit()
            except sqlite3.IntegrityError:
                raise DesktopBridgeError("field_duplicate_receipt") from None
        return record

    def reports(self, limit: int = 20) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DesktopBridgeError("field_invalid_limit")
        with self._connect() as db:
            rows = db.execute(
                "SELECT record_json FROM field_reports ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def readiness(self) -> dict[str, Any]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT record_json FROM field_reports"
            ).fetchall()
        reports = [json.loads(row[0]) for row in rows]
        counts = {s: sum(r["operator_reported_status"] == s for r in reports)
                  for s in sorted(STATUS)}
        return {
            "schema": 1,
            "local_operator_entries": len(reports),
            "reported_outcomes": counts,
            "field_observation_claims_self_reported_only": True,
            "cross_account_denial_verified": False,
            "external_security_review_verified": False,
            "same_user_process_isolation_verified": False,
            "actual_desktop_compatibility_certified": False,
            "ready_for_autonomous_desktop_actions": False,
            "ledger_cryptographically_attested": False,
            "no_cloud_upload_performed_by_this_tool": True,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phi R8 local operator field journal, never an execution grant."
    )
    parser.add_argument("--db", type=Path,
                        default=Path.home() / ".agentora" / "field-trials" / "field-journal.db")
    sub = parser.add_subparsers(dest="mode", required=True)
    rec = sub.add_parser("record", help="Manually witness one R7 redacted receipt")
    rec.add_argument("--receipt", required=True, help="Filename inside local field-trials folder")
    rec.add_argument("--status", choices=sorted(STATUS), required=True)
    rec.add_argument("--issue", choices=sorted(ISSUES), default="none")
    sub.add_parser("readiness", help="Local non-certifying readiness report")
    sub.add_parser("recent", help="Recent local self-reported trial entries")
    args = parser.parse_args(argv)
    try:
        if args.mode == "record":
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise DesktopBridgeError("field_interactive_operator_required")
            if not FILE_RE.fullmatch(args.receipt) or args.receipt in (".", ".."):
                raise DesktopBridgeError("field_receipt_filename_denied")
            safe = load_receipt(_private_dir(default_receipts_dir()) / args.receipt)
            print(
                "LOCAL OPERATOR SELF-REPORT. No signatures, no task verification, "
                "no action permissions."
            )
            print("Receipt ID:", safe["receipt_id"])
            print("Observed snapshots:", safe["observations_checked"])
            print("Your reported status:", args.status, "| issue:", args.issue)
            challenge = "RECORD " + secrets.token_hex(4)
            if input("Type exactly " + challenge + " to record this self-report: ").strip() != challenge:
                raise DesktopBridgeError("field_operator_cancelled")
            # Re-read after consent to reject a swapped or changed receipt.
            path = default_receipts_dir() / args.receipt
            latest_data = read_receipt_data(path)
            if validate_receipt(latest_data) != safe:
                raise DesktopBridgeError("field_receipt_changed")
            record = FieldLedger(args.db).record(
                latest_data, status=args.status, issue=args.issue,
            )
            print("Recorded local self-report:", record["entry_id"])
            print("Autonomous execution authorization: FALSE")
            return 0
        ledger = FieldLedger(args.db)
        output = ledger.readiness() if args.mode == "readiness" else ledger.reports()
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except DesktopBridgeError as exc:
        print("Field journal stopped: " + exc.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
