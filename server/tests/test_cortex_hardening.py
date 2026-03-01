import asyncio

import requests
from sqlmodel import Session, select

from app.db import engine
from app.models import Agent, Team, TeamAgent, Run, RunMetric, RunTrace, ModelCapability
from app.services.runtime.loop import runtime_loop
from app.services.runtime.router import choose_model_for_role
from app.services.runtime.worker_queue import WorkerQueue
from app.services.runtime.capsules import ingest_text_as_capsules, search_capsules
from app.services.tools.registry import registry
from app.core.config import settings
from .conftest import make_client


def _mk_agent(session: Session, tools='["notes_append"]'):
    a = Agent(name='A', model='mock-mini', role='planner', system_prompt='plan carefully', tools_json=tools)
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


def test_invalid_action_payload_fallback(monkeypatch):
    with Session(engine) as session:
        agent = _mk_agent(session)

        async def bad_payload(*args, **kwargs):
            return 'invalid-json'

        monkeypatch.setattr(runtime_loop.client, 'chat_structured', bad_payload)
        res = asyncio.run(runtime_loop.run_agent(session, run_id=501, agent=agent, prompt='hello'))
        assert res.stop_reason == 'invalid_action_payload'
        assert res.warnings


def test_tool_exception_handled(monkeypatch):
    with Session(engine) as session:
        agent = _mk_agent(session, tools='["notes_append"]')

        async def action(*args, **kwargs):
            return {'thought': 't', 'need_memory': False, 'memory_queries': [], 'tool_calls': [{'name': 'notes_append', 'args': {'text': 'x'}}], 'final': '', 'handoff': '', 'done': False}

        def boom(*args, **kwargs):
            raise RuntimeError('boom')

        monkeypatch.setattr(runtime_loop.client, 'chat_structured', action)
        monkeypatch.setitem(registry._tools, 'notes_append', registry._tools['notes_append'].__class__(
            'notes_append', {'run_id': 'int', 'text': 'string'}, 'artifact:write', boom
        ))
        res = asyncio.run(runtime_loop.run_agent(session, run_id=502, agent=agent, prompt='hello'))
        assert res.stop_reason in {'tool_error', 'max_steps'}


def test_model_role_routing_tool_vs_chat():
    with Session(engine) as session:
        m1, _ = choose_model_for_role(session, role='chat', has_images=False)
        m2, _ = choose_model_for_role(session, role='tool_planning', has_images=False)
        assert m1 == settings.agentora_chat_model
        assert m2 == settings.agentora_tool_model


def test_image_input_triggers_vision_fallback():
    with Session(engine) as session:
        cap = session.get(ModelCapability, settings.agentora_tool_model) or ModelCapability(model_name=settings.agentora_tool_model)
        cap.can_vision = False
        cap.can_tools = True
        session.add(cap)
        session.commit()
        m, warnings = choose_model_for_role(session, role='tool_planning', has_images=True)
        assert m in {settings.agentora_vision_model or settings.agentora_vision_model_fallback, settings.agentora_tool_model}
        assert warnings


def test_worker_timeout_fallback(monkeypatch):
    q = WorkerQueue()
    with Session(engine) as session:
        node = q.register(session, 'w1', 'http://worker.local', ['embed_batch'])

        def timeout(*args, **kwargs):
            raise requests.Timeout('timeout')

        monkeypatch.setattr(requests, 'post', timeout)
        job = q.dispatch(session, 'embed_batch', {'items': ['x']}, priority=3)
        assert job.used_fallback_local is True


def test_worker_retries_cap(monkeypatch):
    q = WorkerQueue()
    with Session(engine) as session:
        q.register(session, 'w2', 'http://worker2.local', ['python_exec'])

        class Resp:
            ok = False
            status_code = 500
            text = ''

        monkeypatch.setattr(requests, 'post', lambda *a, **k: Resp())
        job = q.dispatch(session, 'python_exec', {'code': 'print(1)'}, priority=1)
        assert job.retries <= settings.agentora_max_worker_retries


