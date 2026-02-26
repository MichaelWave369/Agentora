from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.db import engine
from app.services.open_cosmos.service import (
    community_spotlight,
    cross_cosmos_visit,
    forecast_values_2050,
    global_wisdom_archive,
    grand_synthesis,
    import_package,
    list_shares,
    living_archive_timeline,
    living_legacy_network,
    query_living_archive,
    revoke_share,
    share_cosmos,
    submit_to_community,
    wisdom_exchange,
)

router = APIRouter(prefix='/api/open-cosmos', tags=['open-cosmos'])


class ShareReq(BaseModel):
    world_id: int
    visibility: str = 'private'
    wisdom_mode: str = 'anonymized'
    contributors: list[dict] = []


class ImportReq(BaseModel):
    package_name: str
    keep_timelines: list[str] = []


class WisdomReq(BaseModel):
    enabled: bool = False


class ArchiveQueryReq(BaseModel):
    question: str


class VisitReq(BaseModel):
    from_world_id: int
    to_world_id: int


class ExchangeReq(BaseModel):
    world_a: int
    world_b: int


class SynthesisReq(BaseModel):
    world_ids: list[int]
    title: str = 'Meta Cosmos'


class ForecastReq(BaseModel):
    world_ids: list[int]


class SubmitReq(BaseModel):
    share_id: int


@router.post('/share')
def share(req: ShareReq):
    with Session(engine) as session:
        try:
            shared = share_cosmos(session, req.world_id, req.visibility, req.wisdom_mode, req.contributors)
            return {'id': shared.id, 'package_name': shared.package_name, 'message': 'Your cosmos is now safely shared with the community ❤️'}
        except ValueError:
            raise HTTPException(status_code=404, detail='world_not_found')


@router.get('/shares')
def shares():
    with Session(engine) as session:
        return {'items': list_shares(session)}


@router.get('/download/{package_name}')
def download(package_name: str):
    path = f'server/data/open_cosmos/{package_name}'
    return FileResponse(path, media_type='application/octet-stream', filename=package_name)


@router.post('/import')
def import_agentora(req: ImportReq):
    with Session(engine) as session:
        try:
            return import_package(session, req.package_name, req.keep_timelines)
        except ValueError:
            raise HTTPException(status_code=404, detail='package_not_found')


@router.post('/revoke/{share_id}')
def revoke(share_id: int):
    with Session(engine) as session:
        ok = revoke_share(session, share_id)
        if not ok:
            raise HTTPException(status_code=404, detail='share_not_found')
        return {'ok': True}


@router.post('/wisdom')
def wisdom(req: WisdomReq):
    with Session(engine) as session:
        return global_wisdom_archive(session, req.enabled)


@router.get('/network')
def network():
    with Session(engine) as session:
        return living_legacy_network(session)


@router.get('/archive/timeline')
def archive_timeline():
    with Session(engine) as session:
        return {'items': living_archive_timeline(session)}


@router.post('/archive/query')
def archive_query(req: ArchiveQueryReq):
    with Session(engine) as session:
        return query_living_archive(session, req.question)


@router.post('/visit')
def visit(req: VisitReq):
    with Session(engine) as session:
        try:
            return cross_cosmos_visit(session, req.from_world_id, req.to_world_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='world_not_found')


@router.post('/exchange')
def exchange(req: ExchangeReq):
    with Session(engine) as session:
        try:
            return wisdom_exchange(session, req.world_a, req.world_b)
        except ValueError:
            raise HTTPException(status_code=404, detail='world_not_found')


@router.post('/synthesis')
def synthesis(req: SynthesisReq):
    with Session(engine) as session:
        try:
            return grand_synthesis(session, req.world_ids, req.title)
        except ValueError:
            raise HTTPException(status_code=404, detail='world_not_found')


@router.post('/forecast')
def forecast(req: ForecastReq):
    with Session(engine) as session:
        return forecast_values_2050(session, req.world_ids)


@router.get('/spotlight')
def spotlight():
    with Session(engine) as session:
        return {'items': community_spotlight(session)}


@router.post('/submit')
def submit(req: SubmitReq):
    with Session(engine) as session:
        try:
            return submit_to_community(session, req.share_id)
        except ValueError:
            raise HTTPException(status_code=404, detail='share_not_found')
