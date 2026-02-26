from fastapi import APIRouter

router = APIRouter(prefix='/api/health', tags=['health'])


@router.get('')
def health():
    return {'ok': True, 'service': 'agentora'}
