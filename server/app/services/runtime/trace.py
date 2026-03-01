from __future__ import annotations

import json
from typing import Any

from sqlmodel import Session, select

from app.models import RunTrace


def add_trace(session: Session, run_id: int, event_type: str, payload: dict[str, Any], agent_id: int = 0) -> None:
    session.add(RunTrace(run_id=run_id, agent_id=agent_id, event_type=event_type, payload_json=json.dumps(payload)))


def get_run_trace(session: Session, run_id: int) -> list[dict]:
    rows = list(session.exec(select(RunTrace).where(RunTrace.run_id == run_id).order_by(RunTrace.id)))
    out: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row.payload_json)
        except Exception:
            payload = {'raw': row.payload_json}
        out.append({'id': row.id, 'run_id': row.run_id, 'agent_id': row.agent_id, 'event_type': row.event_type, 'payload': payload, 'created_at': row.created_at.isoformat()})
    return out
