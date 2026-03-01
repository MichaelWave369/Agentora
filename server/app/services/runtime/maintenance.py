from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Capsule, MemoryConflict, MemoryEdge, MemoryMaintenanceJob, MemorySummary
from app.services.runtime.router import route_worker_job
from app.services.runtime.conflicts import detect_conflicts_for_run, upsert_duplicate_cluster
from app.services.runtime.trace import add_trace


LAYER_PROMOTE = {
    'L5_COLD': 'L4_SPARSE',
    'L4_SPARSE': 'L3_DURABLE',
    'L3_DURABLE': 'L2_SESSION',
    'L2_SESSION': 'L1_SHORT',
    'L1_SHORT': 'L0_HOT',
}
LAYER_DEMOTE = {v: k for k, v in LAYER_PROMOTE.items()}


def promote_capsule(session: Session, capsule_id: int, reason: str = 'manual') -> Capsule | None:
    cap = session.get(Capsule, capsule_id)
    if not cap:
        return None
    cap.memory_layer = LAYER_PROMOTE.get(cap.memory_layer, cap.memory_layer)
    if cap.memory_layer != 'L5_COLD':
        cap.archive_status = 'active'
    cap.last_accessed_at = datetime.utcnow()
    session.add(cap)
    session.commit()
    return cap


def demote_capsule(session: Session, capsule_id: int, reason: str = 'manual') -> Capsule | None:
    cap = session.get(Capsule, capsule_id)
    if not cap:
        return None
    cap.memory_layer = LAYER_DEMOTE.get(cap.memory_layer, cap.memory_layer)
    if cap.memory_layer == 'L5_COLD':
        cap.archive_status = 'cold'
    session.add(cap)
    session.commit()
    return cap


def refine_capsule(session: Session, capsule_id: int) -> dict:
    cap = session.get(Capsule, capsule_id)
    if not cap:
        return {'ok': False, 'error': 'capsule_not_found'}
    if not settings.agentora_enable_adaptive_refinement:
        return {'ok': True, 'created': 0, 'reason': 'adaptive_refinement_disabled'}

    text = cap.text or ''
    if len(text) < 2200 and cap.contradiction_flag is False:
        return {'ok': True, 'created': 0, 'reason': 'not_dense_enough'}

    chunks = [x.strip() for x in text.replace('\n', ' ').split('.') if x.strip()]
    if len(chunks) < 2:
        return {'ok': True, 'created': 0, 'reason': 'no_split_candidate'}

    created = 0
    root_id = cap.lineage_root_id or cap.id
    for idx, chunk in enumerate(chunks[:6]):
        child = Capsule(
            run_id=cap.run_id,
            attachment_id=cap.attachment_id,
            source=cap.source,
            chunk_index=idx,
            text=chunk[:1000],
            tags_json=cap.tags_json,
            is_summary=False,
            memory_layer='L2_SESSION',
            source_type='refinement',
            project_key=cap.project_key,
            session_key=cap.session_key,
            archive_status='active',
            decay_class='medium',
            confidence=max(0.45, cap.confidence * 0.95),
            consolidation_score=max(0.45, cap.consolidation_score * 0.9),
            trust_score=cap.trust_score,
            created_from_run_id=cap.run_id,
            parent_capsule_id=cap.id,
            lineage_root_id=root_id,
        )
        session.add(child)
        created += 1

    summary_text = ' '.join(chunks[:3])[:900]
    summary = Capsule(
        run_id=cap.run_id,
        attachment_id=cap.attachment_id,
        source=cap.source,
        chunk_index=0,
        text=summary_text,
        tags_json=cap.tags_json,
        is_summary=True,
        memory_layer='L1_SHORT',
        source_type='summary',
        project_key=cap.project_key,
        session_key=cap.session_key,
        archive_status='active',
        decay_class='medium',
        confidence=min(1.0, cap.confidence + 0.1),
        consolidation_score=min(1.0, cap.consolidation_score + 0.2),
        trust_score=cap.trust_score,
        created_from_run_id=cap.run_id,
        parent_capsule_id=cap.id,
        lineage_root_id=root_id,
    )
    session.add(summary)
    session.commit()
    session.refresh(summary)

    session.add(
        MemorySummary(
            summary_capsule_id=summary.id,
            source_group_key=f'capsule:{cap.id}',
            member_capsule_ids_json=json.dumps([cap.id]),
            detail_level='refinement',
            refreshed_at=datetime.utcnow(),
        )
    )
    session.commit()
    return {'ok': True, 'created': created + 1, 'summary_capsule_id': summary.id}


def run_maintenance(session: Session, run_id: int | None = None, try_worker: bool = True) -> MemoryMaintenanceJob:
    job = MemoryMaintenanceJob(run_id=run_id, job_type='memory_maintenance', status='running', details_json='{}')
    session.add(job)
    session.commit()
    session.refresh(job)

    if try_worker:
        worker_job = route_worker_job(session, 'memory_maintenance', {'run_id': run_id}, priority=4)
        job.used_worker = not worker_job.used_fallback_local

    promoted = 0
    demoted = 0
    refined = 0
    duplicates = 0
    weak_edges_pruned = 0
    conflicts_detected = 0
    now = datetime.utcnow()
    old_cutoff = now - timedelta(days=settings.agentora_cold_archive_after_days)

    caps = list(session.exec(select(Capsule)))
    for cap in caps:
        utility = (cap.success_count - cap.failure_count) / max(1, cap.retrieval_count)
        utility = (utility + cap.trust_score + cap.consolidation_score) / 3.0
        if utility >= settings.agentora_memory_promotion_threshold and cap.memory_layer != 'L0_HOT':
            promote_capsule(session, cap.id, reason='maintenance')
            promoted += 1
        elif utility <= settings.agentora_memory_demotion_threshold and cap.memory_layer != 'L5_COLD':
            demote_capsule(session, cap.id, reason='maintenance')
            demoted += 1
        if cap.created_at < old_cutoff and cap.memory_layer in {'L3_DURABLE', 'L4_SPARSE'}:
            cap.memory_layer = 'L5_COLD'
            cap.archive_status = 'cold'
            session.add(cap)
            demoted += 1
        cluster = upsert_duplicate_cluster(session, cap)
        if cluster.cluster_size > 1:
            duplicates += 1
        if settings.agentora_enable_adaptive_refinement and len(cap.text or '') > 2600:
            result = refine_capsule(session, cap.id)
            if result.get('ok') and result.get('created', 0) > 0:
                refined += 1

    if run_id:
        conflicts_detected = len(detect_conflicts_for_run(session, run_id))

    edges = list(session.exec(select(MemoryEdge)))
    for edge in edges:
        if edge.weight < 0.18 and edge.usage_count < 2:
            session.delete(edge)
            weak_edges_pruned += 1
    session.commit()

    details = {'promoted': promoted, 'demoted': demoted, 'refined': refined, 'duplicates': duplicates, 'weak_edges_pruned': weak_edges_pruned, 'conflicts_detected': conflicts_detected}
    job.status = 'done'
    job.details_json = json.dumps(details)
    job.updated_at = datetime.utcnow()
    session.add(job)
    session.commit()
    session.refresh(job)
    if run_id:
        add_trace(session, run_id, 'maintenance_summary', {'job_id': job.id, 'details': details, 'used_worker': job.used_worker}, agent_id=0)
        session.commit()
    return job
