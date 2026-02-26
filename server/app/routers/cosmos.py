from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.db import engine
from app.services.cosmos.service import (
    branch_timeline,
    collapse_timelines,
    cosmic_reflection,
    create_world,
    eternal_archive,
    export_eternal_seed,
    get_world,
    list_timelines,
    list_worlds,
    prune_timeline,
    storage_warning,
)

router = APIRouter(prefix='/api/cosmos', tags=['cosmos'])


def _world_dict(w):
    return {
        'id': w.id,
        'name': w.name,
        'seed_prompt': w.seed_prompt,
        'status': w.status,
        'warmth': w.warmth,
        'map_json': w.map_json,
        'rules_json': w.rules_json,
        'history_json': w.history_json,
        'created_at': str(w.created_at),
    }


def _timeline_dict(t):
    return {
        'id': t.id,
        'world_id': t.world_id,
        'parent_timeline_id': t.parent_timeline_id,
        'title': t.title,
        'branch_prompt': t.branch_prompt,
        'diff_json': t.diff_json,
        'status': t.status,
        'created_at': str(t.created_at),
    }


class CreateCosmosReq(BaseModel):
    name: str
    seed_prompt: str
    warmth: int = 60


class BranchReq(BaseModel):
    world_id: int
    parent_timeline_id: int = 0
    title: str
    branch_prompt: str


@router.post('/worlds')
def create_cosmos(req: CreateCosmosReq):
    with Session(engine) as session:
        world = create_world(session, req.name, req.seed_prompt, req.warmth)
        return _world_dict(world)


@router.get('/worlds')
def worlds():
    with Session(engine) as session:
        items = [_world_dict(w) for w in list_worlds(session)]
        return {'items': items, 'storage': storage_warning(session)}


@router.get('/world/{world_id}')
def world(world_id: int):
    with Session(engine) as session:
        found = get_world(session, world_id)
        if not found:
            raise HTTPException(status_code=404, detail='world_not_found')
        return _world_dict(found)


@router.post('/branch')
def branch(req: BranchReq):
    with Session(engine) as session:
        if not get_world(session, req.world_id):
            raise HTTPException(status_code=404, detail='world_not_found')
        tl = branch_timeline(session, req.world_id, req.parent_timeline_id, req.title, req.branch_prompt)
        return _timeline_dict(tl)


@router.get('/world/{world_id}/timelines')
def timelines(world_id: int):
    with Session(engine) as session:
        return {'items': [_timeline_dict(t) for t in list_timelines(session, world_id)]}


@router.post('/world/{world_id}/collapse')
def collapse(world_id: int):
    with Session(engine) as session:
        return collapse_timelines(session, world_id)


@router.post('/timeline/{timeline_id}/prune')
def prune(timeline_id: int):
    with Session(engine) as session:
        ok = prune_timeline(session, timeline_id)
        if not ok:
            raise HTTPException(status_code=404, detail='timeline_not_found')
        return {'ok': True, 'timeline_id': timeline_id}


@router.get('/archive')
def archive(query: str = ''):
    with Session(engine) as session:
        return eternal_archive(session, query)


@router.post('/reflection/{world_id}')
def reflection(world_id: int, warmth: int = 60):
    with Session(engine) as session:
        try:
            return cosmic_reflection(session, world_id, warmth)
        except ValueError:
            raise HTTPException(status_code=404, detail='world_not_found')


@router.get('/world/{world_id}/eternal-seed.zip')
def eternal_seed(world_id: int):
    with Session(engine) as session:
        try:
            path = export_eternal_seed(session, world_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='world_not_found')
    return FileResponse(path, media_type='application/zip', filename=path.name)
