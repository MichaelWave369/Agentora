import json
import random
from datetime import datetime
from pathlib import Path
from sqlmodel import Session, select

from app.models import GatheringSession, GatheringEvent, InstalledTemplate


def discover_local_instances() -> list[dict]:
    return [
        {'name': 'Living Room Host', 'ip': '192.168.1.10', 'avatar': '🛋️', 'strength': 0.95},
        {'name': 'Kitchen Tablet', 'ip': '192.168.1.22', 'avatar': '📱', 'strength': 0.72},
    ]


def make_room_code() -> str:
    return f"{random.randint(0, 9999):04d}"


def create_session(session: Session, host_name: str, mode: str = 'studio') -> GatheringSession:
    room = make_room_code()
    invite = f"GTH-{room}"
    gs = GatheringSession(room_code=room, invite_code=invite, host_name=host_name, mode=mode, participants_json=json.dumps([{'name': host_name, 'role': 'host', 'joined_at': datetime.utcnow().isoformat()}]))
    session.add(gs)
    session.commit()
    session.refresh(gs)
    return gs


def join_session(session: Session, room_code: str, name: str) -> GatheringSession | None:
    gs = session.exec(select(GatheringSession).where(GatheringSession.room_code == room_code)).first()
    if not gs:
        return None
    people = json.loads(gs.participants_json)
    people.append({'name': name, 'role': 'guest', 'joined_at': datetime.utcnow().isoformat()})
    gs.participants_json = json.dumps(people)
    session.add(gs)
    session.commit()
    session.refresh(gs)
    return gs


def add_event(session: Session, gathering_id: int, event_type: str, payload: dict):
    ev = GatheringEvent(session_id=gathering_id, event_type=event_type, payload_json=json.dumps(payload))
    session.add(ev)
    session.commit()


def gathering_templates() -> list[dict]:
    return [
        {'name': 'Grocery Run Planner', 'mode': 'gathering', 'description': 'Coordinate errands together'},
        {'name': 'Neighborhood Watch Truth Squad', 'mode': 'gathering', 'description': 'Verify local reports together'},
        {'name': 'Family Budget Band', 'mode': 'gathering', 'description': 'Budget planning with musical motivation'},
        {'name': 'Bedtime Story Crew', 'mode': 'gathering', 'description': 'Collaborative family storytelling'},
    ]


def ensure_templates_registered(session: Session):
    out = Path('server/data/user_templates')
    out.mkdir(parents=True, exist_ok=True)
    for t in gathering_templates():
        if not session.exec(select(InstalledTemplate).where(InstalledTemplate.name == t['name'])).first():
            p = out / f"{t['name'].lower().replace(' ','-')}@1.0.0.yaml"
            p.write_text(json.dumps(t), encoding='utf-8')
            session.add(InstalledTemplate(name=t['name'], version='1.0.0', description=t['description'], yaml_path=str(p), tags_json='["gathering"]', source='gathering'))
    session.commit()
