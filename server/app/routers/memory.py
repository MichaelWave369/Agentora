import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Capsule, ContextActivation, MemoryEdge, MemoryLayer, MemoryMaintenanceJob
from app.services.runtime.maintenance import demote_capsule, promote_capsule, refine_capsule, run_maintenance
from app.services.runtime.trace import get_run_trace

router = APIRouter(prefix='/api/memory', tags=['memory'])


@router.get('/layers')
def list_layers(session: Session = Depends(get_session)):
    configured = list(session.exec(select(MemoryLayer).order_by(MemoryLayer.priority)))
    if configured:
        return {'ok': True, 'items': configured}
    defaults = [
        {'name': 'L0_HOT', 'priority': 0, 'description': 'Active run state'},
        {'name': 'L1_SHORT', 'priority': 1, 'description': 'Short-term capsules'},
        {'name': 'L2_SESSION', 'priority': 2, 'description': 'Session/project memory'},
        {'name': 'L3_DURABLE', 'priority': 3, 'description': 'Durable identity memory'},
        {'name': 'L4_SPARSE', 'priority': 4, 'description': 'Sparse activated context'},
        {'name': 'L5_COLD', 'priority': 5, 'description': 'Cold archive'},
    ]
    return {'ok': True, 'items': defaults}


@router.get('/capsules/{capsule_id}')
def capsule_detail(capsule_id: int, session: Session = Depends(get_session)):
    cap = session.get(Capsule, capsule_id)
    if not cap:
        raise HTTPException(404, 'capsule not found')
    children = list(session.exec(select(Capsule).where(Capsule.parent_capsule_id == capsule_id)))
    edges = list(
        session.exec(select(MemoryEdge).where((MemoryEdge.from_capsule_id == capsule_id) | (MemoryEdge.to_capsule_id == capsule_id)))
    )
    return {'ok': True, 'capsule': cap, 'children': children, 'edges': edges}


@router.get('/runs/{run_id}/contexts')
def run_contexts(run_id: int, session: Session = Depends(get_session)):
    rows = list(session.exec(select(ContextActivation).where(ContextActivation.run_id == run_id).order_by(ContextActivation.id.desc())))
    items = []
    for row in rows:
        try:
            reason = json.loads(row.reason_json)
        except Exception:
            reason = {'raw': row.reason_json}
        items.append(
            {
                'id': row.id,
                'run_id': row.run_id,
                'capsule_id': row.capsule_id,
                'layer': row.layer,
                'query': row.query,
                'score': row.score,
                'admitted': row.admitted,
                'reason': reason,
                'created_at': row.created_at.isoformat(),
            }
        )
    return {'ok': True, 'items': items}


@router.get('/runs/{run_id}/trace')
def run_memory_trace(run_id: int, session: Session = Depends(get_session)):
    trace = [
        t
        for t in get_run_trace(session, run_id)
        if t['event_type']
        in {
            'memory_layer_query',
            'context_admission',
            'memory_promotion',
            'memory_demotion',
            'memory_refinement',
            'graph_rerank',
            'archive_promotion',
            'maintenance_job',
        }
    ]
    return {'ok': True, 'run_id': run_id, 'trace': trace}


@router.post('/maintenance/run')
def memory_maintenance(payload: dict | None = None, session: Session = Depends(get_session)):
    payload = payload or {}
    job = run_maintenance(session, run_id=payload.get('run_id'), try_worker=bool(payload.get('try_worker', True)))
    return {'ok': True, 'job': job}


@router.post('/capsules/{capsule_id}/promote')
def promote(capsule_id: int, session: Session = Depends(get_session)):
    cap = promote_capsule(session, capsule_id, reason='api')
    if not cap:
        raise HTTPException(404, 'capsule not found')
    return {'ok': True, 'capsule': cap}


@router.post('/capsules/{capsule_id}/demote')
def demote(capsule_id: int, session: Session = Depends(get_session)):
    cap = demote_capsule(session, capsule_id, reason='api')
    if not cap:
        raise HTTPException(404, 'capsule not found')
    return {'ok': True, 'capsule': cap}


@router.post('/capsules/{capsule_id}/refine')
def refine(capsule_id: int, session: Session = Depends(get_session)):
    result = refine_capsule(session, capsule_id)
    if not result.get('ok'):
        raise HTTPException(404, result.get('error', 'refine_failed'))
    return result
