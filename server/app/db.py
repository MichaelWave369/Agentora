from pathlib import Path
from typing import Optional

from sqlmodel import SQLModel, Session, create_engine

from .core.config import settings


def _normalize_sqlite_url(url: str) -> str:
    if not url.startswith('sqlite:///'):
        return url
    db_path = Path(url.replace('sqlite:///', '', 1))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f'sqlite:///{db_path.as_posix()}'


def _build_engine(database_url: str):
    return create_engine(_normalize_sqlite_url(database_url), connect_args={'check_same_thread': False})


engine = _build_engine(settings.database_url)


def set_engine(database_url: str):
    global engine
    engine = _build_engine(database_url)
    return engine


def _ensure_integrationrun_columns() -> None:
    required = {
        'mission_title': "TEXT NOT NULL DEFAULT ''",
        'operator_intent': "TEXT NOT NULL DEFAULT ''",
        'context_summary': "TEXT NOT NULL DEFAULT ''",
        'dispatch_brief': "TEXT NOT NULL DEFAULT ''",
        'acceptance_criteria_json': "TEXT NOT NULL DEFAULT '[]'",
        'constraints_json': "TEXT NOT NULL DEFAULT '[]'",
        'success_criteria_json': "TEXT NOT NULL DEFAULT '[]'",
        'recommended_actions_json': "TEXT NOT NULL DEFAULT '[]'",
        'branch': "TEXT NOT NULL DEFAULT ''",
        'issue_urls_json': "TEXT NOT NULL DEFAULT '[]'",
        'artifact_urls_json': "TEXT NOT NULL DEFAULT '[]'",
        'writeback_status': "TEXT NOT NULL DEFAULT 'not_written'",
        'writeback_at': 'DATETIME',
        'writeback_error': "TEXT NOT NULL DEFAULT ''",
        'phios_packet_json': "TEXT NOT NULL DEFAULT '{}'",
        'agentception_result_json': "TEXT NOT NULL DEFAULT '{}'",
        'last_outcome_hash': "TEXT NOT NULL DEFAULT ''",
        'last_writeback_hash': "TEXT NOT NULL DEFAULT ''",
        'last_writeback_attempt_at': 'DATETIME',
        'writeback_policy': "TEXT NOT NULL DEFAULT 'manual'",
        'auto_writeback_enabled': 'BOOLEAN NOT NULL DEFAULT 0',
        'watch_enabled': 'BOOLEAN NOT NULL DEFAULT 1',
        'last_refreshed_at': 'DATETIME',
        'watch_error': "TEXT NOT NULL DEFAULT ''",
    }
    with engine.connect() as conn:
        try:
            rows = conn.exec_driver_sql("PRAGMA table_info('integrationrun')").fetchall()
        except Exception:
            return
        if not rows:
            return
        existing = {row[1] for row in rows}
        for col, col_def in required.items():
            if col not in existing:
                conn.exec_driver_sql(f'ALTER TABLE integrationrun ADD COLUMN {col} {col_def}')
        conn.commit()


def create_db_and_tables() -> None:
    # Ensure all SQLModel tables are registered before metadata.create_all()
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _ensure_integrationrun_columns()


def init_db(database_url: Optional[str] = None):
    if database_url:
        set_engine(database_url)
    create_db_and_tables()
    return engine


def get_session():
    with Session(engine) as session:
        yield session
