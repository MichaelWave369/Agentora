from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.services.runtime.capsules import search_capsules
from app.services.runtime.schemas import CapsuleSearchRequest

router = APIRouter(prefix='/api/capsules', tags=['capsules'])


@router.post('/search')
async def capsule_search(payload: CapsuleSearchRequest, session: Session = Depends(get_session)):
    items = await search_capsules(session=session, query=payload.query, run_id=payload.run_id, top_k=payload.top_k, source_weight=payload.source_weight)
    return {'ok': True, 'items': items}
