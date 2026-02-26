from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import engine
from app.services.world_garden.service import constellation_links, cross_pollinate, harvest_festival, infinite_bloom, world_map

router = APIRouter(prefix='/api/world-garden', tags=['world-garden'])


class BloomReq(BaseModel):
    node_id: int
    reason: str = 'new creation'


class PollinateReq(BaseModel):
    from_node: int
    to_node: int
    preview_only: bool = True


@router.get('/map')
def map_view():
    with Session(engine) as session:
        return world_map(session)


@router.post('/bloom')
def bloom(req: BloomReq):
    with Session(engine) as session:
        try:
            return infinite_bloom(session, req.node_id, req.reason)
        except ValueError:
            raise HTTPException(status_code=404, detail='node_not_found')


@router.post('/cross-pollinate')
def pollinate(req: PollinateReq):
    with Session(engine) as session:
        try:
            return cross_pollinate(session, req.from_node, req.to_node, req.preview_only)
        except ValueError:
            raise HTTPException(status_code=404, detail='node_not_found')


@router.get('/constellations')
def constellations():
    with Session(engine) as session:
        return constellation_links(session)


@router.post('/festival/harvest')
def festival_harvest():
    with Session(engine) as session:
        return harvest_festival(session)
