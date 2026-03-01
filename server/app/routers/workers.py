from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.models import WorkerJob
from app.schemas import WorkerIn, WorkerHeartbeatIn, WorkerDispatchIn
from app.services.runtime.worker_queue import worker_queue

router = APIRouter(prefix='/api/workers', tags=['workers'])
worker_router = APIRouter(prefix='/api/worker', tags=['worker-node-contract'])


def _job_payload(job: WorkerJob) -> dict:
    return {
        'id': job.id,
        'job_type': job.job_type,
        'status': job.status,
        'priority': job.priority,
        'retries': job.retries,
        'max_retries': job.max_retries,
        'worker_node_id': job.worker_node_id,
        'used_fallback_local': job.used_fallback_local,
        'result_json': job.result_json,
        'error': job.error,
        'created_at': job.created_at.isoformat() if job.created_at else '',
        'updated_at': job.updated_at.isoformat() if job.updated_at else '',
    }


@router.get('')
def list_workers(session: Session = Depends(get_session)):
    return {'ok': True, 'items': worker_queue.list_nodes(session)}


@router.post('/register')
def register_worker(payload: WorkerIn, session: Session = Depends(get_session)):
    node = worker_queue.register(session, payload.name, payload.url, payload.capabilities)
    return {'ok': True, 'worker': node}


@router.post('/heartbeat')
def heartbeat(payload: WorkerHeartbeatIn, session: Session = Depends(get_session)):
    node = worker_queue.heartbeat(session, payload.worker_id, payload.status)
    if not node:
        raise HTTPException(404, 'worker not found')
    return {'ok': True, 'worker': node}


@router.post('/dispatch')
def dispatch_job(payload: WorkerDispatchIn, session: Session = Depends(get_session)):
    job = worker_queue.dispatch(session, payload.job_type, payload.payload, priority=payload.priority)
    return {'ok': True, 'job': _job_payload(job)}


@router.get('/jobs/{job_id}')
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(WorkerJob, job_id)
    if not job:
        raise HTTPException(404, 'job not found')
    return {'ok': True, 'job': _job_payload(job)}


# Worker endpoint contract (for two-PC mode)
@worker_router.post('/register')
def worker_contract_register(payload: dict):
    return {'ok': True, 'accepted': True, 'payload': payload}


@worker_router.post('/heartbeat')
def worker_contract_heartbeat(payload: dict):
    return {'ok': True, 'accepted': True, 'payload': payload}


@worker_router.post('/execute')
def worker_contract_execute(payload: dict):
    return {'ok': True, 'result': {'mode': 'mock-worker', 'echo': payload}}


@worker_router.get('/jobs/{job_id}')
def worker_contract_job(job_id: int):
    return {'ok': True, 'job_id': job_id, 'status': 'done'}
