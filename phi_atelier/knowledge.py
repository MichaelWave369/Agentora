"""Read-only approval check for PhiRepoNerve's exact ΦLoad v1 review format.

Knowledge remains lower-trust reference data, even after local approval.
No third-party import, model call, ledger mutation or network activity occurs.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

PACK_ID = "create.visual-grammar"
PACK_KEYS = frozenset({
    "schema_version", "id", "version", "title", "description",
    "events", "repo_contains", "knowledge", "provenance",
})
LEDGER_FIELDS = (
    "pack_id", "pack_version", "digest", "decision",
    "reviewer", "reason", "created_at", "previous_hash",
)
ZERO_HASH = "0" * 64


class KnowledgeUnavailable(ValueError):
    """Missing, unapproved, revoked, changed or integrity-invalid knowledge."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _read_pack(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise KnowledgeUnavailable("knowledge pack absent, symlinked or oversized")
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise KnowledgeUnavailable("knowledge pack cannot be read") from exc
    if not isinstance(obj, dict) or set(obj) != PACK_KEYS:
        raise KnowledgeUnavailable("unsupported knowledge pack schema")
    if type(obj["schema_version"]) is not int or obj["schema_version"] != 1:
        raise KnowledgeUnavailable("unsupported knowledge pack version")
    if obj["id"] != PACK_ID:
        raise KnowledgeUnavailable("incorrect knowledge pack identity")
    if not isinstance(obj["version"], str) or not 1 <= len(obj["version"]) <= 40:
        raise KnowledgeUnavailable("invalid pack version")
    if not isinstance(obj["provenance"], str) or not 1 <= len(obj["provenance"]) <= 300:
        raise KnowledgeUnavailable("invalid pack provenance")
    if not isinstance(obj["knowledge"], list) or not 1 <= len(obj["knowledge"]) <= 24:
        raise KnowledgeUnavailable("invalid pack knowledge")
    if any(not isinstance(s, str) or not s.strip() or len(s) > 500
           for s in obj["knowledge"]):
        raise KnowledgeUnavailable("invalid knowledge entry")
    return obj


def _approved_in_ledger(db_path: Path, pack_id: str, version: str, digest: str) -> bool:
    if db_path.is_symlink() or not db_path.is_file():
        raise KnowledgeUnavailable("review ledger missing or symlinked")
    # SQLite URI mode=ro never creates or changes the review database.
    uri = db_path.absolute().as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=3) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM pack_reviews ORDER BY id ASC"
            )]
    except (sqlite3.Error, OSError, ValueError) as exc:
        raise KnowledgeUnavailable("review ledger cannot be read") from exc
    head = ZERO_HASH
    last_id = 0
    latest = None
    for row in rows:
        try:
            fields = {k: row[k] for k in LEDGER_FIELDS}
            payload_hash = hashlib.sha256(_canonical(fields)).hexdigest()
            if (row["id"] != last_id + 1
                    or fields["decision"] not in ("approved", "revoked")
                    or fields["previous_hash"] != head
                    or payload_hash != row["entry_hash"]):
                raise KnowledgeUnavailable("review ledger integrity failure")
            last_id = row["id"]
            head = row["entry_hash"]
            if (fields["pack_id"], fields["pack_version"], fields["digest"]) == (
                pack_id, version, digest
            ):
                latest = fields["decision"]
        except (KeyError, TypeError) as exc:
            raise KnowledgeUnavailable("invalid review ledger fields") from exc
    return latest == "approved"


def load_approved_visual_grammar(
    pack_path: str | Path, reviews_db_path: str | Path
) -> dict[str, Any]:
    """Fail closed unless the exact pack digest is approved and not revoked.

    This mirrors ΦLoad's v1 canonical digest and chained review semantics.
    A locally compromised database is outside this mechanism's security model.
    """
    pack = _read_pack(Path(pack_path).expanduser())
    digest = "sha256:" + hashlib.sha256(_canonical(pack)).hexdigest()
    if not _approved_in_ledger(
        Path(reviews_db_path).expanduser(), pack["id"], pack["version"], digest
    ):
        raise KnowledgeUnavailable("knowledge pack requires explicit local approval")
    return {
        "id": pack["id"],
        "version": pack["version"],
        "digest": digest,
        "provenance": pack["provenance"],
        "knowledge": list(pack["knowledge"]),
        "review_status": "approved",
        "trust_level": "reviewed_reference_data_not_instructions",
        "capability_verified": False,
    }
