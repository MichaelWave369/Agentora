"""The R4c envelope migration is additive for existing IntegrationRun databases."""
from sqlalchemy import create_engine

import app.db as db


def test_r4c_fields_added_to_legacy_integrationrun_without_recreating_table(tmp_path, monkeypatch):
    engine = create_engine(f'sqlite:///{tmp_path / "old.sqlite3"}')
    with engine.begin() as conn:
        conn.exec_driver_sql(
            'CREATE TABLE integrationrun (id INTEGER PRIMARY KEY, writeback_status TEXT)'
        )
        conn.exec_driver_sql(
            "INSERT INTO integrationrun (id, writeback_status) VALUES (11, 'needs_reconciliation')"
        )
    monkeypatch.setattr(db, 'engine', engine)
    db._ensure_integrationrun_columns()
    with engine.connect() as conn:
        names = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info(integrationrun)')}
        assert {'writeback_request_json', 'writeback_operation_id',
                'writeback_outcome_hash'}.issubset(names)
        row = conn.exec_driver_sql(
            'SELECT writeback_status, writeback_request_json, writeback_operation_id '
            'FROM integrationrun WHERE id=11'
        ).one()
    assert tuple(row) == ('needs_reconciliation', '{}', '')
