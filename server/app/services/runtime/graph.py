from __future__ import annotations

from datetime import datetime
from sqlmodel import Session, select

from app.models import Capsule, MemoryEdge


def reinforce_edge(
    session: Session,
    from_capsule_id: int,
    to_capsule_id: int,
    edge_type: str = 'co_retrieval',
    weight: float = 0.6,
    confidence: float = 0.6,
    trust_score: float = 0.6,
) -> MemoryEdge:
    if from_capsule_id == to_capsule_id:
        raise ValueError('self_edge_not_allowed')
    edge = session.exec(
        select(MemoryEdge).where(
            MemoryEdge.from_capsule_id == from_capsule_id,
            MemoryEdge.to_capsule_id == to_capsule_id,
            MemoryEdge.edge_type == edge_type,
        )
    ).first()
    now = datetime.utcnow()
    if edge:
        edge.weight = max(edge.weight, weight)
        edge.confidence = max(edge.confidence, confidence)
        edge.trust_score = max(edge.trust_score, trust_score)
        edge.usage_count += 1
        edge.last_reinforced_at = now
    else:
        edge = MemoryEdge(
            from_capsule_id=from_capsule_id,
            to_capsule_id=to_capsule_id,
            edge_type=edge_type,
            weight=weight,
            confidence=confidence,
            trust_score=trust_score,
            usage_count=1,
            last_reinforced_at=now,
        )
    session.add(edge)
    session.commit()
    session.refresh(edge)
    return edge


def graph_rerank(session: Session, candidate_ids: list[int], base_scores: dict[int, float]) -> dict[int, float]:
    if not candidate_ids:
        return {}
    neighbor_edges = list(
        session.exec(
            select(MemoryEdge).where(
                MemoryEdge.from_capsule_id.in_(candidate_ids) | MemoryEdge.to_capsule_id.in_(candidate_ids)
            )
        )
    )
    boosted = dict(base_scores)
    for edge in neighbor_edges:
        source = edge.from_capsule_id
        target = edge.to_capsule_id
        source_score = boosted.get(source, 0.0)
        neighbor_boost = source_score * 0.12 * edge.weight * edge.confidence * max(0.25, edge.trust_score)
        if target in boosted:
            boosted[target] += neighbor_boost
        elif source in boosted:
            cap = session.get(Capsule, target)
            if cap and cap.archive_status != 'cold':
                boosted[target] = neighbor_boost * 0.85
    return boosted
