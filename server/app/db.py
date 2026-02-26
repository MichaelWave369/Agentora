from pathlib import Path
from sqlmodel import SQLModel, create_engine, Session

from .core.config import settings


def _normalize_sqlite_url(url: str) -> str:
    if not url.startswith('sqlite:///'):
        return url
    db_path = Path(url.replace('sqlite:///', '', 1))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f'sqlite:///{db_path.as_posix()}'


engine = create_engine(_normalize_sqlite_url(settings.database_url), connect_args={'check_same_thread': False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
