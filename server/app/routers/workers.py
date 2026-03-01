from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.schemas import WorkerIn
from app.services.runtime.worker_queue import worker_queue

router = APIRouter(prefix='/api/workers', tags=['workers'])


@router.get('')
def list_workers(session: Session = Depends(get_session)):
    return {'ok': True, 'items': worker_queue.list_nodes(session)}


@router.post('/register')
def register_worker(payload: WorkerIn, session: Session = Depends(get_session)):
    node = worker_queue.register(session, payload.name, payload.url, payload.capabilities)
    return {'ok': True, 'worker': node}


@router.post('/dispatch')
def dispatch_job(payload: dict, session: Session = Depends(get_session)):
    job = worker_queue.dispatch(session, payload.get('job_type', 'generic'), payload.get('payload', {}))
    return {'ok': True, 'job': job}
