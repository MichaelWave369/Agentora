import asyncio

from sqlmodel import Session, select

from app.db import engine
from app.models import Agent, Team, TeamAgent, Run, RunMetric
from app.services.runtime.capsules import ingest_text_as_capsules, search_capsules
from app.services.runtime.loop import runtime_loop
from app.services.runtime.schemas import RuntimeAction
from app.services.runtime.worker_queue import WorkerQueue
from app.services.tools.registry import registry
from app.services.orchestration.engine import OrchestrationEngine


def test_capsule_ingest_and_search():
    with Session(engine) as session:
        count = asyncio.run(ingest_text_as_capsules(session, run_id=777, text='alpha beta gamma\n' * 120, source='unit-test'))
        assert count > 0
        items = asyncio.run(search_capsules(session, query='beta gamma', run_id=777, top_k=3))
        assert items
        assert items[0]['run_id'] == 777


def test_structured_action_parsing():
    payload = {
        'thought': 'need context and tool',
        'need_memory': True,
        'memory_queries': ['project notes'],
        'tool_calls': [{'name': 'notes_append', 'args': {'text': 'x'}}],
        'final': 'done',
        'handoff': '',
        'done': True,
    }
    action = RuntimeAction.model_validate(payload)
    assert action.need_memory is True
    assert action.tool_calls[0].name == 'notes_append'


def test_tool_loop_execution_and_persisted_toolcall(monkeypatch):
    with Session(engine) as session:
        agent = Agent(name='Tooler', model='mock-mini', role='ops', system_prompt='be useful', tools_json='["notes_append"]')
        session.add(agent)
        run_id = 880
        session.commit()
        session.refresh(agent)

        async def fake_chat_structured(*args, **kwargs):
            return {
                'thought': 'call a tool',
                'need_memory': False,
                'memory_queries': [],
                'tool_calls': [{'name': 'notes_append', 'args': {'text': 'hello'}}],
                'final': 'tool done',
                'handoff': '',
                'done': True,
            }

        monkeypatch.setattr(runtime_loop.client, 'chat_structured', fake_chat_structured)
        result = asyncio.run(runtime_loop.run_agent(session, run_id=run_id, agent=agent, prompt='append note'))
        assert 'tool done' in result.final_text
        assert result.tool_calls_count == 1


def test_worker_fallback_local():
    with Session(engine) as session:
        q = WorkerQueue()
        q._urls = []
        q._rr = None
        job = q.dispatch(session, 'embedding_batch', {'items': ['a', 'b']})
        assert job.status == 'fallback_local'


def test_engine_metrics_increment_tool_calls(monkeypatch):
    with Session(engine) as session:
        agent = Agent(name='Planner', model='mock-mini', role='planner', system_prompt='plan', tools_json='["notes_append"]')
        team = Team(name='CortexTeam', description='t', mode='sequential', yaml_text='')
        session.add(agent)
        session.add(team)
        session.commit()
        session.refresh(agent)
        session.refresh(team)
        session.add(TeamAgent(team_id=team.id, agent_id=agent.id, position=0))
        run = Run(team_id=team.id, status='running', mode='sequential', max_turns=2, max_seconds=30, token_budget=1000, consensus_threshold=1)
        session.add(run)
        session.commit()
        session.refresh(run)

        async def fake_chat_structured(*args, **kwargs):
            return {
                'thought': 'use tool then finish',
                'need_memory': False,
                'memory_queries': [],
                'tool_calls': [{'name': 'notes_append', 'args': {'text': 'metric'}}],
                'final': 'done',
                'handoff': '',
                'done': True,
            }

        monkeypatch.setattr(runtime_loop.client, 'chat_structured', fake_chat_structured)
        asyncio.run(OrchestrationEngine().execute(session, run, 'hello world', False))
        metric = session.exec(select(RunMetric).where(RunMetric.run_id == run.id)).first()
        assert metric is not None
        assert metric.tool_calls >= 1
