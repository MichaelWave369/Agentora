"""Agentora Fleet R0.4: local atomic reservation leases, NOT job dispatch.

No subprocesses, GitHub writes, agent execution, approval, or merge authority.
SQLite's single-writer transaction coordinates processes sharing one filesystem.
It is NOT a distributed lock across independent GitHub Actions runners.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
import tempfile
import time

LEASE_SCHEMA = "agentora.fleet.local-reservation.v0.4"
INTAKE_SCHEMA = "agentora.fleet.verification-intake.v0.3"
OWNER = "MichaelWave369"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
REPO_NAME = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
WORKER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
MAX_INPUT_BYTES = 131072
MIN_TTL = 30
MAX_TTL = 1800


class LeaseHeld(Exception):
    """No reservation, renewal, or release was authorized."""


def require(condition, code):
    if not condition:
        raise LeaseHeld(code)


def epoch_ms(now_ms=None):
    instant = int(time.time() * 1000) if now_ms is None else now_ms
    require(type(instant) is int and 0 <= instant < 10**15, "INVALID_CLOCK")
    return instant


def ttl_ms(ttl_seconds):
    require(type(ttl_seconds) is int and MIN_TTL <= ttl_seconds <= MAX_TTL,
            "INVALID_TTL")
    return ttl_seconds * 1000


def valid_repo(name):
    return (isinstance(name, str) and name.startswith(OWNER + "/") and
            bool(REPO_NAME.fullmatch(name[len(OWNER) + 1:])) and
            name[len(OWNER) + 1:] not in (".", ".."))


def validate_intake(intake):
    """Validate R0.3's held receipt *shape*, not sender authenticity.

    An intake is untrusted source metadata, never execution authorization.
    """
    require(isinstance(intake, dict) and intake.get("schema") == INTAKE_SCHEMA,
            "INTAKE_SCHEMA_INVALID")
    require(intake.get("state") == "HELD_FOR_OPERATOR_REVIEW" and
            intake.get("owner") == OWNER and valid_repo(intake.get("repository")),
            "INTAKE_IDENTITY_INVALID")
    repo_id = intake.get("repository_id")
    require(type(repo_id) is int and 0 < repo_id <= 9007199254740991,
            "INTAKE_REPO_ID_INVALID")
    require(isinstance(intake.get("source_sha"), str) and
            SHA40.fullmatch(intake["source_sha"]) is not None and
            isinstance(intake.get("request_sha256"), str) and
            SHA64.fullmatch(intake["request_sha256"]) is not None,
            "INTAKE_REVISION_OR_DIGEST_INVALID")
    for field in ("verified_complete", "operator_approved", "dispatch_authorized",
                  "merge_authorized", "head_revalidated_by_agentora",
                  "digest_is_authentication"):
        require(intake.get(field) is False, "INTAKE_AUTHORITY_CLAIM_REJECTED")
    require(type(intake.get("independent_checks_run")) is int and
            intake["independent_checks_run"] == 0 and
            isinstance(intake.get("checks"), list) and intake["checks"] and
            all(isinstance(c, dict) and c.get("verification_state") == "NOT_RUN" and
                c.get("evidence_receipt") is None for c in intake["checks"]),
            "INTAKE_VERIFICATION_CLAIM_REJECTED")
    return {key: intake[key] for key in
            ("repository", "repository_id", "source_sha", "request_sha256")}


def load_intake(path):
    require(path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= MAX_INPUT_BYTES, "INTAKE_FILE_INVALID")
    try:
        content = path.read_bytes()
        require(len(content) <= MAX_INPUT_BYTES, "INTAKE_FILE_INVALID")
        intake = json.loads(content.decode("utf-8"))
        validate_intake(intake)
        return intake
    except (UnicodeError, ValueError):
        raise LeaseHeld("INTAKE_JSON_INVALID") from None


class LeaseLedger:
    def __init__(self, db_path):
        self.path = Path(db_path)
        require(str(self.path) != ":memory:", "PERSISTENT_DB_REQUIRED")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(not self.path.is_symlink(), "DB_SYMLINK_REJECTED")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        os.close(fd)
        if os.name == "posix":
            require((self.path.stat().st_mode & 0o077) == 0,
                    "DB_PERMISSIONS_UNSAFE")
        with self._connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("""CREATE TABLE IF NOT EXISTS reservations (
                repository TEXT PRIMARY KEY, repository_id INTEGER NOT NULL,
                source_sha TEXT NOT NULL, request_sha256 TEXT NOT NULL,
                worker TEXT NOT NULL, token_digest TEXT NOT NULL,
                generation INTEGER NOT NULL, state TEXT NOT NULL,
                created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL,
                expires_ms INTEGER NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS lease_events (
                event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                repository TEXT NOT NULL, generation INTEGER NOT NULL,
                event_type TEXT NOT NULL, event_ms INTEGER NOT NULL,
                worker TEXT NOT NULL, source_sha TEXT NOT NULL
            )""")
            db.commit()

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(str(self.path), timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=5000")
        try:
            yield db
        finally:
            db.close()

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise

    @staticmethod
    def _event(db, row, event_type, now):
        db.execute("""INSERT INTO lease_events
            (repository,generation,event_type,event_ms,worker,source_sha)
            VALUES (?,?,?,?,?,?)""", (row["repository"], row["generation"],
            event_type, now, row["worker"], row["source_sha"]))

    def reserve(self, intake, worker, ttl_seconds=300, now_ms=None):
        item = validate_intake(intake)
        require(isinstance(worker, str) and WORKER.fullmatch(worker) is not None,
                "WORKER_INVALID")
        now = epoch_ms(now_ms)
        duration = ttl_ms(ttl_seconds)
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("ascii")).hexdigest()
        with self._transaction() as db:
            previous = db.execute("SELECT * FROM reservations WHERE repository=?",
                                  (item["repository"],)).fetchone()
            if previous and previous["state"] == "RESERVED" and previous["expires_ms"] > now:
                raise LeaseHeld("REPO_ALREADY_RESERVED")
            generation = previous["generation"] + 1 if previous else 1
            row = {**item, "worker": worker, "generation": generation,
                   "created_ms": now, "updated_ms": now, "expires_ms": now + duration,
                   "state": "RESERVED"}
            db.execute("""INSERT INTO reservations
                (repository,repository_id,source_sha,request_sha256,worker,
                 token_digest,generation,state,created_ms,updated_ms,expires_ms)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(repository) DO UPDATE SET
                  repository_id=excluded.repository_id,
                  source_sha=excluded.source_sha,
                  request_sha256=excluded.request_sha256,
                  worker=excluded.worker,
                  token_digest=excluded.token_digest,
                  generation=excluded.generation,
                  state=excluded.state,
                  created_ms=excluded.created_ms,
                  updated_ms=excluded.updated_ms,
                  expires_ms=excluded.expires_ms""",
                (row["repository"], row["repository_id"], row["source_sha"],
                 row["request_sha256"], worker, digest, generation, "RESERVED",
                 now, now, now + duration))
            self._event(db, row, "RESERVED_AFTER_EXPIRY" if previous and
                        previous["state"] == "RESERVED" else "RESERVED", now)
        # Token is never placed into the DB, log, or public status view.
        return {"schema": LEASE_SCHEMA, **row, "token": token,
                "execution_authorized": False, "merge_authorized": False,
                "verified_complete": False}

    def _check_owned(self, db, capability, now):
        require(isinstance(capability, dict) and
                capability.get("schema") == LEASE_SCHEMA and
                valid_repo(capability.get("repository")) and
                type(capability.get("generation")) is int and
                capability["generation"] > 0 and
                isinstance(capability.get("worker"), str) and
                isinstance(capability.get("token"), str) and
                len(capability["token"]) <= 128,
                "LEASE_CAPABILITY_INVALID")
        row = db.execute("SELECT * FROM reservations WHERE repository=?",
                         (capability["repository"],)).fetchone()
        require(row is not None and row["state"] == "RESERVED" and
                row["expires_ms"] > now and
                row["generation"] == capability["generation"] and
                row["worker"] == capability["worker"] and
                row["source_sha"] == capability.get("source_sha") and
                row["repository_id"] == capability.get("repository_id") and
                row["request_sha256"] == capability.get("request_sha256") and
                secrets.compare_digest(row["token_digest"],
                  hashlib.sha256(capability["token"].encode("utf-8")).hexdigest()),
                "LEASE_EXPIRED_OR_FENCED")
        return row

    def renew(self, capability, ttl_seconds=300, now_ms=None):
        now = epoch_ms(now_ms)
        duration = ttl_ms(ttl_seconds)
        with self._transaction() as db:
            row = self._check_owned(db, capability, now)
            db.execute("UPDATE reservations SET updated_ms=?,expires_ms=? WHERE repository=?",
                       (now, now + duration, row["repository"]))
            self._event(db, row, "RENEWED", now)
        return {**capability, "updated_ms": now, "expires_ms": now + duration}

    def release(self, capability, now_ms=None):
        now = epoch_ms(now_ms)
        with self._transaction() as db:
            row = self._check_owned(db, capability, now)
            db.execute("""UPDATE reservations SET state='RELEASED',updated_ms=?,
                         expires_ms=? WHERE repository=?""",
                       (now, now, row["repository"]))
            self._event(db, row, "RELEASED_NOT_COMPLETED", now)
        return {"repository": row["repository"], "generation": row["generation"],
                "state": "RELEASED_NOT_COMPLETED", "execution_authorized": False,
                "merge_authorized": False, "verified_complete": False}

    def status(self, now_ms=None):
        now = epoch_ms(now_ms)
        with self._connection() as db:
            rows = db.execute("""SELECT repository,repository_id,source_sha,
                request_sha256,worker,generation,state,created_ms,updated_ms,
                expires_ms FROM reservations ORDER BY repository""").fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["state"] = ("EXPIRED" if row["state"] == "RESERVED" and
                             row["expires_ms"] <= now else row["state"])
            item.update(execution_authorized=False, merge_authorized=False,
                        verified_complete=False)
            items.append(item)
        return {"schema": "agentora.fleet.local-lease-status.v0.4",
                "scope": "SINGLE_SHARED_SQLITE_FILE_NOT_DISTRIBUTED",
                "reservations": items, "active_reservations": sum(
                    x["state"] == "RESERVED" for x in items),
                "actual_jobs_dispatched": 0, "verified_complete": 0,
                "merge_authorized": False}

    def events(self):
        with self._connection() as db:
            return [dict(x) for x in db.execute("""SELECT repository,generation,
                event_type,event_ms,worker,source_sha FROM lease_events
                ORDER BY event_id""").fetchall()]


def load_capability(path):
    require(path.is_file() and not path.is_symlink() and
            0 < path.stat().st_size <= 8192, "LEASE_FILE_INVALID")
    # A capability contains a secret. Decline world/group-readable files on Unix.
    if os.name == "posix":
        require((path.stat().st_mode & 0o077) == 0, "LEASE_FILE_PERMISSIONS_UNSAFE")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, ValueError):
        raise LeaseHeld("LEASE_FILE_JSON_INVALID") from None


def save_capability(path, data, exclusive=False):
    """Keep the bearer capability private; renewals use atomic replacement."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    if exclusive:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(path, 0o600)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return
    require(path.is_file() and not path.is_symlink(), "LEASE_FILE_MISSING")
    if os.name == "posix":
        require((path.stat().st_mode & 0o077) == 0, "LEASE_FILE_PERMISSIONS_UNSAFE")
    fd, temporary = tempfile.mkstemp(prefix=".fleet-r04-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        # The capability is not shared across processes; replacement is atomic
        # but does not grant any new execution authority.
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    reserve = sub.add_parser("reserve", help="Local reservation only; never run a job")
    reserve.add_argument("--intake", required=True, type=Path)
    reserve.add_argument("--worker", required=True)
    reserve.add_argument("--lease-file", required=True, type=Path)
    for name in ("renew", "release"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--lease-file", required=True, type=Path)
    for name in ("reserve", "renew"):
        cmd = reserve if name == "reserve" else sub.choices[name]
        cmd.add_argument("--ttl", type=int, default=300)
    sub.add_parser("status", help="Safe status: no capability tokens")
    parser.add_argument("--db", required=True, type=Path,
                        help="One local SQLite file shared by the participating processes")
    args = parser.parse_args(argv)
    try:
        ledger = LeaseLedger(args.db)
        if args.action == "reserve":
            require(not args.lease_file.exists() and not args.lease_file.is_symlink(),
                    "LEASE_FILE_ALREADY_EXISTS")
            intake = load_intake(args.intake)
            # validate before acquiring a transactional reservation
            token = ledger.reserve(intake, args.worker, args.ttl)
            try:
                save_capability(args.lease_file, token, exclusive=True)
            except BaseException:
                ledger.release(token)
                raise
            result = {"state": "RESERVED_FOR_COORDINATION_ONLY",
                      "repository": token["repository"],
                      "generation": token["generation"],
                      "execution_authorized": False, "merge_authorized": False}
        elif args.action == "renew":
            token = load_capability(args.lease_file)
            renewed = ledger.renew(token, args.ttl)
            save_capability(args.lease_file, renewed)
            result = {"state": "RENEWED", "repository": renewed["repository"],
                      "generation": renewed["generation"],
                      "execution_authorized": False, "merge_authorized": False}
        elif args.action == "release":
            token = load_capability(args.lease_file)
            result = ledger.release(token)
            args.lease_file.unlink()
        else:
            result = ledger.status()
        print(json.dumps(result, sort_keys=True))
        return 0
    except (LeaseHeld, OSError, sqlite3.Error) as exc:
        print("FLEET_R04_HELD " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
