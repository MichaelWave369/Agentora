import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Capsule, ContextActivation, DuplicateCluster, MemoryConflict, MemoryEdge, MemoryLayer, MemoryMaintenanceJob, MemorySummary, MemoryUsefulnessMetric
from app.services.runtime.conflicts import detect_conflicts_for_run, list_duplicates, upsert_duplicate_cluster
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
    edges = list(session.exec(select(MemoryEdge).where((MemoryEdge.from_capsule_id == capsule_id) | (MemoryEdge.to_capsule_id == capsule_id))))
    summary = session.exec(select(MemorySummary).where(MemorySummary.summary_capsule_id == capsule_id)).first()
    return {'ok': True, 'capsule': cap, 'children': children, 'edges': edges, 'summary': summary}


@router.get('/capsules/{capsule_id}/lineage')
def capsule_lineage(capsule_id: int, session: Session = Depends(get_session)):
    cap = session.get(Capsule, capsule_id)
    if not cap:
        raise HTTPException(404, 'capsule not found')
    root_id = cap.lineage_root_id or cap.id
    root = session.get(Capsule, root_id)
    descendants = list(session.exec(select(Capsule).where((Capsule.lineage_root_id == root_id) | (Capsule.id == root_id)).order_by(Capsule.id)))
    summaries = list(session.exec(select(MemorySummary).where(MemorySummary.source_group_key == f'capsule:{root_id}')))
    return {'ok': True, 'root': root, 'capsule': cap, 'descendants': descendants, 'summaries': summaries}


@router.get('/capsules/{capsule_id}/neighbors')
def capsule_neighbors(capsule_id: int, session: Session = Depends(get_session)):
    edges = list(session.exec(select(MemoryEdge).where((MemoryEdge.from_capsule_id == capsule_id) | (MemoryEdge.to_capsule_id == capsule_id)).order_by(MemoryEdge.weight.desc())))
    neighbors = []
    for e in edges:
        nid = e.to_capsule_id if e.from_capsule_id == capsule_id else e.from_capsule_id
        ncap = session.get(Capsule, nid)
        if ncap:
            neighbors.append({'edge': e, 'capsule': ncap})
    return {'ok': True, 'items': neighbors}


@router.get('/runs/{run_id}/contexts')
def run_contexts(run_id: int, session: Session = Depends(get_session)):
    rows = list(session.exec(select(ContextActivation).where(ContextActivation.run_id == run_id).order_by(ContextActivation.id.desc())))
    items = []
    for row in rows:
        try:
            reason = json.loads(row.reason_json)
        except Exception:
            reason = {'raw': row.reason_json}
        cap = session.get(Capsule, row.capsule_id)
        items.append({'id': row.id, 'run_id': row.run_id, 'capsule_id': row.capsule_id, 'layer': row.layer, 'query': row.query, 'score': row.score, 'admitted': row.admitted, 'reason': reason, 'capsule': cap, 'created_at': row.created_at.isoformat()})
    return {'ok': True, 'items': items}


@router.get('/runs/{run_id}/retrieval')
def run_retrieval(run_id: int, session: Session = Depends(get_session)):
    rows = list(session.exec(select(ContextActivation).where(ContextActivation.run_id == run_id).order_by(ContextActivation.id.desc()).limit(40)))
    return {'ok': True, 'run_id': run_id, 'items': [{'capsule_id': r.capsule_id, 'layer': r.layer, 'score': r.score, 'reason': json.loads(r.reason_json or '{}')} for r in rows]}


@router.get('/runs/{run_id}/trace')
def run_memory_trace(run_id: int, session: Session = Depends(get_session)):
    allow = {'memory_layer_query', 'context_admission', 'retrieval_score_breakdown', 'context_admission_reason', 'memory_promotion', 'memory_demotion', 'memory_refinement', 'graph_rerank', 'archive_promotion', 'maintenance_job', 'maintenance_summary', 'memory_conflict_detected', 'memory_conflict_admitted', 'duplicate_capsule_detected', 'memory_usefulness_update'}
    trace = [t for t in get_run_trace(session, run_id) if t['event_type'] in allow]
    return {'ok': True, 'run_id': run_id, 'trace': trace}


@router.get('/health')
def memory_health(session: Session = Depends(get_session)):
    capsules = list(session.exec(select(Capsule)))
    by_layer: dict[str, int] = {}
    for c in capsules:
        by_layer[c.memory_layer] = by_layer.get(c.memory_layer, 0) + 1
    jobs = list(session.exec(select(MemoryMaintenanceJob).order_by(MemoryMaintenanceJob.id.desc()).limit(10)))
    last_job = jobs[0] if jobs else None
    return {
        'ok': True,
        'counts_by_layer': by_layer,
        'hot_count': sum(1 for c in capsules if c.memory_layer in {'L0_HOT', 'L1_SHORT'}),
        'cold_count': sum(1 for c in capsules if c.memory_layer == 'L5_COLD'),
        'conflict_count': len(list(session.exec(select(MemoryConflict)))),
        'duplicate_count': len(list(session.exec(select(DuplicateCluster).where(DuplicateCluster.cluster_size > 1)))),
        'active_context_runs': len({r.run_id for r in session.exec(select(ContextActivation))}),
        'maintenance_status': [{'id': j.id, 'status': j.status, 'job_type': j.job_type, 'used_worker': j.used_worker, 'details_json': j.details_json, 'updated_at': j.updated_at.isoformat()} for j in jobs],
        'last_maintenance': {'id': last_job.id, 'status': last_job.status} if last_job else None,
    }


@router.get('/conflicts')
def memory_conflicts(session: Session = Depends(get_session)):
    rows = list(session.exec(select(MemoryConflict).order_by(MemoryConflict.conflict_score.desc()).limit(100)))
    return {'ok': True, 'items': rows}


@router.get('/duplicates')
def memory_duplicates(session: Session = Depends(get_session)):
    return {'ok': True, 'items': list_duplicates(session)}


@router.post('/maintenance/run')
def memory_maintenance(payload: dict | None = None, session: Session = Depends(get_session)):
    payload = payload or {}
    job = run_maintenance(session, run_id=payload.get('run_id'), try_worker=bool(payload.get('try_worker', True)))
    return {'ok': True, 'job': job}


@router.post('/maintenance/conflicts')
def maintenance_conflicts(payload: dict | None = None, session: Session = Depends(get_session)):
    payload = payload or {}
    run_id = int(payload.get('run_id', 0))
    if run_id <= 0:
        raise HTTPException(400, 'run_id required')
    conflicts = detect_conflicts_for_run(session, run_id)
    return {'ok': True, 'created': len(conflicts)}


@router.post('/maintenance/duplicates')
def maintenance_duplicates(session: Session = Depends(get_session)):
    caps = list(session.exec(select(Capsule).order_by(Capsule.id.desc()).limit(200)))
    touched = 0
    for c in caps:
        upsert_duplicate_cluster(session, c)
        touched += 1
    return {'ok': True, 'touched_capsules': touched, 'clusters': list_duplicates(session)}


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
