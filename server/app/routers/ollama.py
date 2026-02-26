from fastapi import APIRouter
from app.services.ollama_client import OllamaClient

router = APIRouter(prefix='/api/ollama', tags=['ollama'])
client = OllamaClient()


@router.get('/models')
async def models():
    return {'models': await client.list_models()}


@router.post('/test')
async def test_conn():
    try:
        m = await client.list_models()
        return {'ok': True, 'models': m}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
