"""R4a shared Agentora/PhiOS operation identity (contract only).

Pure helpers: no HTTP, no memory writes, no configuration activation.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

PROTOCOL = "phios.agentora.writeback.v1"
_ID_DOMAIN = (PROTOCOL + "\n").encode("utf-8")
MAX_ENVELOPE_BYTES = 32 * 1024


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def operation_identity(payload: dict[str, object]) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("writeback payload must be an object")
    session = payload.get("session_id")
    task = payload.get("task_id")
    if not isinstance(session, str) or not session.strip():
        raise ValueError("session_id must be a nonempty string")
    if not isinstance(task, str) or not task.strip():
        raise ValueError("task_id must be a nonempty string")
    raw = payload.get("raw_payload")
    if not isinstance(raw, dict):
        raise ValueError("raw_payload must be an object")
    outcome = raw.get("outcome")
    if not isinstance(outcome, dict) or not outcome:
        raise ValueError("raw_payload.outcome must be a nonempty object")
    return {"session_id": session.strip(), "task_id": task.strip(), "outcome": outcome}


def operation_id(payload: dict[str, object]) -> str:
    identity = operation_identity(payload)
    return hashlib.sha256(_ID_DOMAIN + _canonical(identity).encode("utf-8")).hexdigest()


def canonical_envelope(payload: dict[str, object], *, created_at_utc: str) -> str:
    operation_identity(payload)
    if not isinstance(created_at_utc, str) or not created_at_utc.strip():
        raise ValueError("created_at_utc must be a timestamp")
    try:
        parsed = datetime.fromisoformat(created_at_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid created_at_utc") from exc
    if parsed.tzinfo is None:
        raise ValueError("created_at_utc must include a timezone")
    normalized = parsed.astimezone(timezone.utc).isoformat()
    text = _canonical({
        "protocol_version": PROTOCOL,
        "created_at_utc": normalized,
        "payload": payload,
    })
    if len(text.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise ValueError("writeback envelope too large")
    return text
