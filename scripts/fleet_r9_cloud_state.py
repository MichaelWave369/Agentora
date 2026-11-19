"""Single-writer, crash-conservative volume layout for the EXISTING R9 SQLite ledgers.

Offline library only. It deliberately does not provision cloud storage, start
workers, authorize merges, or make a GitHub Actions runner persistent.
"""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from tempfile import mkdtemp
from urllib.parse import quote

SCHEMA = "agentora.r9.volume-state.v1"
OWNER = "MichaelWave369"
REPO = "MichaelWave369/Agentora"
REPO_ID = 1167870912
DB_NAMES = ("reponerve.sqlite3", "r9-stewards.sqlite3", "r9-leases.sqlite3")
MARKER = ".r9-state-manifest.json"
LOCK = ".r9-single-writer.lock"


class VolumeHeld(ValueError):
    pass


def need(ok, reason):
    if not ok:
        raise VolumeHeld(reason)


def _regular_private(path):
    need(path.is_file() and not path.is_symlink(), "R9_VOLUME_FILE_MISSING_OR_UNSAFE")
    stat = path.stat()
    need(stat.st_mode & 0o077 == 0 and stat.st_nlink == 1,
         "R9_VOLUME_FILE_PERMISSIONS_UNSAFE")
    need(stat.st_size > 0, "R9_VOLUME_FILE_EMPTY")


def _integrity(dbpath):
    _regular_private(dbpath)
    # Read-only integrity verification; do not manufacture a missing DB.
    try:
        with sqlite3.connect("file:" + quote(str(dbpath), safe="/") + "?mode=ro",
                             uri=True, timeout=3) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchall()
        need(result == [("ok",)], "R9_VOLUME_DB_CORRUPT")
    except sqlite3.DatabaseError:
        raise VolumeHeld("R9_VOLUME_DB_UNREADABLE") from None


def manifest():
    return {"schema": SCHEMA, "owner": OWNER, "repository": REPO,
            "repository_id": REPO_ID, "db_files": list(DB_NAMES),
            "authority": "public_observation_only", "dispatch_authorized": False}


class VolumeState:
    """Active is immutable until a fully verified seed has been atomically named.

    A writer lock is held over the complete public scan, R9 transaction, and
    commit. A crash before first publish leaves a staging directory and HOLDS
    future boots for manual reconciliation, rather than silently wiping it.
    """

    def __init__(self, path):
        root = Path(path).expanduser()
        need(root.is_absolute() and ".." not in root.parts and
             str(root) not in ("/", "/tmp", "/var/tmp"),
             "R9_VOLUME_ROOT_INVALID")
        for component in (root, *root.parents):
            need(not component.is_symlink(), "R9_VOLUME_SYMLINK_REJECTED")
        self.root = root
        self.working = None
        self.is_new = None
        self._lock_fd = None
        self._old_umask = None

    def __enter__(self):
        try:
            self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
            st = self.root.stat()
            need(st.st_mode & 0o077 == 0 and st.st_uid == os.getuid(),
                 "R9_VOLUME_ROOT_PERMISSIONS_UNSAFE")
            lock_path = self.root / LOCK
            need(not lock_path.is_symlink(), "R9_VOLUME_LOCK_SYMLINK")
            flags = os.O_RDWR | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            self._lock_fd = os.open(lock_path, flags, 0o600)
            need(os.fstat(self._lock_fd).st_mode & 0o077 == 0,
                 "R9_VOLUME_LOCK_PERMISSIONS_UNSAFE")
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise VolumeHeld("R9_VOLUME_WRITER_ACTIVE") from None
            active = self.root / "active"
            if active.exists() or active.is_symlink():
                self.working = active
                self.is_new = False
                self.verify()
            else:
                need(set(p.name for p in self.root.iterdir()) == {LOCK},
                     "R9_VOLUME_ORPHANED_SEED_OR_UNEXPECTED_FILES")
                self.working = Path(mkdtemp(prefix=".staging-r9-", dir=self.root))
                self.is_new = True
            self._old_umask = os.umask(0o077)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def verify(self):
        need(self.working is not None and self.working.is_dir() and
             not self.working.is_symlink(), "R9_VOLUME_ACTIVE_DIRECTORY_INVALID")
        if not self.is_new:
            expected = json.dumps(manifest(), sort_keys=True, separators=(",", ":"))
            marker_path = self.working / MARKER
            _regular_private(marker_path)
            need(marker_path.read_text(encoding="utf-8") == expected,
                 "R9_VOLUME_MANIFEST_MISMATCH")
        for name in DB_NAMES:
            _integrity(self.working / name)

    def commit(self):
        need(self._lock_fd is not None and self.working is not None,
             "R9_VOLUME_NOT_LOCKED")
        self.verify()
        if self.is_new:
            marker_path = self.working / MARKER
            need(not marker_path.exists() and not marker_path.is_symlink(),
                 "R9_VOLUME_MANIFEST_ALREADY_PRESENT")
            payload = json.dumps(manifest(), sort_keys=True, separators=(",", ":"))
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(marker_path, flags, 0o600)
            try:
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
            fd = os.open(self.working, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            target = self.root / "active"
            need(not target.exists() and not target.is_symlink(),
                 "R9_VOLUME_ACTIVE_APPEARED_DURING_SEED")
            os.rename(self.working, target)
            self.working, self.is_new = target, False
            fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        self.verify()

    def __exit__(self, *_):
        if self._old_umask is not None:
            os.umask(self._old_umask)
            self._old_umask = None
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(self._lock_fd)
                self._lock_fd = None
        # Do NOT delete an incomplete seed. A crash or failed first admission
        # must be investigated, never treated as a fresh empty state.
        return False
