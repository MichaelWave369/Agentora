from fastapi import APIRouter
from app.services.lan.session import create_join_code, join_request, approve

router = APIRouter(prefix='/api/lan', tags=['lan'])


@router.post('/create')
def create(payload: dict):
    return create_join_code(payload['run_id'])


@router.post('/join')
def join(payload: dict):
    return join_request(payload['join_code'], payload.get('name', 'guest'))


@router.post('/approve')
def approve_join(payload: dict):
    return approve(payload['join_code'], payload['host_token'], payload['token'])
