import asyncio

from sqlmodel import Session, select

from app.db import engine
from app.models import Agent, AgentCapabilityProfile, AgentHandoff, CollaborationMetric, Run, Team, TeamAgent, TeamPlan, TeamSubgoal
from app.services.orchestration.engine import OrchestrationEngine
from app.services.runtime.loop import runtime_loop
from app.services.runtime.team import collaboration_trace


def _seed_team(session: Session):
    planner = Agent(name='Planner', model='mock-mini', role='planner', system_prompt='plan', tools_json='[]')
    executor = Agent(name='Builder', model='mock-mini', role='executor', system_prompt='build', tools_json='["notes_append"]')
    critic = Agent(name='Critic', model='mock-mini', role='critic', system_prompt='critique', tools_json='[]')
    team = Team(name='OrchTeam', description='team', mode='careful', yaml_text='')
    session.add(planner)
    session.add(executor)
    session.add(critic)
    session.add(team)
    session.commit()
    session.refresh(planner)
    session.refresh(executor)
    session.refresh(critic)
    session.refresh(team)
    session.add(TeamAgent(team_id=team.id, agent_id=planner.id, position=0))
    session.add(TeamAgent(team_id=team.id, agent_id=executor.id, position=1))
    session.add(TeamAgent(team_id=team.id, agent_id=critic.id, position=2))
    session.commit()
    run = Run(team_id=team.id, status='running', mode='careful', max_turns=6, max_seconds=60, token_budget=3000, consensus_threshold=1)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run, planner, executor, critic


def test_team_plan_and_handoffs(monkeypatch):
    with Session(engine) as session:
        run, planner, executor, critic = _seed_team(session)

        async def fake_run_agent(session, run_id, agent, prompt, image_paths=None, max_steps=None):
            class R:
                final_text = f"{agent.role} output for {prompt[:40]}"
                tool_calls_count = 0
                stop_reason = 'completed'
                warnings = []
                worker_used = False
                model_used = ['mock-mini']
            return R()

        monkeypatch.setattr(runtime_loop, 'run_agent', fake_run_agent)
        state = asyncio.run(OrchestrationEngine().execute(session, run, 'Plan and build then verify this feature', False))
        assert state.messages

        plan = session.exec(select(TeamPlan).where(TeamPlan.run_id == run.id).order_by(TeamPlan.id.desc())).first()
        assert plan is not None
        subgoals = list(session.exec(select(TeamSubgoal).where(TeamSubgoal.plan_id == plan.id)))
        assert len(subgoals) >= 2
        handoffs = list(session.exec(select(AgentHandoff).where(AgentHandoff.run_id == run.id)))
        assert handoffs
        metric = session.exec(select(CollaborationMetric).where(CollaborationMetric.run_id == run.id)).first()
        assert metric is not None
        trace = collaboration_trace(session, run.id)
        events = {t['event_type'] for t in trace}
        assert 'team_plan_created' in events
        assert 'subgoal_assigned' in events
        assert 'subgoal_completed' in events


def test_single_agent_fallback_plan(monkeypatch):
    with Session(engine) as session:
        agent = Agent(name='Solo', model='mock-mini', role='assistant', system_prompt='do', tools_json='[]')
        team = Team(name='SoloTeam', description='s', mode='fast', yaml_text='')
        session.add(agent)
        session.add(team)
        session.commit()
        session.refresh(agent)
        session.refresh(team)
        session.add(TeamAgent(team_id=team.id, agent_id=agent.id, position=0))
        run = Run(team_id=team.id, status='running', mode='fast', max_turns=3, max_seconds=30, token_budget=1000, consensus_threshold=1)
        session.add(run)
        session.commit()
        session.refresh(run)

        async def fake_run_agent(session, run_id, agent, prompt, image_paths=None, max_steps=None):
            class R:
                final_text = 'quick answer'
                tool_calls_count = 0
                stop_reason = 'completed'
                warnings = []
                worker_used = False
                model_used = ['mock-mini']
            return R()

        monkeypatch.setattr(runtime_loop, 'run_agent', fake_run_agent)
        asyncio.run(OrchestrationEngine().execute(session, run, 'Quick summary please', False))
        plan = session.exec(select(TeamPlan).where(TeamPlan.run_id == run.id).order_by(TeamPlan.id.desc())).first()
        assert plan is not None
        assert plan.mode == 'single_agent'
        assert session.exec(select(AgentCapabilityProfile).where(AgentCapabilityProfile.agent_id == agent.id)).first() is not None
