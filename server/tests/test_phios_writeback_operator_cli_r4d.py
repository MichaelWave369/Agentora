"""Operator command refuses implicit, remote or unconfirmed actions."""
from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, SQLModel

from app.core.config import settings
from app.models import IntegrationRun
from app.services import phios_writeback_reconcile_cli as cli
from app.services.integration_orchestrator import IntegrationOrchestrator

ID = "a" * 64


def _database(tmp_path):
    path = tmp_path / "operator.sqlite"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(IntegrationRun(
            id=222, writeback_status="needs_reconciliation",
            writeback_operation_id=ID,
        ))
        session.commit()
    engine.dispose()
    return path


def _args(path, *, operation=ID, apply=False):
    args = [
        "--database", str(path), "--run-id", "222",
        "--expected-operation-id", operation,
    ]
    if apply:
        args.append("--apply")
    return args


def test_inspect_never_calls_remote(tmp_path, monkeypatch, capsys):
    path = _database(tmp_path)
    spy = Mock(side_effect=AssertionError("network forbidden"))
    monkeypatch.setattr(IntegrationOrchestrator, "reconcile_writeback_v1", spy)
    assert cli.main(_args(path)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] and not result["network_request_made"]
    spy.assert_not_called()


def test_operation_confirmation_mismatch_blocks(tmp_path, monkeypatch, capsys):
    path = _database(tmp_path)
    spy = Mock(side_effect=AssertionError("network forbidden"))
    monkeypatch.setattr(IntegrationOrchestrator, "reconcile_writeback_v1", spy)
    assert cli.main(_args(path, operation="f" * 64, apply=True)) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "NOT_HELD_OR_ID_MISMATCH"
    spy.assert_not_called()


def test_disabled_r4c_blocks_apply(tmp_path, monkeypatch, capsys):
    path = _database(tmp_path)
    monkeypatch.setattr(settings, "agentora_phios_writeback_v1_enabled", False)
    spy = Mock(side_effect=AssertionError("network forbidden"))
    monkeypatch.setattr(IntegrationOrchestrator, "reconcile_writeback_v1", spy)
    assert cli.main(_args(path, apply=True)) == 2
    assert json.loads(capsys.readouterr().out)["error_code"] == "R4C_DISABLED"
    spy.assert_not_called()


def test_confirmed_apply_calls_only_reconciler(tmp_path, monkeypatch, capsys):
    path = _database(tmp_path)
    monkeypatch.setattr(settings, "agentora_phios_writeback_v1_enabled", True)
    spy = Mock(return_value={"ok": True, "reconciled": True})
    monkeypatch.setattr(IntegrationOrchestrator, "reconcile_writeback_v1", spy)
    assert cli.main(_args(path, apply=True)) == 0
    spy.assert_called_once_with(222)
    assert json.loads(capsys.readouterr().out)["network_operation"] == "GET_ONLY"


def test_missing_or_linked_sqlite_files_denied(tmp_path):
    path = _database(tmp_path)
    missing = tmp_path / "missing.sqlite"
    alias = tmp_path / "alias.sqlite"
    alias.symlink_to(path)
    for candidate in (missing, alias):
        with pytest.raises(SystemExit):
            cli.main(_args(candidate))
    assert not missing.exists()
