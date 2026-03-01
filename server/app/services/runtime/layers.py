from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Capsule, CapsuleEmbedding, ContextActivation, MemoryCapsuleState, MemoryConflict
from app.services.runtime.conflicts import detect_conflicts_for_run, upsert_duplicate_cluster
from app.services.runtime.graph import graph_rerank, reinforce_edge


LAYER_ORDER = ['L0_HOT', 'L1_SHORT', 'L2_SESSION', 'L3_DURABLE', 'L4_SPARSE', 'L5_COLD']


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a[:n], b[:n]))
    na = math.sqrt(sum(x * x for x in a[:n]))
    nb = math.sqrt(sum(y * y for y in b[:n]))
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def _decay_value(capsule: Capsule, now: datetime) -> float:
    dt = (now - capsule.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600.0
    horizon = max(0.0, dt)
    if capsule.decay_class == 'long':
        return settings.agentora_memory_decay_long ** horizon
    if capsule.decay_class == 'medium':
        return settings.agentora_memory_decay_medium ** horizon
    return settings.agentora_memory_decay_short ** horizon


def _layer_weight(layer: str) -> float:
    return settings.memory_layer_weights.get(layer, 1.0)


def _project_match(capsule: Capsule, project_key: str, session_key: str) -> float:
    if project_key and capsule.project_key and project_key == capsule.project_key:
        return settings.agentora_project_memory_boost
    if session_key and capsule.session_key and session_key == capsule.session_key:
        return max(1.0, settings.agentora_project_memory_boost - 0.1)
    return 0.0


def _score_capsule(capsule: Capsule, similarity: float, project_key: str, session_key: str) -> dict[str, float]:
    now = datetime.now(timezone.utc)
    factors = {
        'semantic': similarity,
        'decay': _decay_value(capsule, now),
        'access_frequency': min(1.0, capsule.retrieval_count / 16.0),
        'trust': max(0.0, min(1.0, capsule.trust_score)),
        'consolidation': max(0.0, min(1.0, capsule.consolidation_score)),
        'project_match': _project_match(capsule, project_key, session_key),
        'layer_weight': _layer_weight(capsule.memory_layer),
        'duplicate_penalty': max(0.0, capsule.duplicate_score * 0.2),
        'conflict_penalty': 0.12 if capsule.contradiction_flag else 0.0,
    }
    base = (
        factors['semantic'] * 0.46
        + factors['decay'] * 0.17
        + factors['access_frequency'] * 0.08
        + factors['trust'] * 0.08
        + factors['consolidation'] * 0.08
        + min(1.0, factors['project_match']) * 0.07
    )
    final = max(0.0, (base - factors['duplicate_penalty'] - factors['conflict_penalty']) * factors['layer_weight'])
    factors['pre_graph_score'] = final
    factors['final_score'] = final
    return factors


def layered_retrieval(
    session: Session,
    query_vector: list[float],
    query: str,
    run_id: int,
    top_k: int | None = None,
    project_key: str | None = None,
    session_key: str | None = None,
) -> dict[str, Any]:
    top_k = top_k or settings.agentora_context_top_k
    project_key = project_key or f'run:{run_id}'
    session_key = session_key or f'run:{run_id}'

    stmt = select(Capsule, CapsuleEmbedding).join(CapsuleEmbedding, Capsule.id == CapsuleEmbedding.capsule_id)
    stmt = stmt.where(Capsule.run_id == run_id)
    rows = list(session.exec(stmt))
    if not rows and settings.agentora_global_memory_fallback_enabled:
        stmt = select(Capsule, CapsuleEmbedding).join(CapsuleEmbedding, Capsule.id == CapsuleEmbedding.capsule_id)
        rows = list(session.exec(stmt))

    candidates: list[dict[str, Any]] = []
    low_score_candidates: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    for cap, emb in rows:
        if cap.memory_layer == 'L5_COLD' and cap.archive_status == 'cold':
            continue
        if cap.text in seen_text:
            continue
        seen_text.add(cap.text)
        if not settings.agentora_cross_project_memory_enabled and cap.project_key and cap.project_key != project_key and rows and cap.run_id != run_id:
            continue
        try:
            vec = json.loads(emb.vector_json)
        except Exception:
            vec = []
        factors = _score_capsule(cap, _cosine_similarity(query_vector, vec), project_key=project_key, session_key=session_key)
        if factors['final_score'] < settings.agentora_context_min_score:
            low_score_candidates.append({
                'capsule_id': cap.id,
                'text': cap.text,
                'source': cap.source,
                'run_id': cap.run_id,
                'is_summary': cap.is_summary,
                'created_at': cap.created_at.isoformat(),
                'layer': cap.memory_layer,
                'score': factors['final_score'],
                'score_breakdown': factors,
                'conflict_flag': cap.contradiction_flag,
                'duplicate_cluster_id': cap.duplicate_cluster_id,
                'duplicate_score': cap.duplicate_score,
            })
            continue
        upsert_duplicate_cluster(session, cap)
        candidates.append(
            {
                'capsule_id': cap.id,
                'text': cap.text,
                'source': cap.source,
                'run_id': cap.run_id,
                'is_summary': cap.is_summary,
                'created_at': cap.created_at.isoformat(),
                'layer': cap.memory_layer,
                'score': factors['final_score'],
                'score_breakdown': factors,
                'conflict_flag': cap.contradiction_flag,
                'duplicate_cluster_id': cap.duplicate_cluster_id,
                'duplicate_score': cap.duplicate_score,
            }
        )

    if not candidates and low_score_candidates:
        low_score_candidates.sort(key=lambda x: x['score'], reverse=True)
        candidates = low_score_candidates[: max(top_k * 2, 2)]

    candidates.sort(key=lambda x: (LAYER_ORDER.index(x['layer']) if x['layer'] in LAYER_ORDER else 99, -x['score']))
    base = candidates[: max(top_k * 3, 1)]
    base_scores = {int(x['capsule_id']): float(x['score']) for x in base}

    graph_boosts: dict[int, float] = {k: 0.0 for k in base_scores}
    if settings.agentora_enable_graph_rerank:
        reranked = graph_rerank(session, list(base_scores.keys()), base_scores)
        for item in base:
            cid = int(item['capsule_id'])
            graph_boosts[cid] = max(0.0, reranked.get(cid, item['score']) - item['score'])
            item['score_breakdown']['graph_rerank'] = graph_boosts[cid]
            item['score'] = reranked.get(cid, item['score'])
            item['score_breakdown']['final_score'] = item['score']

    if settings.agentora_duplicate_suppression_enabled:
        deduped: list[dict[str, Any]] = []
        seen_cluster: set[int] = set()
        for item in sorted(base, key=lambda x: x['score'], reverse=True):
            cluster_id = item.get('duplicate_cluster_id') or 0
            if cluster_id and cluster_id in seen_cluster:
                continue
            if cluster_id:
                seen_cluster.add(cluster_id)
            deduped.append(item)
        base = deduped
    else:
        base.sort(key=lambda x: x['score'], reverse=True)

    admitted: list[dict[str, Any]] = []
    layer_budgets = settings.context_layer_budgets
    for item in base:
        if len(admitted) >= settings.agentora_max_active_contexts:
            break
        layer = item['layer']
        if sum(1 for x in admitted if x['layer'] == layer) >= layer_budgets.get(layer, settings.agentora_max_active_contexts):
            continue
        reason = {
            'admission': 'score_above_threshold',
            'rank_score': round(item['score'], 5),
            'top_factors': sorted(item['score_breakdown'].items(), key=lambda x: abs(float(x[1])) if isinstance(x[1], (int, float)) else 0, reverse=True)[:4],
            'conflict_flag': item['conflict_flag'],
            'duplicate_cluster_id': item.get('duplicate_cluster_id'),
        }
        session.add(ContextActivation(run_id=run_id, capsule_id=item['capsule_id'], layer=layer, query=query, score=item['score'], reason_json=json.dumps(reason), admitted=True))
        item['admission_reason'] = reason
        admitted.append(item)

    for item in admitted:
        cap = session.get(Capsule, item['capsule_id'])
        if not cap:
            continue
        cap.retrieval_count += 1
        cap.last_accessed_at = datetime.utcnow()
        cap.recency_score = min(1.0, cap.recency_score + 0.03)
        session.add(cap)
        state = session.exec(select(MemoryCapsuleState).where(MemoryCapsuleState.capsule_id == cap.id)).first() or MemoryCapsuleState(capsule_id=cap.id, layer=cap.memory_layer)
        state.retrieval_count += 1
        state.usage_count += 1
        state.last_accessed_at = datetime.utcnow()
        state.updated_at = datetime.utcnow()
        session.add(state)

    top_ids = [a['capsule_id'] for a in admitted[:4]]
    for i, source in enumerate(top_ids):
        for target in top_ids[i + 1 :]:
            reinforce_edge(session, source, target, edge_type='co_retrieval', weight=0.65, confidence=0.65)

    conflicts = detect_conflicts_for_run(session, run_id)
    conflict_ids = {c.left_capsule_id for c in conflicts} | {c.right_capsule_id for c in conflicts}
    for item in admitted:
        if item['capsule_id'] in conflict_ids:
            item['conflict_flag'] = True

    session.commit()
    retrieval_meta = {
        'run_id': run_id,
        'query': query,
        'layers_used': sorted({x['layer'] for x in admitted}, key=lambda x: LAYER_ORDER.index(x) if x in LAYER_ORDER else 99),
        'candidate_count': len(candidates),
        'admitted_count': len(admitted),
        'conflict_count': len(list(session.exec(select(MemoryConflict).where((MemoryConflict.left_capsule_id.in_(top_ids)) | (MemoryConflict.right_capsule_id.in_(top_ids)))))) if top_ids else 0,
    }
    return {'items': admitted[:top_k], 'meta': retrieval_meta}
