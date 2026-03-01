from __future__ import annotations

import json
import math
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Capsule, CapsuleEmbedding
from app.services.ollama_client import OllamaClient


def chunk_text(text: str, chunk_size: int = 700, overlap: int = 120) -> list[str]:
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


async def ingest_text_as_capsules(
    session: Session,
    run_id: int,
    text: str,
    source: str,
    attachment_id: int | None = None,
) -> int:
    chunks = chunk_text(text)
    if not chunks:
        return 0
    client = OllamaClient()
    vectors = await client.embed_texts(chunks)
    inserted = 0
    for idx, chunk in enumerate(chunks):
        capsule = Capsule(
            run_id=run_id,
            attachment_id=attachment_id,
            source=source,
            chunk_index=idx,
            text=chunk,
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


def search_capsules_sync(session: Session, query_vector: list[float], run_id: int | None = None, top_k: int | None = None) -> list[dict]:
    top_k = top_k or settings.agentora_capsule_top_k
    stmt = select(Capsule, CapsuleEmbedding).join(CapsuleEmbedding, Capsule.id == CapsuleEmbedding.capsule_id)
    if run_id is not None:
        stmt = stmt.where(Capsule.run_id == run_id)
    rows = list(session.exec(stmt))
    scored: list[dict] = []
    for cap, emb in rows:
        try:
            vec = json.loads(emb.vector_json)
        except Exception:
            vec = []
        score = _cosine_similarity(query_vector, vec)
        scored.append({'capsule_id': cap.id, 'score': score, 'text': cap.text, 'source': cap.source, 'run_id': cap.run_id})
    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:max(1, top_k)]


async def search_capsules(session: Session, query: str, run_id: int | None = None, top_k: int | None = None) -> list[dict]:
    client = OllamaClient()
    qv = (await client.embed_texts([query]))[0]
    return search_capsules_sync(session=session, query_vector=qv, run_id=run_id, top_k=top_k)
