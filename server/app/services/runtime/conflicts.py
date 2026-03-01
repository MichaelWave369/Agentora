from __future__ import annotations

import hashlib
import json
from datetime import datetime

from sqlmodel import Session, select

from app.models import Capsule, DuplicateCluster, MemoryConflict


NEGATION_TERMS = {' not ', "n't ", ' never ', ' no ', ' cannot ', ' fail ', ' false '}


def _normalize(text: str) -> str:
    return ' '.join((text or '').lower().split())


def _text_hash(text: str) -> str:
    return hashlib.sha1(_normalize(text).encode('utf-8')).hexdigest()[:16]


def _token_jaccard(a: str, b: str) -> float:
    sa = set(_normalize(a).split())
    sb = set(_normalize(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / max(1, len(sa | sb))


def _negation_polarity(text: str) -> int:
    norm = f' {_normalize(text)} '
    return 1 if any(x in norm for x in NEGATION_TERMS) else 0


def contradiction_score(a: Capsule, b: Capsule) -> float:
    overlap = _token_jaccard(a.text, b.text)
    polarity_gap = 1.0 if _negation_polarity(a.text) != _negation_polarity(b.text) else 0.0
    layer_penalty = 0.15 if a.memory_layer != b.memory_layer else 0.0
    return max(0.0, min(1.0, overlap * 0.6 + polarity_gap * 0.35 + layer_penalty))


def upsert_duplicate_cluster(session: Session, capsule: Capsule) -> DuplicateCluster:
    h = _text_hash(capsule.text)
    cluster = session.exec(select(DuplicateCluster).where(DuplicateCluster.hash_key == h)).first()
    now = datetime.utcnow()
    if not cluster:
        cluster = DuplicateCluster(hash_key=h, canonical_capsule_id=capsule.id, member_capsule_ids_json=json.dumps([capsule.id]), cluster_size=1, updated_at=now)
    else:
        members = set(json.loads(cluster.member_capsule_ids_json or '[]'))
        members.add(capsule.id)
        cluster.member_capsule_ids_json = json.dumps(sorted(members))
        cluster.cluster_size = len(members)
        cluster.updated_at = now
    session.add(cluster)
    session.commit()
    session.refresh(cluster)
    capsule.duplicate_cluster_id = cluster.id
    capsule.duplicate_score = min(1.0, max(capsule.duplicate_score, 0.35 if cluster.cluster_size > 1 else 0.0))
    session.add(capsule)
    session.commit()
    return cluster


def detect_conflicts_for_run(session: Session, run_id: int) -> list[MemoryConflict]:
    rows = list(session.exec(select(Capsule).where(Capsule.run_id == run_id).order_by(Capsule.id.desc()).limit(30)))
    created: list[MemoryConflict] = []
    for i, left in enumerate(rows):
        for right in rows[i + 1 : i + 8]:
            score = contradiction_score(left, right)
            if score < 0.55:
                continue
            conflict = session.exec(
                select(MemoryConflict).where(
                    MemoryConflict.left_capsule_id == left.id,
                    MemoryConflict.right_capsule_id == right.id,
                )
            ).first()
            if conflict:
                conflict.conflict_score = max(conflict.conflict_score, score)
                conflict.updated_at = datetime.utcnow()
            else:
                conflict = MemoryConflict(
                    left_capsule_id=left.id,
                    right_capsule_id=right.id,
                    conflict_type='contradiction',
                    conflict_score=score,
                    status='open',
                    detail_json=json.dumps({'run_id': run_id, 'overlap': _token_jaccard(left.text, right.text)}),
                    updated_at=datetime.utcnow(),
                )
            left.contradiction_flag = True
            right.contradiction_flag = True
            session.add(left)
            session.add(right)
            session.add(conflict)
            created.append(conflict)
    session.commit()
    return created


def list_duplicates(session: Session) -> list[dict]:
    clusters = list(session.exec(select(DuplicateCluster).where(DuplicateCluster.cluster_size > 1).order_by(DuplicateCluster.cluster_size.desc())))
    return [
        {
            'id': c.id,
            'hash_key': c.hash_key,
            'cluster_size': c.cluster_size,
            'canonical_capsule_id': c.canonical_capsule_id,
            'member_capsule_ids': json.loads(c.member_capsule_ids_json or '[]'),
            'updated_at': c.updated_at.isoformat(),
        }
        for c in clusters
    ]
