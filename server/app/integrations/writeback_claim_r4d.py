"""Atomic SQLite writeback claims and receipt reconciliation (R4d).

A single conditional SQL UPDATE is the concurrency decision; never treat a
stale ORM object as authorization to perform another remote POST.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_, or_, update
from sqlmodel import Session

from app.models import IntegrationRun

HELD = ("dispatching", "needs_reconciliation")


def claim_writeback_v1(
    session: Session,
    *,
    run_id: int,
    envelope_json: str,
    operation_id: str,
    outcome_hash: str,
    attempted_at: datetime,
) -> bool:
    """One winning process persists its request before any network dispatch."""
    if not isinstance(run_id, int) or run_id <= 0:
        raise ValueError("writeback claim requires a persisted run ID")
    if not envelope_json or not operation_id or not outcome_hash:
        raise ValueError("writeback claim requires exact persisted identity")
    stmt = (
        update(IntegrationRun)
        .where(
            IntegrationRun.id == run_id,
            IntegrationRun.writeback_status.notin_(HELD),
            or_(
                IntegrationRun.writeback_status != "written",
                IntegrationRun.last_writeback_hash != outcome_hash,
            ),
        )
        .values(
            writeback_status="dispatching",
            writeback_request_json=envelope_json,
            writeback_operation_id=operation_id,
            writeback_outcome_hash=outcome_hash,
            last_writeback_attempt_at=attempted_at,
            writeback_error="",
        )
        .execution_options(synchronize_session="fetch")
    )
    result = session.exec(stmt)
    if result.rowcount != 1:
        session.rollback()
        return False
    # A successful transaction boundary is essential: a crash immediately
    # after this commit leaves a held state that another process can inspect.
    session.commit()
    return True


def reconcile_published_v1(
    session: Session,
    *,
    run_id: int,
    operation_id: str,
    envelope_json: str,
    outcome_hash: str,
    reconciled_at: datetime,
) -> bool:
    """Only a still-held, identical operation may become written after GET proof."""
    stmt = (
        update(IntegrationRun)
        .where(
            IntegrationRun.id == run_id,
            IntegrationRun.writeback_status.in_(HELD),
            IntegrationRun.writeback_operation_id == operation_id,
            IntegrationRun.writeback_request_json == envelope_json,
            IntegrationRun.writeback_outcome_hash == outcome_hash,
        )
        .values(
            writeback_status="written",
            writeback_at=reconciled_at,
            writeback_error="",
            last_writeback_hash=outcome_hash,
        )
        .execution_options(synchronize_session="fetch")
    )
    result = session.exec(stmt)
    if result.rowcount != 1:
        session.rollback()
        return False
    session.commit()
    return True
