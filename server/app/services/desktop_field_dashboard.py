"""Phi Desktop Bridge R9: read-only operator readiness from the local R8 journal.

Not a signature, an independent test, or permission for desktop execution.
This adapter never invokes desktop actions and cannot create the journal.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Any
from urllib.parse import quote

MAX_RECORD = 8192
MAX_PREVIEW = 12
OUTCOMES = frozenset({"observed", "issue", "inconclusive"})
ISSUES = frozenset({
    "none", "inaccessible-ui", "transport-failure",
    "unexpected-observation", "operator-interrupted", "other",
})
UNVERIFIED = (
    "Real Windows desktop compatibility",
    "Cross-account named-pipe denial",
    "Independent security review",
    "Same-user process isolation",
    "Actual user task completion",
)


def _empty(reason: str) -> dict[str, Any]:
    return {
        "schema": 1, "source": "local_operator_self_reports",
        "availability": reason, "total_self_reports": 0,
        "recent_self_reports": [], "rejected_preview_entries": 0,
        "not_independently_verified": list(UNVERIFIED),
        "source_integrity_verified": False,
        "windows_file_acl_verified": False, "task_verified": False,
        "execution_authorized": False, "autonomous_desktop_ready": False,
    }


def _preflight(path: Path) -> str:
    if not path.parent.exists() or not path.exists():
        return "not_recorded"
    try:
        if path.parent.is_symlink() or path.is_symlink():
            return "unavailable_or_insecure"
        parent, file = path.parent.stat(), path.stat()
        if not stat.S_ISDIR(parent.st_mode) or not stat.S_ISREG(file.st_mode):
            return "unavailable_or_insecure"
        if os.name == "posix":
            if (parent.st_uid != os.getuid() or file.st_uid != os.getuid()
                    or parent.st_mode & 0o077 or file.st_mode & 0o077):
                return "unavailable_or_insecure"
    except OSError:
        return "unavailable_or_insecure"
    return "available"


def _redacted_entry(raw: str) -> dict[str, object] | None:
    if not isinstance(raw, str) or len(raw) > MAX_RECORD:
        return None
    try:
        row = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(row, dict) or type(row.get("schema")) is not int or row["schema"] != 1:
        return None
    status, issue, when = (
        row.get("operator_reported_status"),
        row.get("operator_issue_category"),
        row.get("recorded_at"),
    )
    if (not isinstance(status, str) or status not in OUTCOMES
            or not isinstance(issue, str) or issue not in ISSUES
            or (status == "observed" and issue != "none")
            or (status != "observed" and issue == "none")
            or not isinstance(when, str) or len(when) > 48):
        return None
    try:
        stamp = datetime.fromisoformat(when)
    except ValueError:
        return None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        return None
    if any(row.get(k) is not False for k in (
        "execution_authorization", "autonomous_readiness",
        "operator_statement_independently_verified", "source_signature_validated",
    )):
        return None
    receipt = row.get("receipt")
    if (not isinstance(receipt, dict)
            or type(receipt.get("observations_checked")) is not int
            or receipt["observations_checked"] not in (1, 2)):
        return None
    return {
        "time": stamp.isoformat(timespec="seconds"),
        "reported_outcome": status,
        "issue_category": issue,
        "observation_count": receipt["observations_checked"],
        "witness": "operator_self_report_only",
    }


class FieldReadinessDashboard:
    """Reads a bounded preview via SQLite URI mode=ro; never mutates records."""

    def __init__(self, db: Path | None = None):
        self.db = Path(db).expanduser() if db is not None else (
            Path.home() / ".agentora" / "field-trials" / "field-journal.db"
        )

    def snapshot(self) -> dict[str, Any]:
        state = _preflight(self.db)
        result = _empty(state)
        if state != "available":
            return result
        uri = "file:" + quote(self.db.resolve().as_posix(), safe="/:") + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as conn:
                conn.execute("PRAGMA query_only=ON")
                count = conn.execute("SELECT COUNT(*) FROM field_reports").fetchone()[0]
                rows = conn.execute(
                    "SELECT record_json FROM field_reports ORDER BY rowid DESC LIMIT ?",
                    (MAX_PREVIEW,),
                ).fetchall()
        except (sqlite3.DatabaseError, OSError):
            return _empty("unavailable_or_insecure")
        valid = []
        invalid = 0
        for (raw,) in rows:
            entry = _redacted_entry(raw)
            if entry is None:
                invalid += 1
            else:
                valid.append(entry)
        result.update({
            "total_self_reports": count,
            "recent_self_reports": valid,
            "rejected_preview_entries": invalid,
        })
        return result


def render_readiness(snapshot: dict[str, Any]) -> str:
    """Plain text only, never an execution decision or certificate."""
    lines = [
        "PHI FIELD READINESS | READ ONLY | OPERATOR SELF-REPORTS",
        "",
        "Ledger: " + snapshot["availability"],
        "Operator reports: " + str(snapshot["total_self_reports"]),
        "Invalid previews: " + str(snapshot["rejected_preview_entries"]),
        "",
        "UNVERIFIED REQUIREMENTS",
    ]
    lines.extend("  NOT VERIFIED | " + item
                 for item in snapshot["not_independently_verified"])
    lines += [
        "",
        "Autonomous desktop control: NOT AUTHORIZED",
        "Task completion: NOT VERIFIED",
        "Ledger integrity: NOT VERIFIED",
        "Windows journal ACL: NOT VERIFIED",
        "",
        "RECENT SELF-REPORTS | NOT INDEPENDENT EVIDENCE",
    ]
    if not snapshot["recent_self_reports"]:
        lines.append("  No local operator reports available")
    else:
        for item in snapshot["recent_self_reports"]:
            lines.append(
                f"  {item['time']} | reported {item['reported_outcome']} | "
                f"{item['issue_category']} | {item['observation_count']} observation(s)"
            )
    lines += [
        "",
        "No proposal approval, action, broker call, or access permission",
        "can be granted by this panel.",
    ]
    return "\n".join(lines)
