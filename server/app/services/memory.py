from sqlmodel import Session, select
from app.models import MemoryItem


def remember(session: Session, agent_id: int, key: str, value: str) -> None:
    item = MemoryItem(agent_id=agent_id, key=key, value=value)
    session.add(item)
    session.commit()


def recall(session: Session, agent_id: int, limit: int = 5) -> list[MemoryItem]:
    return list(session.exec(select(MemoryItem).where(MemoryItem.agent_id == agent_id).limit(limit)))
