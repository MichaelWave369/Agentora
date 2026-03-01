from sqlmodel import Session

from app.db import engine
from app.models import Capsule, CapsuleEmbedding
from app.services.runtime.layers import layered_retrieval


def _add_cap(session: Session, run_id: int, text: str, layer: str = 'L2_SESSION', project_key: str | None = None):
    cap = Capsule(run_id=run_id, source='unit', text=text, memory_layer=layer, project_key=project_key or f'run:{run_id}', session_key=f'run:{run_id}')
    session.add(cap)
    session.commit()
    session.refresh(cap)
    session.add(CapsuleEmbedding(capsule_id=cap.id, vector_json='[1.0,0.0,0.0]'))
    session.commit()
    return cap


def test_retrieval_score_breakdown_and_context_reasons():
    with Session(engine) as session:
        _add_cap(session, 9801, 'project alpha memory one', layer='L1_SHORT')
        _add_cap(session, 9801, 'project alpha memory two', layer='L2_SESSION')
        result = layered_retrieval(session, query_vector=[1.0, 0.0, 0.0], query='project alpha', run_id=9801, top_k=2)
        assert result['items']
        first = result['items'][0]
        assert 'score_breakdown' in first
        assert 'semantic' in first['score_breakdown']
        assert 'graph_rerank' in first['score_breakdown']
        assert 'admission_reason' in first


def test_duplicate_suppression_and_conflict_flagging():
    with Session(engine) as session:
        _add_cap(session, 9802, 'policy should not allow external sharing', layer='L2_SESSION')
        _add_cap(session, 9802, 'policy should allow external sharing', layer='L2_SESSION')
        _add_cap(session, 9802, 'policy should allow external sharing', layer='L2_SESSION')
        result = layered_retrieval(session, query_vector=[1.0, 0.0, 0.0], query='sharing policy', run_id=9802, top_k=6)
        texts = [x['text'] for x in result['items']]
        assert len(texts) == len(set(texts))
        assert any(x.get('conflict_flag') for x in result['items'])
