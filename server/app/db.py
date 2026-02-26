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


def create_db_and_tables() -> None:
    # Ensure all SQLModel tables are registered before metadata.create_all()
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)


def init_db(database_url: Optional[str] = None):
    if database_url:
        set_engine(database_url)
    create_db_and_tables()
    return engine


def get_session():
    with Session(engine) as session:
        yield session