def test_capsule_retrieval_dedupe_and_metadata():
    with Session(engine) as session:
        text = ('same block ' * 80) + ('unique tail ' * 90)
        asyncio.run(ingest_text_as_capsules(session, run_id=701, text=text, source='docA'))
        items = asyncio.run(search_capsules(session, 'same block', run_id=701, top_k=6))
        assert items
        assert all('source' in i and 'created_at' in i for i in items)
        texts = [i['text'] for i in items]
        assert len(texts) == len(set(texts))


def test_trace_contains_tool_and_stop_reason(monkeypatch):
    c = make_client()
    a = c.post('/api/agents', json={'name': 'Planner', 'model': 'mock-mini', 'role': 'p', 'system_prompt': 's', 'tools': ['notes_append']}).json()
    t = c.post('/api/teams', json={'name': 'TT', 'mode': 'sequential', 'description': '', 'yaml_text': '', 'agent_ids': [a['id']]}).json()

    async def action(*args, **kwargs):
        return {'thought': 'use tool', 'need_memory': False, 'memory_queries': [], 'tool_calls': [{'name': 'notes_append', 'args': {'text': 'trace'}}], 'final': 'done', 'handoff': '', 'done': True}

    monkeypatch.setattr(runtime_loop.client, 'chat_structured', action)
    rr = c.post('/api/runs', json={'team_id': t['id'], 'prompt': 'hi', 'max_turns': 2, 'max_seconds': 20, 'token_budget': 800, 'consensus_threshold': 1}).json()
    tr = c.get(f"/api/runs/{rr['run_id']}/trace").json()
    event_types = [x['event_type'] for x in tr['trace']]
    assert 'tool_call' in event_types
    assert 'final_answer' in event_types


def test_blocked_tool_denied_and_logged(monkeypatch):
    c = make_client()
    a = c.post('/api/agents', json={'name': 'Planner2', 'model': 'mock-mini', 'role': 'p', 'system_prompt': 's', 'tools': ['python_exec']}).json()
    t = c.post('/api/teams', json={'name': 'TB', 'mode': 'sequential', 'description': '', 'yaml_text': '', 'agent_ids': [a['id']]}).json()

    original = settings.agentora_blocked_tool_names
    settings.agentora_blocked_tool_names = 'python_exec'

    async def action(*args, **kwargs):
        return {'thought': 'blocked', 'need_memory': False, 'memory_queries': [], 'tool_calls': [{'name': 'python_exec', 'args': {'python_code': 'print(1)'}}], 'final': 'ok', 'handoff': '', 'done': True}

    monkeypatch.setattr(runtime_loop.client, 'chat_structured', action)
    rr = c.post('/api/runs', json={'team_id': t['id'], 'prompt': 'hi', 'max_turns': 2, 'max_seconds': 20, 'token_budget': 800, 'consensus_threshold': 1}).json()
    with Session(engine) as session:
        traces = list(session.exec(select(RunTrace).where(RunTrace.run_id == rr['run_id'])))
        assert any('blocked' in x.payload_json for x in traces)
    settings.agentora_blocked_tool_names = original


def test_runmetric_reflects_tool_usage(monkeypatch):
    c = make_client()
    a = c.post('/api/agents', json={'name': 'Planner3', 'model': 'mock-mini', 'role': 'p', 'system_prompt': 's', 'tools': ['notes_append']}).json()
    t = c.post('/api/teams', json={'name': 'TM', 'mode': 'sequential', 'description': '', 'yaml_text': '', 'agent_ids': [a['id']]}).json()

    async def action(*args, **kwargs):
        return {'thought': 'tool', 'need_memory': False, 'memory_queries': [], 'tool_calls': [{'name': 'notes_append', 'args': {'text': 'metric'}}], 'final': 'done', 'handoff': '', 'done': True}

    monkeypatch.setattr(runtime_loop.client, 'chat_structured', action)
    rr = c.post('/api/runs', json={'team_id': t['id'], 'prompt': 'hi', 'max_turns': 2, 'max_seconds': 20, 'token_budget': 800, 'consensus_threshold': 1}).json()
    with Session(engine) as session:
        metric = session.exec(select(RunMetric).where(RunMetric.run_id == rr['run_id'])).first()
        assert metric and metric.tool_calls >= 1
