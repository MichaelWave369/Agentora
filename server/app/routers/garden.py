from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session

from app.db import engine
from app.services.garden.service import advance_season, community_garden, garden_map, harvest_bed, tend_bed

router = APIRouter(prefix='/api/garden', tags=['garden'])


class TendReq(BaseModel):
    bed_id: int
    gardener_role: str = 'Waterer'
    note: str = ''


@router.get('/map')
def map_view():
    with Session(engine) as session:
        return garden_map(session)


@router.post('/tend')
def tend(req: TendReq):
    with Session(engine) as session:
        try:
            return tend_bed(session, req.bed_id, req.gardener_role, req.note)
        except ValueError:
            raise HTTPException(status_code=404, detail='garden_bed_not_found')


@router.post('/season/advance')
def season_advance():
    with Session(engine) as session:
        return advance_season(session)


@router.post('/harvest/{bed_id}')
def harvest(bed_id: int):
    with Session(engine) as session:
        try:
            return harvest_bed(session, bed_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='garden_bed_not_found')


@router.get('/community')
def community():
    with Session(engine) as session:
        return community_garden(session)
