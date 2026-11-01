"""Phi Desktop Bridge R2: local proposal inbox, with no desktop execution path.

Untrusted agent plans can be recorded for human review. A review NEVER triggers
agent-desktop, the R1 broker, Agentora's actions API, or a network request.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
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
from typing import Any, Callable, Iterator

SCHEMA = 1
ID_RE = re.compile(r"[0-9a-f]{32}\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_RE = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
CORRELATION_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,79}\Z")
SNAPSHOT_REF_RE = re.compile(r"@s[A-Za-z0-9]+:e[0-9]+")
VALID_OPS = frozenset({"observe", "click"})
VALID_STATES = frozenset({"pending", "reviewed", "rejected", "expired"})
MAX_PENDING = 100


class ProposalError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _clean_text(value: str, *, limit: int, field: str, required: bool) -> str:
    if not isinstance(value, str):
        raise ProposalError("invalid_" + field)
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise ProposalError("invalid_" + field)
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ProposalError("invalid_" + field)
    return value


def normalize_proposal(
    *,
    source: str,
    app: str,
    operation: str,
    reason: str,
    target_hint: str = "",
    correlation_id: str = "",
) -> dict[str, Any]:
    """A deliberately narrow allowlist. Labels and hints are not authority."""
    if not isinstance(source, str) or not SOURCE_RE.fullmatch(source):
        raise ProposalError("invalid_source")
    app = _clean_text(app, limit=80, field="app", required=True)
    if operation not in VALID_OPS:
        raise ProposalError("invalid_operation")
    reason = _clean_text(reason, limit=240, field="reason", required=True)
    target_hint = _clean_text(target_hint, limit=100, field="target_hint", required=operation == "click")
    if SNAPSHOT_REF_RE.search(target_hint):
        raise ProposalError("stale_snapshot_ref_forbidden")
    if correlation_id and (
        not isinstance(correlation_id, str) or not CORRELATION_RE.fullmatch(correlation_id)
    ):
        raise ProposalError("invalid_correlation_id")
    if not isinstance(correlation_id, str):
        raise ProposalError("invalid_correlation_id")
    return {
        "schema": SCHEMA,
        "source": source,
        "app": app,
        "operation": operation,
        "reason": reason,
        "target_hint": target_hint,
        "correlation_id": correlation_id,
    }


def _canonical(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _digest(data: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(data).encode("ascii")).hexdigest()


class ProposalInbox:
    """SQLite inbox. Writes are local, transactional and never executable."""

    def __init__(self, db_path: Path, clock: Callable[[], float] = time.time):
        self.path = Path(db_path).expanduser()
        self.clock = clock
        self._init_file()
        with self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS desktop_proposals (
                    id TEXT PRIMARY KEY,
                    digest TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','reviewed','rejected','expired')),
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    reviewed_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS desktop_proposal_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    proposal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS proposal_inbox_status
                    ON desktop_proposals(status, created_at);
                """
            )

    def _init_file(self) -> None:
        folder = self.path.parent
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name == "posix":
            mode = folder.stat().st_mode
            if mode & 0o077:
                raise ProposalError("insecure_inbox_directory")
        if self.path.is_symlink():
            raise ProposalError("symlink_inbox_forbidden")
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        except FileExistsError:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise ProposalError("invalid_inbox_file")
            if os.name == "posix" and info.st_mode & 0o077:
                raise ProposalError("insecure_inbox_file")
        else:
            os.close(fd)
        # OS ACL isolation is NOT asserted on Windows; see threat model.

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=5.0)) as con:
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA busy_timeout=5000")
            yield con

    def _expire(self, con: sqlite3.Connection, now: int) -> None:
        expired = con.execute(
            "SELECT id FROM desktop_proposals WHERE status = 'pending' AND expires_at <= ?",
            (now,),
        ).fetchall()
        if expired:
            con.execute(
                "UPDATE desktop_proposals SET status = 'expired' "
                "WHERE status = 'pending' AND expires_at <= ?",
                (now,),
            )
            con.executemany(
                "INSERT INTO desktop_proposal_events(proposal_id,status,at) VALUES (?, 'expired', ?)",
                [(r["id"], now) for r in expired],
            )

    def submit(
        self,
        *,
        source: str,
        app: str,
        operation: str,
        reason: str,
        target_hint: str = "",
        correlation_id: str = "",
        ttl_seconds: int = 900,
    ) -> dict[str, Any]:
        if type(ttl_seconds) is not int or not 30 <= ttl_seconds <= 3600:
            raise ProposalError("invalid_ttl")
        payload = normalize_proposal(
            source=source, app=app, operation=operation,
            reason=reason, target_hint=target_hint,
            correlation_id=correlation_id,
        )
        now = int(self.clock())
        item_id = secrets.token_hex(16)
        digest = _digest(payload)
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._expire(con, now)
            count = con.execute(
                "SELECT COUNT(*) AS n FROM desktop_proposals WHERE status='pending'"
            ).fetchone()["n"]
            if count >= MAX_PENDING:
                raise ProposalError("inbox_pending_limit")
            con.execute(
                "INSERT INTO desktop_proposals(id,digest,payload,status,created_at,expires_at) "
                "VALUES (?,?,?,'pending',?,?)",
                (item_id, digest, _canonical(payload), now, now + ttl_seconds),
            )
            con.execute(
                "INSERT INTO desktop_proposal_events(proposal_id,status,at) VALUES (?, 'pending', ?)",
                (item_id, now),
            )
            con.commit()
        return {"id": item_id, "digest": digest, "status": "pending",
                "created_at": now, "expires_at": now + ttl_seconds, "proposal": payload}

    def _read_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "digest": row["digest"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "reviewed_at": row["reviewed_at"],
            "proposal": json.loads(row["payload"]),
        }

    def get(self, item_id: str) -> dict[str, Any]:
        if not isinstance(item_id, str) or not ID_RE.fullmatch(item_id):
            raise ProposalError("invalid_id")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._expire(con, int(self.clock()))
            row = con.execute(
                "SELECT * FROM desktop_proposals WHERE id = ?", (item_id,)
            ).fetchone()
            con.commit()
        if row is None:
            raise ProposalError("proposal_not_found")
        record = self._read_row(row)
        if _digest(record["proposal"]) != record["digest"]:
            raise ProposalError("proposal_integrity_failed")
        return record

    def list(self, *, status: str = "pending", limit: int = 50) -> list[dict[str, Any]]:
        if status not in VALID_STATES | {"all"}:
            raise ProposalError("invalid_status")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ProposalError("invalid_limit")
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._expire(con, int(self.clock()))
            if status == "all":
                rows = con.execute(
                    "SELECT * FROM desktop_proposals ORDER BY created_at DESC, id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM desktop_proposals WHERE status = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            con.commit()
        return [self._read_row(row) for row in rows]

    def review(self, item_id: str, expected_digest: str, decision: str) -> dict[str, Any]:
        """Only metadata transition; cannot grant desktop authority or execute."""
        if not isinstance(item_id, str) or not ID_RE.fullmatch(item_id):
            raise ProposalError("invalid_id")
        if not isinstance(expected_digest, str) or not DIGEST_RE.fullmatch(expected_digest):
            raise ProposalError("invalid_digest")
        if decision not in {"reviewed", "rejected"}:
            raise ProposalError("invalid_decision")
        now = int(self.clock())
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            self._expire(con, now)
            cursor = con.execute(
                "UPDATE desktop_proposals SET status=?,reviewed_at=? "
                "WHERE id=? AND digest=? AND status='pending' AND expires_at>?",
                (decision, now, item_id, expected_digest, now),
            )
            if cursor.rowcount != 1:
                raise ProposalError("proposal_stale_or_not_pending")
            con.execute(
                "INSERT INTO desktop_proposal_events(proposal_id,status,at) VALUES (?,?,?)",
                (item_id, decision, now),
            )
            con.commit()
        return self.get(item_id)

    def handoff(self, item_id: str) -> str:
        item = self.get(item_id)
        if item["status"] != "reviewed":
            raise ProposalError("manual_handoff_requires_review")
        p = item["proposal"]
        if p["operation"] == "observe":
            action = "Request a FRESH observation of that same app from the local R1 broker."
        else:
            action = (
                "Request a FRESH observation in the local broker; identify the "
                "current clickable ref by checking the actual UI; then make a "
                "separate, one-use, human-approved click in the broker's terminal."
            )
        return (
            f"Proposal {item['id']} reviewed for MANUAL FOLLOW-UP ONLY.\n"
            f"Application: {p['app']}\nIntent: {p['operation']}\n"
            f"Target hint (untrusted): {p['target_hint']}\n"
            f"{action}\nNo command was executed and no broker token was issued."
        )

    def events(self, item_id: str) -> list[dict[str, Any]]:
        self.get(item_id)
        with self._connect() as con:
            rows = con.execute(
                "SELECT status,at FROM desktop_proposal_events WHERE proposal_id=? ORDER BY seq",
                (item_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def submit_agentora_proposal(
    inbox: ProposalInbox, *,
    run_id: int, app: str, operation: str, reason: str, target_hint: str = ""
) -> dict[str, Any]:
    """Pure orchestration adapter. No ActionRequest approval or broker access."""
    if type(run_id) is not int or run_id < 0:
        raise ProposalError("invalid_run_id")
    return inbox.submit(
        source="agentora", app=app, operation=operation,
        reason=reason, target_hint=target_hint,
        correlation_id=f"run:{run_id}",
    )


def _time(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def _display(item: dict[str, Any]) -> None:
    p = item["proposal"]
    print(f"ID: {item['id']}")
    print(f"Status: {item['status']}")
    print(f"Source label (untrusted): {p['source']}")
    print(f"App: {p['app']} | Requested: {p['operation']}")
    print(f"Intent: {p['reason']}")
    if p["target_hint"]:
        print(f"Target hint (untrusted): {p['target_hint']}")
    print(f"Expires: {_time(item['expires_at'])}")
    print(f"Digest: {item['digest']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phi Desktop proposal inbox; NO desktop execution")
    parser.add_argument("--db", type=Path, default=Path.home() / ".agentora" / "desktop-inbox.db")
    sub = parser.add_subparsers(dest="cmd", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("--source", default="manual")
    submit.add_argument("--app", required=True)
    submit.add_argument("--op", choices=sorted(VALID_OPS), required=True)
    submit.add_argument("--reason")
    submit.add_argument("--target-hint", default="")
    submit.add_argument("--correlation-id", default="")
    submit.add_argument("--ttl", type=int, default=900)
    listed = sub.add_parser("list")
    listed.add_argument("--status", choices=sorted(VALID_STATES | {"all"}), default="pending")
    listed.add_argument("--limit", type=int, default=50)
    for name in ("show", "review", "handoff"):
        p = sub.add_parser(name)
        p.add_argument("id")
        if name == "review":
            p.add_argument("--decision", choices=["reviewed", "rejected"], required=True)
    args = parser.parse_args(argv)
    try:
        inbox = ProposalInbox(args.db)
        if args.cmd == "submit":
            if args.reason is None and not sys.stdin.isatty():
                raise ProposalError("reason_required")
            reason = args.reason if args.reason is not None else input("Reason (no private data): ")
            item = inbox.submit(
                source=args.source, app=args.app, operation=args.op,
                reason=reason, target_hint=args.target_hint,
                correlation_id=args.correlation_id, ttl_seconds=args.ttl,
            )
            print(f"Proposal queued locally: {item['id']} (expires {_time(item['expires_at'])})")
        elif args.cmd == "list":
            for item in inbox.list(status=args.status, limit=args.limit):
                print(
                    f"{item['id']} {item['status']} {item['proposal']['operation']} "
                    f"{item['proposal']['app']} (expires {_time(item['expires_at'])})"
                )
        elif args.cmd == "show":
            _display(inbox.get(args.id))
        elif args.cmd == "handoff":
            print(inbox.handoff(args.id))
        elif args.cmd == "review":
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                raise ProposalError("interactive_operator_required")
            item = inbox.get(args.id)
            if item["status"] != "pending":
                raise ProposalError("proposal_stale_or_not_pending")
            _display(item)
            challenge = "REVIEW " + secrets.token_hex(4)
            if input(f"Type {challenge} to mark as {args.decision}: ").strip() != challenge:
                raise ProposalError("review_cancelled")
            result = inbox.review(args.id, item["digest"], args.decision)
            print(f"Recorded: {result['status']}. No desktop action was performed.")
        return 0
    except ProposalError as exc:
        print(f"Desktop inbox stopped: {exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
