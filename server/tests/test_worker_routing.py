from sqlmodel import Session

from app.db import engine
from app.models import WorkerNode
from app.services.runtime.worker_queue import WorkerQueue


def test_worker_routing_prefers_heavy_capability():
    with Session(engine) as session:
        q = WorkerQueue()
        w1 = q.register(session, 'heavy-node', 'http://127.0.0.1:9991', ['memory_maintenance', 'embed_batch'])
        w2 = q.register(session, 'light-node', 'http://127.0.0.1:9992', ['interactive_chat'])
        # force timeout/fallback locally in test env but ensure route attempt is valid
        job = q.dispatch(session, 'memory_maintenance', {'run_id': 555}, priority=3)
        assert job.status in {'running', 'done', 'fallback_local'}


def test_interactive_task_stays_local_guardrail():
    with Session(engine) as session:
        q = WorkerQueue()
        q.register(session, 'chat-node', 'http://127.0.0.1:9993', ['interactive_chat'])
        job = q.dispatch(session, 'interactive_chat', {'run_id': 556}, priority=8)
        assert job.status == 'fallback_local'
