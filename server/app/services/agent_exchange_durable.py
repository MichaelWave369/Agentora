"""Durable advisory-only Commonline exchange inbox; trusted local adapter only.

No HTTP route, tool execution, Github writes or remote authentication.
The caller must independently authenticate the sender identity.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from app.services.agent_exchange import ExchangeHeld, ID_RE, parse_exchange


class DurableReviewInbox:
    """SQLite inbox with durable dedupe, contact policy, and view-only receipts."""

    def __init__(self, db_path: str | Path, *, contacts: dict[str, set[str]],
                 max_messages: int = 10000):
        if type(max_messages) is not int or not 1 <= max_messages <= 100000:
            raise ValueError("CAPACITY_INVALID")
        if not contacts or any(
            type(actor) is not str or ID_RE.fullmatch(actor) is None or
            type(peers) is not set or
            any(type(peer) is not str or ID_RE.fullmatch(peer) is None for peer in peers)
            for actor, peers in contacts.items()
        ):
            raise ValueError("CONTACTS_INVALID")
        self._contacts = {actor: frozenset(peers) for actor, peers in contacts.items()}
        self._max_messages = max_messages
        self.path = Path(db_path).expanduser()
        if str(db_path) == ":memory:" or self.path.is_symlink():
            raise ExchangeHeld("DB_PATH_UNSAFE")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink():
            raise ExchangeHeld("DB_PARENT_UNSAFE")
        if os.name == "posix" and self.path.parent.stat().st_mode & 0o002:
            raise ExchangeHeld("DB_PARENT_WORLD_WRITABLE")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        os.close(fd)
        if os.name == "posix" and self.path.stat().st_mode & 0o077:
            raise ExchangeHeld("DB_FILE_PERMISSIONS")
        with self._tx() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS exchange_messages(
                message_id TEXT PRIMARY KEY, payload_digest TEXT NOT NULL,
                thread_id TEXT NOT NULL, sender TEXT NOT NULL,
                recipient TEXT NOT NULL, kind TEXT NOT NULL,
                issued_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                summary TEXT NOT NULL, context_ref TEXT, source_sha TEXT,
                arrived_at TEXT NOT NULL, seen_at TEXT
            )""")
            db.execute("""CREATE INDEX IF NOT EXISTS exchange_inbox_recipient
                ON exchange_messages(recipient, seen_at, arrived_at, message_id)""")

    @contextmanager
    def _tx(self):
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

    def ingest(self, raw: dict, *, authenticated_sender: str,
               now: datetime | None = None) -> str:
        instant = now or datetime.now(timezone.utc)
        msg = parse_exchange(raw, now=instant)
        if msg.sender != authenticated_sender:
            raise ExchangeHeld("SENDER_NOT_AUTHENTICATED")
        if (msg.sender not in self._contacts or msg.recipient not in self._contacts
                or msg.recipient not in self._contacts[msg.sender]):
            raise ExchangeHeld("CONTACT_NOT_ALLOWED")
        digest = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False, allow_nan=False
                                           ).encode("utf-8")).hexdigest()
        with self._tx() as db:
            prior = db.execute("SELECT payload_digest FROM exchange_messages WHERE message_id=?",
                               (msg.message_id,)).fetchone()
            if prior:
                if prior["payload_digest"] != digest:
                    raise ExchangeHeld("MESSAGE_ID_COLLISION")
                return "REPLAY_IGNORED"
            if db.execute("SELECT COUNT(*) FROM exchange_messages").fetchone()[0] >= self._max_messages:
                raise ExchangeHeld("INBOX_CAPACITY_HELD")
            db.execute("""INSERT INTO exchange_messages (
                message_id,payload_digest,thread_id,sender,recipient,kind,
                issued_at,expires_at,summary,context_ref,source_sha,arrived_at,seen_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,NULL)""", (
                msg.message_id, digest, msg.thread_id, msg.sender, msg.recipient,
                msg.kind, msg.issued_at.isoformat(), msg.expires_at.isoformat(),
                msg.summary, msg.context_ref, msg.source_sha, instant.isoformat()))
        return "REVIEW_PENDING"

    def pending(self, recipient: str, *, limit: int = 100) -> list[dict]:
        if recipient not in self._contacts:
            raise ExchangeHeld("UNKNOWN_RECIPIENT")
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ExchangeHeld("LIMIT_INVALID")
        with self._tx() as db:
            rows = db.execute("""SELECT message_id,thread_id,sender,recipient,kind,
                summary,context_ref,source_sha,arrived_at
                FROM exchange_messages WHERE recipient=? AND seen_at IS NULL
                ORDER BY arrived_at,message_id LIMIT ?""", (recipient, limit)).fetchall()
            return [dict(row) | {"dispatch_authorized": False,
                                 "merge_authorized": False, "outcome_accepted": False}
                    for row in rows]

    def mark_seen(self, message_id: str, *, recipient: str,
                  now: datetime | None = None) -> str:
        """View receipt only; NEVER acceptance or task approval."""
        if recipient not in self._contacts:
            raise ExchangeHeld("UNKNOWN_RECIPIENT")
        if type(message_id) is not str or ID_RE.fullmatch(message_id) is None:
            raise ExchangeHeld("MESSAGE_ID_INVALID")
        instant = now or datetime.now(timezone.utc)
        if instant.tzinfo is None:
            raise ExchangeHeld("CLOCK_INVALID")
        with self._tx() as db:
            row = db.execute("SELECT recipient,seen_at FROM exchange_messages WHERE message_id=?",
                             (message_id,)).fetchone()
            if row is None or row["recipient"] != recipient:
                raise ExchangeHeld("MESSAGE_NOT_VISIBLE")
            if row["seen_at"]:
                return "ALREADY_SEEN"
            db.execute("UPDATE exchange_messages SET seen_at=? WHERE message_id=?",
                       (instant.isoformat(), message_id))
        return "SEEN_ONLY"

    @property
    def dispatch_authorized(self) -> bool:
        return False

    @property
    def merge_authorized(self) -> bool:
        return False
