"""Durable, advisory-only repository stewards for RepoNerve R1 observations.

One logical steward per immutable GitHub ID; zero agent execution, GitHub
writes, approvals, merges, installations or claims of product verification.
SQLite transactions coordinate concurrent *local* planning processes only.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

SOURCE_SCHEMA = "phireponerve.agentora.public-observations.v1"
EXPORT_SCHEMA = "agentora.fleet.steward-advisory.v1"
OWNER = "MichaelWave369"
SOURCE = "PHIREPONERVE_LOCAL_R1"
ALLOWED_EVENTS = {
    "first_observed", "visible_again", "renamed", "archival_changed",
    "default_branch_changed", "push_activity_observed",
}
NAME_RE = re.compile(r"MichaelWave369/[A-Za-z0-9_.-]{1,100}\Z")
REQUEST_RE = re.compile(r"[A-Za-z0-9_.-]{1,80}\Z")
SOURCE_KEYS = {
    "schema", "owner", "scope", "source", "source_scan_id", "observed_at",
    "public_repo_count", "repositories", "recent_events", "source_only",
    "dispatch_authorized", "merge_authorized", "verified_complete",
}
REPO_KEYS = {"github_id", "full_name", "archived", "source_only", "verified_complete"}
EVENT_KEYS = {"id", "github_id", "full_name", "event_type", "observed_at"}
MAX_ROWS = 10000
MAX_INPUT_BYTES = 1024 * 1024


class StewardHeld(ValueError):
    """Input, persistence or advisory planning did not meet the contract."""


def require(ok, code):
    if not ok:
        raise StewardHeld(code)


def _int(value, minimum=1):
    return type(value) is int and minimum <= value <= 9007199254740991


def _timestamp(raw, now):
    require(isinstance(raw, str) and len(raw) <= 48, "TIME_INVALID")
    try:
        instant = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise StewardHeld("TIME_INVALID") from None
    require(instant.tzinfo is not None and -300 <= (now - instant).total_seconds() <= 36 * 3600,
            "TIME_STALE_OR_FUTURE")
    return instant.astimezone(timezone.utc).isoformat()


def validate_observation(data, *, now=None):
    """Reject forged completion/dispatch, hidden fields and identity drift."""
    now = now or datetime.now(timezone.utc)
    require(type(data) is dict and set(data) == SOURCE_KEYS, "ROOT_FIELDS_INVALID")
    require(data["schema"] == SOURCE_SCHEMA and data["owner"] == OWNER
            and data["scope"] == "public_only" and data["source"] == SOURCE,
            "SOURCE_IDENTITY_INVALID")
    require(data["source_only"] is True and data["dispatch_authorized"] is False
            and data["merge_authorized"] is False and data["verified_complete"] is False,
            "AUTHORITY_FORGERY")
    require(_int(data["source_scan_id"]), "SOURCE_SCAN_ID_INVALID")
    observed = _timestamp(data["observed_at"], now)
    rows = data["repositories"]
    require(type(rows) is list and len(rows) <= MAX_ROWS
            and _int(data["public_repo_count"], 0)
            and len(rows) == data["public_repo_count"], "REPOSITORY_COUNT_INVALID")
    names, ids = set(), set()
    sanitized = []
    for row in rows:
        require(type(row) is dict and set(row) == REPO_KEYS, "REPO_FIELDS_INVALID")
        repo_id, name = row["github_id"], row["full_name"]
        require(_int(repo_id) and type(name) is str
                and NAME_RE.fullmatch(name) is not None
                and name.rsplit("/", 1)[-1] not in (".", "..")
                and type(row["archived"]) is bool
                and row["source_only"] is True and row["verified_complete"] is False,
                "REPO_IDENTITY_INVALID")
        require(repo_id not in ids and name.lower() not in names, "DUPLICATE_REPO")
        ids.add(repo_id)
        names.add(name.lower())
        sanitized.append({"github_id": repo_id, "full_name": name,
                          "archived": row["archived"]})
    events = data["recent_events"]
    require(type(events) is list and len(events) <= 200, "EVENT_COUNT_INVALID")
    event_ids = set()
    by_id = {item["github_id"]: item["full_name"] for item in sanitized}
    for event in events:
        require(type(event) is dict and set(event) == EVENT_KEYS, "EVENT_FIELDS_INVALID")
        event_id = event["id"]
        require(_int(event_id) and event_id not in event_ids
                and _int(event["github_id"])
                and event["github_id"] in by_id
                and event["full_name"] == by_id[event["github_id"]]
                and event["event_type"] in ALLOWED_EVENTS, "EVENT_IDENTITY_INVALID")
        _timestamp(event["observed_at"], now)
        event_ids.add(event_id)
    return {"scan_id": data["source_scan_id"], "observed_at": observed,
            "repositories": sanitized}


class StewardRegistry:
    def __init__(self, db_path):
        self.path = Path(db_path).expanduser()
        require(str(db_path) != ":memory:" and not self.path.is_symlink(), "DB_PATH_UNSAFE")
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(not self.path.parent.is_symlink(), "DB_PARENT_SYMLINK")
        if os.name == "posix":
            require((self.path.parent.stat().st_mode & 0o002) == 0, "DB_PARENT_UNSAFE")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(self.path, flags, 0o600)
        os.close(fd)
        if os.name == "posix":
            require((self.path.stat().st_mode & 0o077) == 0, "DB_PERMISSIONS_UNSAFE")
        with self._tx() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS source_state (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                scan_id INTEGER NOT NULL, observed_at TEXT NOT NULL,
                payload_digest TEXT NOT NULL
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS stewards (
                github_id INTEGER PRIMARY KEY, steward_key TEXT NOT NULL UNIQUE,
                full_name TEXT NOT NULL, archived INTEGER NOT NULL,
                present INTEGER NOT NULL, first_observed TEXT NOT NULL,
                last_observed TEXT NOT NULL, last_rotation INTEGER NOT NULL DEFAULT 0,
                planned_count INTEGER NOT NULL DEFAULT 0
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS rotation_turns (
                request_id TEXT PRIMARY KEY, batch_size INTEGER NOT NULL,
                generation INTEGER NOT NULL, selected_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""")

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

    @staticmethod
    def _source(db):
        return db.execute("SELECT * FROM source_state WHERE singleton=1").fetchone()

    def ingest(self, raw, *, now=None):
        if isinstance(raw, bytes):
            require(0 < len(raw) <= MAX_INPUT_BYTES, "INPUT_TOO_LARGE")
            try:
                data = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                raise StewardHeld("INPUT_JSON_INVALID") from None
        elif isinstance(raw, dict):
            data = raw
            require(len(json.dumps(raw).encode("utf-8")) <= MAX_INPUT_BYTES, "INPUT_TOO_LARGE")
        else:
            raise StewardHeld("INPUT_TYPE_INVALID")
        source = validate_observation(data, now=now)
        digest = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        with self._tx() as db:
            prior = self._source(db)
            if prior:
                require(source["scan_id"] >= prior["scan_id"], "SCAN_ROLLBACK_HELD")
                if source["scan_id"] == prior["scan_id"]:
                    require(prior["payload_digest"] == digest, "SCAN_ID_CONTENT_CHANGED")
                    return {"state": "IDEMPOTENT", "scan_id": prior["scan_id"],
                            "public_repos": len(source["repositories"]), "stewards_created": 0}
                require(source["observed_at"] >= prior["observed_at"],
                        "SCAN_TIME_ROLLBACK_HELD")
            db.execute("UPDATE stewards SET present=0")
            created = 0
            for item in source["repositories"]:
                repo_id = item["github_id"]
                existed = db.execute("SELECT github_id FROM stewards WHERE github_id=?",
                                     (repo_id,)).fetchone()
                if existed is None:
                    created += 1
                db.execute("""INSERT INTO stewards (
                    github_id, steward_key, full_name, archived, present,
                    first_observed, last_observed
                ) VALUES (?,?,?,?,1,?,?)
                ON CONFLICT(github_id) DO UPDATE SET
                    full_name=excluded.full_name,
                    archived=excluded.archived, present=1,
                    last_observed=excluded.last_observed""",
                    (repo_id, f"steward-gh-{repo_id}", item["full_name"],
                     int(item["archived"]), source["observed_at"], source["observed_at"]))
            db.execute("""INSERT INTO source_state(singleton,scan_id,observed_at,payload_digest)
                VALUES (1,?,?,?)
                ON CONFLICT(singleton) DO UPDATE SET scan_id=excluded.scan_id,
                observed_at=excluded.observed_at, payload_digest=excluded.payload_digest""",
                (source["scan_id"], source["observed_at"], digest))
        return {"state": "INGESTED", "scan_id": source["scan_id"],
                "public_repos": len(source["repositories"]), "stewards_created": created,
                "execution_authorized": False}

    def snapshot(self):
        """Only present public names are exported. Absent old names stay local."""
        with self._tx() as db:
            source = self._source(db)
            require(source is not None, "NO_SOURCE_OBSERVATIONS")
            rows = db.execute("""SELECT github_id,steward_key,full_name,archived,
                last_rotation,planned_count FROM stewards
                WHERE present=1 ORDER BY github_id""").fetchall()
            return {
                "schema": EXPORT_SCHEMA, "owner": OWNER, "scope": "public_only",
                "source": "AGENTORA_LOCAL_STEWARD_LEDGER",
                "source_scan_id": source["scan_id"],
                "observed_at": source["observed_at"],
                "stewards": [{
                    "github_id": r["github_id"], "steward_key": r["steward_key"],
                    "full_name": r["full_name"],
                    "state": "PAUSED_ARCHIVED" if r["archived"] else "AVAILABLE",
                    "planned_count": r["planned_count"], "last_rotation": r["last_rotation"],
                } for r in rows],
                "dispatch_authorized": False, "merge_authorized": False,
                "verified_complete": False,
            }

    def plan_rotation(self, request_id, batch_size=3, *, now=None):
        """Persist one advisory rotation. Never activate agents or claim resources."""
        require(type(request_id) is str and REQUEST_RE.fullmatch(request_id) is not None,
                "REQUEST_ID_INVALID")
        require(type(batch_size) is int and 1 <= batch_size <= 6,
                "BATCH_SIZE_INVALID")
        now = now or datetime.now(timezone.utc)
        with self._tx() as db:
            source = self._source(db)
            require(source is not None, "NO_SOURCE_OBSERVATIONS")
            require(-300 <= (now - datetime.fromisoformat(source["observed_at"])).total_seconds()
                    <= 36 * 3600, "SOURCE_STALE")
            old = db.execute("SELECT * FROM rotation_turns WHERE request_id=?",
                             (request_id,)).fetchone()
            if old:
                require(old["batch_size"] == batch_size, "REQUEST_REPLAY_MISMATCH")
                return {"state": "REPLAYED_ADVISORY", "request_id": request_id,
                        "generation": old["generation"], "selected": json.loads(old["selected_json"]),
                        "dispatch_authorized": False, "merge_authorized": False}
            generation = db.execute(
                "SELECT COALESCE(MAX(generation),0)+1 FROM rotation_turns").fetchone()[0]
            selected = db.execute("""SELECT github_id,steward_key FROM stewards
                WHERE present=1 AND archived=0
                ORDER BY last_rotation ASC, planned_count ASC, github_id ASC LIMIT ?""",
                (batch_size,)).fetchall()
            keys = [{"github_id": r["github_id"], "steward_key": r["steward_key"]}
                    for r in selected]
            for row in selected:
                db.execute("""UPDATE stewards SET last_rotation=?,
                    planned_count=planned_count+1 WHERE github_id=?""",
                    (generation, row["github_id"]))
            db.execute("""INSERT INTO rotation_turns (
                request_id,batch_size,generation,selected_json,created_at)
                VALUES (?,?,?,?,?)""",
                (request_id, batch_size, generation,
                 json.dumps(keys, separators=(",", ":")), now.isoformat()))
        return {"state": "PLANNED_ONLY", "request_id": request_id,
                "generation": generation, "selected": keys,
                "dispatch_authorized": False, "merge_authorized": False}
