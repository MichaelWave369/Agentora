from sqlmodel import Session
from app.models import IntegrationSetting

DEFAULTS = ['private_spark', 'personal_memory_agent', 'growora']


def ensure_defaults(session: Session):
    for name in DEFAULTS:
        if not session.get(IntegrationSetting, name):
            session.add(IntegrationSetting(name=name, enabled=False, config_json='{}'))
    session.commit()


def statuses(session: Session) -> list[dict]:
    ensure_defaults(session)
    from sqlmodel import select
    return [{'name': i.name, 'enabled': i.enabled} for i in session.exec(select(IntegrationSetting))]
