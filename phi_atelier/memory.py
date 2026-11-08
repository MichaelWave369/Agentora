"""Human-governed PhiAtelier visual feedback memory.

The ledger records explicit local human decisions about model suggestions.
It never triggers a model call, trains weights, modifies rendered images, or
authorizes future GPU work. Hash chaining catches accidental changes, not a
malicious workstation administrator and not human identity.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ZERO = "0" * 64
TTL_SECONDS = 60 * 60
MAX_PENDING = 16
MAX_RECORDS = 5000
DECISIONS = frozenset({"accepted", "rejected", "revised"})


class MemoryError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":")).encode("utf-8")


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value)).hexdigest()


def bounded(value: Any, label: str, low: int, high: int) -> str:
    if not isinstance(value, str) or not low <= len(value.strip()) <= high:
        raise MemoryError(label + " length out of bounds")
    value = value.strip()
    if any(ord(c) < 32 and c not in "\n\t" for c in value):
        raise MemoryError("control characters in " + label)
    return value


class ReviewMemory:
    """A one-process review staging registry and append-only SQLite decisions."""

    def __init__(self, database: str | Path | None = None):
        self.database = Path(database).expanduser() if database else (
            Path.home() / ".agentora" / "phi_atelier_feedback.sqlite3"
        )
        self._lock = threading.RLock()
        self._pending: dict[str, tuple[float, dict]] = {}

    def _connect(self, create: bool = False):
        if self.database.is_symlink():
            raise MemoryError("feedback ledger cannot be a symlink", 503)
        if not create and not self.database.is_file():
            return None
        if create:
            self.database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.database.parent.is_symlink():
                raise MemoryError("feedback ledger parent cannot be a symlink", 503)
            try:
                fd = os.open(str(self.database), os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(fd)
        try:
            db = sqlite3.connect(str(self.database), timeout=4)
            db.row_factory = sqlite3.Row
            if create:
                db.execute("""CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    review_digest TEXT NOT NULL UNIQUE,
                    job_id TEXT NOT NULL,
                    image_sha256 TEXT NOT NULL,
                    model TEXT NOT NULL,
                    original_prompt TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    human_reason TEXT NOT NULL,
                    reviewed_suggestion TEXT NOT NULL,
                    approved_guidance TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    entry_hash TEXT NOT NULL
                )""")
                db.commit()
            return db
        except sqlite3.DatabaseError as exc:
            raise MemoryError("feedback ledger unavailable", 503) from exc

    @staticmethod
    def _verified(db) -> list[dict]:
        if db is None:
            return []
        try:
            rows = [dict(r) for r in db.execute("SELECT * FROM feedback ORDER BY id ASC")]
        except sqlite3.DatabaseError as exc:
            raise MemoryError("feedback ledger unreadable", 503) from exc
        if len(rows) > MAX_RECORDS:
            raise MemoryError("feedback ledger exceeds bounded capacity", 503)
        head, last_id = ZERO, 0
        fields = (
            "review_digest", "job_id", "image_sha256", "model",
            "original_prompt", "decision", "human_reason", "reviewed_suggestion",
            "approved_guidance", "created_at", "previous_hash",
        )
        seen = set()
        for row in rows:
            try:
                payload = {k: row[k] for k in fields}
                if (row["id"] != last_id + 1
                        or row["review_digest"] in seen
                        or row["decision"] not in DECISIONS
                        or row["previous_hash"] != head
                        or hashlib.sha256(canonical(payload)).hexdigest() != row["entry_hash"]):
                    raise MemoryError("feedback ledger integrity check failed", 503)
                last_id, head = row["id"], row["entry_hash"]
                seen.add(row["review_digest"])
            except (KeyError, TypeError, ValueError) as exc:
                raise MemoryError("feedback ledger integrity check failed", 503) from exc
        return rows

    def stage(self, report: dict, *, original_prompt: str) -> str:
        """Hold an unverified vision report in memory until a *separate* human action."""
        if not isinstance(report, dict):
            raise MemoryError("invalid model review report")
        expected = (
            "job_id", "image_sha256", "model", "observations", "origin",
            "review_status", "new_render_queued",
        )
        if any(key not in report for key in expected):
            raise MemoryError("incomplete vision report")
        if (report["origin"] != "local_vision_model_unverified"
                or report["review_status"] != "human_review_required"
                or report["new_render_queued"] is not False):
            raise MemoryError("only unverified, non-rendering vision reports can be staged")
        try:
            if str(uuid.UUID(report["job_id"])) != report["job_id"]:
                raise ValueError()
        except (TypeError, ValueError, AttributeError) as exc:
            raise MemoryError("invalid source job UUID") from exc
        image_hash = report["image_sha256"]
        if (not isinstance(image_hash, str) or len(image_hash) != 71
                or not image_hash.startswith("sha256:")
                or any(ch not in "0123456789abcdef" for ch in image_hash[7:])):
            raise MemoryError("invalid source image digest")
        source = report["observations"]
        if not isinstance(source, dict) or "specific_suggestions" not in source:
            raise MemoryError("invalid source observations")
        suggestion = bounded(source["specific_suggestions"], "suggestion", 12, 1200)
        model = bounded(report["model"], "model", 1, 120)
        prompt = bounded(original_prompt, "original_prompt", 1, 3000)
        # The source digest binds model observations, job, image and user intent.
        source_data = {
            "job_id": report["job_id"], "image_sha256": image_hash,
            "model": model, "original_prompt": prompt,
            "observations": source,
        }
        review_digest = digest(source_data)
        with self._lock:
            now = time.monotonic()
            self._pending = {
                k: v for k, v in self._pending.items() if now - v[0] < TTL_SECONDS
            }
            if review_digest not in self._pending and len(self._pending) >= MAX_PENDING:
                raise MemoryError("too many pending visual critiques in this session", 409)
            self._pending[review_digest] = (now, {
                "review_digest": review_digest, "job_id": report["job_id"],
                "image_sha256": image_hash, "model": model,
                "original_prompt": prompt, "reviewed_suggestion": suggestion,
            })
        return review_digest

    def decide(
        self, *, review_digest: str, decision: str,
        human_reason: str, edited_guidance: str = "",
        human_confirm: bool = False,
    ) -> dict:
        """Append exactly one explicit human decision to the local ledger."""
        if human_confirm is not True:
            raise MemoryError("explicit human confirmation required", 403)
        if decision not in DECISIONS:
            raise MemoryError("decision must be accepted, rejected or revised")
        reason = bounded(human_reason, "human_reason", 8, 500)
        if not isinstance(edited_guidance, str):
            raise MemoryError("edited_guidance must be text")
        if decision == "revised":
            guidance = bounded(edited_guidance, "edited_guidance", 8, 700)
        elif edited_guidance.strip():
            raise MemoryError("edited guidance is only permitted for revised decisions")
        else:
            guidance = ""
        with self._lock:
            pending = self._pending.get(review_digest)
            if pending is None or time.monotonic() - pending[0] >= TTL_SECONDS:
                self._pending.pop(review_digest, None)
                raise MemoryError("vision review not pending or expired; request a new critique", 409)
            source = pending[1]
            if decision == "accepted":
                guidance = source["reviewed_suggestion"]
            db = self._connect(create=True)
            try:
                db.execute("BEGIN IMMEDIATE")
                rows = self._verified(db)
                if any(row["review_digest"] == review_digest for row in rows):
                    raise MemoryError("this review already has a human decision", 409)
                if len(rows) >= MAX_RECORDS:
                    raise MemoryError("local feedback ledger is full", 409)
                data = {
                    **source,
                    "decision": decision,
                    "human_reason": reason,
                    "approved_guidance": guidance,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "previous_hash": rows[-1]["entry_hash"] if rows else ZERO,
                }
                entry_hash = hashlib.sha256(canonical(data)).hexdigest()
                cursor = db.execute("""INSERT INTO feedback (
                    review_digest, job_id, image_sha256, model, original_prompt,
                    decision, human_reason, reviewed_suggestion, approved_guidance,
                    created_at, previous_hash, entry_hash
                ) VALUES (
                    :review_digest, :job_id, :image_sha256, :model, :original_prompt,
                    :decision, :human_reason, :reviewed_suggestion, :approved_guidance,
                    :created_at, :previous_hash, :entry_hash
                )""", {**data, "entry_hash": entry_hash})
                db.commit()
                self._pending.pop(review_digest, None)
                return {
                    "id": cursor.lastrowid,
                    **data, "entry_hash": entry_hash,
                    "trust_level": "human_decision_recorded_not_verified_identity",
                    "training_performed": False, "new_render_queued": False,
                }
            except (sqlite3.DatabaseError, MemoryError) as exc:
                db.rollback()
                if isinstance(exc, MemoryError):
                    raise
                raise MemoryError("feedback ledger could not commit", 503) from exc
            finally:
                db.close()

    def list_decisions(self, *, limit: int = 50) -> dict:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MemoryError("limit must be 1..100")
        with self._lock:
            db = self._connect()
            try:
                rows = self._verified(db)
            finally:
                if db is not None:
                    db.close()
            return {
                "schema_version": "phi.atelier.feedback-memory.v1",
                "entries": [
                    {k: row[k] for k in (
                        "id", "review_digest", "job_id", "image_sha256", "model",
                        "original_prompt", "decision", "human_reason",
                        "reviewed_suggestion", "approved_guidance",
                        "created_at", "entry_hash",
                    )} for row in reversed(rows[-limit:])
                ],
                "total_entries": len(rows),
                "head": rows[-1]["entry_hash"] if rows else ZERO,
                "verified_hash_chain": True,
                "training_performed": False,
                "renderer_contacted": False,
                "persistence": "local_sqlite",
            }

    def accepted_context(self, limit: int = 10) -> dict:
        """Explicit manual retrieval only; not automatically used as model context."""
        if type(limit) is not int or not 1 <= limit <= 20:
            raise MemoryError("limit must be 1..20")
        result = self.list_decisions(limit=100)
        notes = [
            {
                "review_digest": r["review_digest"],
                "source_image_sha256": r["image_sha256"],
                "original_prompt": r["original_prompt"],
                "approved_guidance": r["approved_guidance"],
                "decision": r["decision"],
            }
            for r in result["entries"]
            if r["decision"] in ("accepted", "revised") and r["approved_guidance"]
        ][:limit]
        return {
            "schema_version": "phi.atelier.approved-feedback-context.v1",
            "notes": notes,
            "source": "human-reviewed_feedback_reference_only",
            "trust_level": "lower_trust_data_not_authority",
            "automatically_injected_into_model": False,
            "model_training_performed": False,
            "new_render_queued": False,
        }
