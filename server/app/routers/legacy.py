import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import engine
from app.models import Agent
from app.services.legacy.service import (
    export_heirloom,
    gather_legacy_stats,
    ingest_mode_history,
    list_souls,
    load_or_create_soul,
    nurture,
    reflection,
    spawn_child,
)

router = APIRouter(prefix='/api/legacy', tags=['legacy'])


class NurtureReq(BaseModel):
    agent_id: int
    dimension: str
    delta: int = 1
    note: str = ''


class ChildReq(BaseModel):
    parent_ids: list[int]
    child_name: str
    specialization: str = 'community_guardian'


@router.get('/souls')
def souls():
    with Session(engine) as session:
        return {'items': list_souls(session), 'stats': gather_legacy_stats(session)}


@router.get('/soul/{agent_id}')
def soul(agent_id: int):
    with Session(engine) as session:
        try:
            return load_or_create_soul(session, agent_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='agent_not_found')


@router.post('/nurture')
def nurture_agent(req: NurtureReq):
    with Session(engine) as session:
        try:
            return nurture(req.agent_id, req.dimension, req.delta, req.note, session)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))


@router.post('/reflect/{agent_id}')
def reflect_agent(agent_id: int):
    with Session(engine) as session:
        try:
            return reflection(agent_id, session)
        except ValueError:
            raise HTTPException(status_code=404, detail='agent_not_found')


@router.post('/child')
def create_child(req: ChildReq):
    with Session(engine) as session:
        try:
            return spawn_child(session, req.parent_ids, req.child_name, req.specialization)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))


@router.post('/ingest/{agent_id}')
def ingest(agent_id: int):
    with Session(engine) as session:
        try:
            return ingest_mode_history(session, agent_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='agent_not_found')


@router.post('/archive/{agent_id}')
def archive(agent_id: int):
    with Session(engine) as session:
        soul_state = load_or_create_soul(session, agent_id)
        soul_state['archived'] = True
        soul_state['timeline'].append({'type': 'archived'})
        from app.services.legacy.service import save_soul

        return save_soul(soul_state)


@router.get('/tree')
def family_tree():
    with Session(engine) as session:
        nodes = []
        edges = []
        for agent in session.exec(select(Agent)).all():
            soul_state = load_or_create_soul(session, agent.id)
            nodes.append({'id': agent.id, 'name': agent.name, 'role': agent.role, 'traits': soul_state['traits'], 'avatar_stage': soul_state['avatar_stage'], 'archived': soul_state.get('archived', False)})
            for parent in soul_state.get('lineage', {}).get('parents', []):
                edges.append({'from': parent, 'to': agent.id})
        return {'nodes': nodes, 'edges': edges}


@router.get('/heirloom/{agent_id}.zip')
def heirloom(agent_id: int):
    with Session(engine) as session:
        try:
            path = export_heirloom(session, agent_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='agent_not_found')
    return FileResponse(path, media_type='application/zip', filename=path.name)


@router.post('/import-tree')
def import_tree(payload: dict):
    items = payload.get('items', [])
    with Session(engine) as session:
        for item in items:
            if not session.get(Agent, item.get('agent_id', -1)):
                agent = Agent(name=item.get('agent_name', 'Legacy Agent'), model='llama3.1', role='legacy_import', system_prompt='Imported legacy companion.')
                session.add(agent)
        session.commit()
    return {'imported': len(items)}


@router.post('/family-night-reflection')
def family_night_reflection(payload: dict):
    votes = payload.get('votes', {})
    with Session(engine) as session:
        updated = []
        for agent_id, score in votes.items():
            soul_state = nurture(int(agent_id), 'empathetic', int(score), 'family-night-reflection', session)
            updated.append({'agent_id': agent_id, 'evolution_points': soul_state['evolution_points']})
    return {'updated': updated, 'mode': 'gathering+legacy'}
