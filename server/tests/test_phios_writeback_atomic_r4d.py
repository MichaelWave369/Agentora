"""R4d SQLite claim and reconciliation are atomic across real sessions."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier

from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.integrations.writeback_claim_r4d import claim_writeback_v1, reconcile_published_v1
from app.models import IntegrationRun


def _engine(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'r4d.sqlite'}",
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(IntegrationRun(
            id=221, repo="owner/repo", phios_session_id="session-221",
            agentception_job_id="job-221", writeback_status="not_written",
        ))
        session.commit()
    return engine


def _claim(session, *, operation="a" * 64, outcome="outcome-A"):
    return claim_writeback_v1(
        session, run_id=221, envelope_json='{"persisted":"exact"}',
        operation_id=operation, outcome_hash=outcome,
        attempted_at=datetime(2026, 11, 21, 20, 0),
    )


def test_stale_sessions_cannot_both_claim_same_mission(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as first, Session(engine) as second:
        assert first.get(IntegrationRun, 221).writeback_status == "not_written"
        assert second.get(IntegrationRun, 221).writeback_status == "not_written"
        assert _claim(first)
        assert not _claim(second)
        second.expire_all()
        saved = second.get(IntegrationRun, 221)
        assert saved.writeback_status == "dispatching"
        assert saved.writeback_operation_id == "a" * 64
        assert saved.writeback_request_json == '{"persisted":"exact"}'
        assert saved.writeback_outcome_hash == "outcome-A"
    engine.dispose()


def test_simultaneous_workers_exactly_one_winner(tmp_path):
    engine = _engine(tmp_path)
    barrier = Barrier(2)

    def worker(op):
        with Session(engine) as session:
            barrier.wait(timeout=5)
            return _claim(session, operation=op)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ("a" * 64, "b" * 64)))
    assert sorted(results) == [False, True]
    with Session(engine) as session:
        row = session.get(IntegrationRun, 221)
        assert row.writeback_status == "dispatching"
        assert row.writeback_operation_id in {"a" * 64, "b" * 64}
    engine.dispose()


def test_crash_after_claim_keeps_durable_hold(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        assert _claim(session)
    with Session(engine) as restarted:
        assert not _claim(restarted)
        assert restarted.get(IntegrationRun, 221).writeback_status == "dispatching"
    engine.dispose()


def test_written_same_outcome_cannot_be_reclaimed(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        row = session.get(IntegrationRun, 221)
        row.writeback_status = "written"
        row.last_writeback_hash = "outcome-A"
        session.commit()
    with Session(engine) as session:
        assert not _claim(session)
        assert _claim(session, operation="c" * 64, outcome="outcome-C")
    engine.dispose()


def test_receipt_cas_checks_held_and_exact_operation(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        assert _claim(session)
        args = {
            "session": session, "run_id": 221,
            "envelope_json": '{"persisted":"exact"}',
            "outcome_hash": "outcome-A", "reconciled_at": datetime.utcnow(),
        }
        assert not reconcile_published_v1(operation_id="b" * 64, **args)
        assert reconcile_published_v1(operation_id="a" * 64, **args)
        assert not reconcile_published_v1(operation_id="a" * 64, **args)
        saved = session.get(IntegrationRun, 221)
        assert saved.writeback_status == "written"
        assert saved.last_writeback_hash == "outcome-A"
    engine.dispose()
