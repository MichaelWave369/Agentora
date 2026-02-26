from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session

from app.db import engine
from app.services.open_cosmos.service import (
    global_wisdom_archive,
    import_package,
    list_shares,
    living_legacy_network,
    revoke_share,
    share_cosmos,
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
