from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.db import engine
from app.models import Capsule, CapsuleEmbedding, ContextActivation
from app.services.runtime.capsules import search_capsules_sync
from app.services.runtime.maintenance import demote_capsule, promote_capsule, refine_capsule, run_maintenance
from app.services.runtime.worker_queue import WorkerQueue


def _mk_capsule(session: Session, **kwargs) -> Capsule:
    cap = Capsule(
        run_id=kwargs.get('run_id', 401),
        source=kwargs.get('source', 'unit'),
        text=kwargs.get('text', 'alpha memory capsule'),
        memory_layer=kwargs.get('memory_layer', 'L1_SHORT'),
        decay_class=kwargs.get('decay_class', 'short'),
        trust_score=kwargs.get('trust_score', 0.7),
        consolidation_score=kwargs.get('consolidation_score', 0.7),
        recency_score=kwargs.get('recency_score', 1.0),
        created_at=kwargs.get('created_at', datetime.utcnow()),
        archive_status=kwargs.get('archive_status', 'active'),
    )
    session.add(cap)
    session.commit()
    session.refresh(cap)
    session.add(CapsuleEmbedding(capsule_id=cap.id, vector_json='[1.0,0.0,0.0]'))
    session.commit()
    return cap


def test_layer_priority_and_sparse_admission():
    with Session(engine) as session:
        hot = _mk_capsule(session, run_id=9401, memory_layer='L0_HOT', text='hot context')
        _mk_capsule(session, run_id=9401, memory_layer='L3_DURABLE', text='durable context')
        _mk_capsule(session, run_id=9401, memory_layer='L5_COLD', archive_status='cold', text='cold context')

        before = len(list(session.exec(select(ContextActivation).where(ContextActivation.run_id == 9401))))
        items = search_capsules_sync(session, query_vector=[1.0, 0.0, 0.0], run_id=9401, top_k=4, query='hot context')
        assert items
        assert items[0]['layer'] == 'L0_HOT'
        assert all(i['layer'] != 'L5_COLD' for i in items)

        activations = list(session.exec(select(ContextActivation).where(ContextActivation.run_id == 9401)))
        assert activations
        assert (len(activations) - before) <= 6
        assert any(a.layer == 'L0_HOT' for a in activations[-6:])


def test_decay_and_scoring_prefer_recent_short_memory():
    with Session(engine) as session:
        _mk_capsule(session, run_id=9402, memory_layer='L1_SHORT', decay_class='short', created_at=datetime.utcnow())
        _mk_capsule(session, run_id=9402, memory_layer='L3_DURABLE', decay_class='long', created_at=datetime.utcnow() - timedelta(days=45))
        items = search_capsules_sync(session, query_vector=[1.0, 0.0, 0.0], run_id=9402, top_k=2, query='alpha')
        assert items[0]['score'] >= items[-1]['score']


def test_refinement_and_promotion_demotion_lifecycle():
    with Session(engine) as session:
        dense = _mk_capsule(session, run_id=9403, text='.'.join(['topic a'] * 800), memory_layer='L2_SESSION')
        result = refine_capsule(session, dense.id)
        assert result['ok'] is True
        assert result['created'] >= 1

        cap = promote_capsule(session, dense.id)
        assert cap.memory_layer in {'L1_SHORT', 'L0_HOT'}
        cap = demote_capsule(session, dense.id)
        assert cap.memory_layer in {'L2_SESSION', 'L3_DURABLE'}


def test_maintenance_and_worker_fallback():
    with Session(engine) as session:
        cap = _mk_capsule(session, run_id=9404, memory_layer='L2_SESSION')
        cap.retrieval_count = 10
        cap.success_count = 8
        cap.failure_count = 0
        session.add(cap)
        session.commit()

        job = run_maintenance(session, run_id=9404, try_worker=True)
        assert job.status == 'done'
        assert job.id is not None

        wq = WorkerQueue()
        fallback = wq.dispatch(session, 'memory_maintenance', {'run_id': 404})
        assert fallback.status in {'fallback_local', 'done', 'running'}
