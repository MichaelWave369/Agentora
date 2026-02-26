from fastapi import APIRouter
from app.services.tools.registry import registry

router = APIRouter(prefix='/api/tools', tags=['tools'])


@router.get('')
def list_tools():
    return {'tools': registry.list()}
