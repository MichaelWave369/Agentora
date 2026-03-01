from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Capsule, CapsuleEmbedding, ContextActivation, MemoryCapsuleState
from app.services.runtime.graph import graph_rerank, reinforce_edge


LAYER_ORDER = ['L0_HOT', 'L1_SHORT', 'L2_SESSION', 'L3_DURABLE', 'L4_SPARSE', 'L5_COLD']


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    if n == 0:
        return 0.0
    a = a[:n]
    b = b[:n]
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _decay_value(capsule: Capsule, now: datetime) -> float:
    dt = (now - capsule.created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600.0
    horizon = max(0.0, dt)
    if capsule.decay_class == 'long':
        return settings.agentora_memory_decay_long ** horizon
    if capsule.decay_class == 'medium':
        return settings.agentora_memory_decay_medium ** horizon
    return settings.agentora_memory_decay_short ** horizon


def _project_match(capsule: Capsule, project_key: str | None, session_key: str | None) -> float:
    if project_key and capsule.project_key and capsule.project_key == project_key:
        return 1.0
    if session_key and capsule.session_key and capsule.session_key == session_key:
        return 0.8
    return 0.0


def _layer_weight(layer: str) -> float:
    return settings.memory_layer_weights.get(layer, 1.0)


def score_capsule(capsule: Capsule, similarity: float, project_key: str | None, session_key: str | None) -> tuple[float, dict[str, float]]:
    now = datetime.now(timezone.utc)
    decay = _decay_value(capsule, now)
    access = min(1.0, capsule.retrieval_count / 16.0)
    project_score = _project_match(capsule, project_key=project_key, session_key=session_key)
    trust = max(0.0, min(1.0, capsule.trust_score))
    consolid = max(0.0, min(1.0, capsule.consolidation_score))
    layer_w = _layer_weight(capsule.memory_layer)
    recency = max(0.05, capsule.recency_score)

    score = (
        similarity * 0.45
        + decay * 0.16
        + access * 0.08
        + consolid * 0.1
        + trust * 0.08
        + recency * 0.06
        + project_score * 0.07
    ) * layer_w
    return score, {
        'semantic': similarity,
        'decay': decay,
        'access': access,
        'consolidation': consolid,
        'trust': trust,
        'recency': recency,
        'project_match': project_score,
        'layer_weight': layer_w,
    }


def _layer_sort_key(item: dict[str, Any]) -> tuple[int, float]:
    layer = item.get('layer', 'L5_COLD')
    priority = LAYER_ORDER.index(layer) if layer in LAYER_ORDER else len(LAYER_ORDER)
    return priority, -item.get('score', 0.0)


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
    stmt = select(Capsule, CapsuleEmbedding).join(CapsuleEmbedding, Capsule.id == CapsuleEmbedding.capsule_id)
    if run_id is not None:
        stmt = stmt.where(Capsule.run_id == run_id)
    rows = list(session.exec(stmt))

    candidates: list[dict[str, Any]] = []
    seen_text: set[str] = set()
    for cap, emb in rows:
        if cap.text in seen_text:
            continue
        seen_text.add(cap.text)
        if cap.memory_layer == 'L5_COLD' and cap.archive_status == 'cold':
            continue
        try:
            vec = json.loads(emb.vector_json)
        except Exception:
            vec = []
        sim = _cosine_similarity(query_vector, vec)
        score, factors = score_capsule(cap, sim, project_key=project_key, session_key=session_key)
        if score < settings.agentora_context_min_score:
            continue
        candidates.append(
            {
                'capsule_id': cap.id,
                'score': score,
                'text': cap.text,
                'source': cap.source,
                'run_id': cap.run_id,
                'is_summary': cap.is_summary,
                'created_at': cap.created_at.isoformat(),
                'layer': cap.memory_layer,
                'factors': factors,
            }
        )

    candidates.sort(key=_layer_sort_key)
    base = candidates[: max(top_k * 3, 1)]
    base_scores = {int(x['capsule_id']): float(x['score']) for x in base}
    if settings.agentora_enable_graph_rerank:
        reranked = graph_rerank(session, list(base_scores.keys()), base_scores)
        for item in base:
            cid = int(item['capsule_id'])
            item['graph_score'] = reranked.get(cid, item['score'])
            item['score'] = item['graph_score']
    base.sort(key=lambda x: x['score'], reverse=True)

    admitted: list[dict[str, Any]] = []
    layer_budgets = settings.context_layer_budgets
    for item in base:
        if len(admitted) >= settings.agentora_max_active_contexts:
            break
        layer = item['layer']
        layer_count = sum(1 for x in admitted if x['layer'] == layer)
        layer_budget = layer_budgets.get(layer, settings.agentora_max_active_contexts)
        if layer_count >= layer_budget:
            continue
        reason = {
            'admission': 'score_above_threshold',
            'layer_budget': layer_budget,
            'rank_score': round(item['score'], 4),
            'factors': item['factors'],
        }
        session.add(
            ContextActivation(
                run_id=run_id,
                capsule_id=item['capsule_id'],
                layer=layer,
                query=query,
                score=item['score'],
                reason_json=json.dumps(reason),
                admitted=True,
            )
        )
        admitted.append({**item, 'admission_reason': reason})

    for item in admitted:
        cap = session.get(Capsule, item['capsule_id'])
        if not cap:
            continue
        cap.retrieval_count += 1
        cap.last_accessed_at = datetime.utcnow()
        cap.last_used_at = datetime.utcnow()
        cap.recency_score = min(1.0, cap.recency_score + 0.03)
        session.add(cap)
        state = session.exec(select(MemoryCapsuleState).where(MemoryCapsuleState.capsule_id == cap.id)).first()
        if not state:
            state = MemoryCapsuleState(capsule_id=cap.id, layer=cap.memory_layer)
        state.retrieval_count += 1
        state.usage_count += 1
        state.last_accessed_at = datetime.utcnow()
        state.updated_at = datetime.utcnow()
        session.add(state)

    top_ids = [a['capsule_id'] for a in admitted[:4]]
    for i, source in enumerate(top_ids):
        for target in top_ids[i + 1 :]:
            reinforce_edge(session, source, target, edge_type='co_retrieval', weight=0.65, confidence=0.65)

    session.commit()
    return {'items': admitted[:top_k], 'layers_used': sorted({x['layer'] for x in admitted}, key=lambda x: LAYER_ORDER.index(x) if x in LAYER_ORDER else 99)}
