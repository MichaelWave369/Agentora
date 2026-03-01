from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Capsule, CapsuleEmbedding
from app.services.ollama_client import OllamaClient
from app.services.runtime.layers import layered_retrieval


def chunk_text(text: str, chunk_size: int = 850, overlap: int = 150) -> list[str]:
    clean = ' '.join(text.split())
    if not clean:
        return []
    out: list[str] = []
    i = 0
    step = max(1, chunk_size - overlap)
    while i < len(clean):
        out.append(clean[i : i + chunk_size])
        i += step
    return out


def _summary_chunk(text: str) -> str:
    clean = ' '.join(text.split())
    return clean[:1000]


def _derive_layer(source: str, is_summary: bool, text_len: int) -> tuple[str, str]:
    source_l = (source or '').lower()
    if source_l in {'runtime', 'tool', 'scratchpad'}:
        return 'L0_HOT', 'short'
    if source_l in {'attachment', 'extract'} and text_len > 1600:
        return 'L5_COLD', 'long'
    if is_summary:
        return 'L1_SHORT', 'medium'
    if source_l in {'profile', 'preference', 'identity'}:
        return 'L3_DURABLE', 'long'
    return 'L2_SESSION', 'medium'


async def ingest_text_as_capsules(
    session: Session,
    run_id: int,
    text: str,
    source: str,
    attachment_id: int | None = None,
    tags: list[str] | None = None,
) -> int:
    chunks = chunk_text(text)
    if not chunks:
        return 0
    created_chunks = chunks[:]
    summary_added = False
    if len(text) > 4000 and settings.agentora_enable_memory_summaries:
        created_chunks = [_summary_chunk(text)] + created_chunks
        summary_added = True

    vectors = await OllamaClient().embed_texts(created_chunks, model=settings.agentora_embed_model)
    inserted = 0
    tags_json = json.dumps(tags or [])
    for idx, chunk in enumerate(created_chunks):
        is_summary = summary_added and idx == 0
        layer, decay = _derive_layer(source=source, is_summary=is_summary, text_len=len(chunk))
        capsule = Capsule(
            run_id=run_id,
            attachment_id=attachment_id,
            source=source,
            chunk_index=idx,
            text=chunk,
            tags_json=tags_json,
            is_summary=is_summary,
            memory_layer=layer,
            source_type='attachment' if attachment_id else 'run',
            project_key=f'run:{run_id}',
            session_key=f'run:{run_id}',
            archive_status='cold' if layer == 'L5_COLD' else 'active',
            decay_class=decay,
            confidence=0.55,
            consolidation_score=0.5,
            trust_score=0.55,
            recency_score=1.0,
            created_from_run_id=run_id,
            created_at=datetime.utcnow(),
        )
        session.add(capsule)
        session.commit()
        session.refresh(capsule)
        vec = vectors[idx] if idx < len(vectors) else []
        session.add(CapsuleEmbedding(capsule_id=capsule.id, vector_json=json.dumps(vec)))
        inserted += 1
    session.commit()
    return inserted


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


def _recency_boost(created_at: datetime) -> float:
    now = datetime.now(timezone.utc)
    dt = created_at.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    return 1.0 / (1.0 + (hours / 24.0))


def search_capsules_sync(
    session: Session,
    query_vector: list[float],
    run_id: int | None = None,
    top_k: int | None = None,
    source_weight: dict[str, float] | None = None,
    query: str = '',
) -> list[dict]:
    if settings.agentora_enable_layered_memory and run_id is not None:
        layered = layered_retrieval(session, query_vector=query_vector, query=query or 'query', run_id=run_id, top_k=top_k)
        return layered['items']

    top_k = top_k or settings.agentora_capsule_top_k
    source_weight = source_weight or {}

    stmt = select(Capsule, CapsuleEmbedding).join(CapsuleEmbedding, Capsule.id == CapsuleEmbedding.capsule_id)
    if run_id is not None:
        stmt = stmt.where(Capsule.run_id == run_id)
    rows = list(session.exec(stmt))

    seen_text: set[str] = set()
    scored: list[dict] = []
    for cap, emb in rows:
        if cap.text in seen_text:
            continue
        seen_text.add(cap.text)
        try:
            vec = json.loads(emb.vector_json)
        except Exception:
            vec = []
        sim = _cosine_similarity(query_vector, vec)
        recency = _recency_boost(cap.created_at)
        src_w = float(source_weight.get(cap.source, 1.0))
        summary_boost = 1.08 if cap.is_summary else 1.0
        final = sim * 0.75 + recency * 0.25
        final *= src_w * summary_boost
        scored.append(
            {
                'capsule_id': cap.id,
                'score': final,
                'text': cap.text,
                'source': cap.source,
                'run_id': cap.run_id,
                'is_summary': cap.is_summary,
                'created_at': cap.created_at.isoformat(),
                'layer': cap.memory_layer,
                'score_breakdown': {
                    'semantic': sim,
                    'decay': recency,
                    'access_frequency': min(1.0, cap.retrieval_count / 16.0),
                    'trust': cap.trust_score,
                    'consolidation': cap.consolidation_score,
                    'project_match': 0.0,
                    'layer_weight': 1.0,
                    'graph_rerank': 0.0,
                    'final_score': final,
                },
                'admission_reason': {'admission': 'flat_retrieval_fallback'},
                'conflict_flag': cap.contradiction_flag,
                'duplicate_cluster_id': cap.duplicate_cluster_id,
                'duplicate_score': cap.duplicate_score,
            }
        )
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:max(1, top_k)]


async def search_capsules(
    session: Session,
    query: str,
    run_id: int | None = None,
    top_k: int | None = None,
    source_weight: dict[str, float] | None = None,
) -> list[dict]:
    qv = (await OllamaClient().embed_texts([query], model=settings.agentora_embed_model))[0]
    return search_capsules_sync(session=session, query_vector=qv, run_id=run_id, top_k=top_k, source_weight=source_weight, query=query)
