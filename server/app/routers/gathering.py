import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import GatheringSession, GatheringEvent
from app.services.gathering.service import (
    discover_local_instances,
    create_session,
    join_session,
    add_event,
    gathering_templates,
    ensure_templates_registered,
)

router = APIRouter(prefix='/api/gathering', tags=['gathering'])


@router.get('/discover')
def discover():
    devices = discover_local_instances()
    return {'devices': devices, 'message': 'No other devices found — solo mode still works great!' if not devices else ''}


@router.post('/session/create')
def create(payload: dict, session: Session = Depends(get_session)):
    gs = create_session(session, payload.get('host_name', 'Host'), payload.get('mode', 'studio'))
    ensure_templates_registered(session)
    return {'id': gs.id, 'room_code': gs.room_code, 'invite_code': gs.invite_code, 'mode': gs.mode, 'host_name': gs.host_name}


@router.post('/session/join')
def join(payload: dict, session: Session = Depends(get_session)):
    gs = join_session(session, payload['room_code'], payload.get('name', 'Guest'))
    if not gs:
        raise HTTPException(404, 'room not found')
    return {'id': gs.id, 'room_code': gs.room_code, 'invite_code': gs.invite_code, 'mode': gs.mode, 'host_name': gs.host_name}


@router.get('/session/{session_id}')
def session_state(session_id: int, session: Session = Depends(get_session)):
    gs = session.get(GatheringSession, session_id)
    if not gs:
        raise HTTPException(404, 'session not found')
    events = list(session.exec(select(GatheringEvent).where(GatheringEvent.session_id == session_id)))
    return {'session': gs.model_dump(), 'participants': json.loads(gs.participants_json), 'events': [e.model_dump() for e in events]}


@router.post('/session/{session_id}/event')
def event(session_id: int, payload: dict, session: Session = Depends(get_session)):
    add_event(session, session_id, payload.get('type', 'message'), payload.get('payload', {}))
    return {'ok': True}


@router.get('/templates')
def templates():
    return {'templates': gathering_templates()}


@router.post('/memory/import')
def memory_import(payload: dict, session: Session = Depends(get_session)):
    gs = session.get(GatheringSession, payload['session_id'])
    if not gs:
        raise HTTPException(404, 'session not found')
    if not payload.get('consent', False):
        return {'ok': False, 'message': 'Consent required'}
    memories = json.loads(gs.memories_json)
    memories.extend(payload.get('items', []))
    gs.memories_json = json.dumps(memories)
    session.add(gs)
    session.commit()
    return {'ok': True, 'count': len(memories)}
