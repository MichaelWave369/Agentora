from sqlmodel import Session

from app.db import engine
from app.models import Agent, Run, Team, TeamAgent
from .conftest import make_client


def test_team_and_capabilities_endpoints_smoke():
    client = make_client()
    with Session(engine) as session:
        a = Agent(name='Ops', model='mock-mini', role='planner', system_prompt='plan', tools_json='[]')
        t = Team(name='TeamAPI', description='x', mode='careful', yaml_text='')
        session.add(a)
        session.add(t)
        session.commit()
        session.refresh(a)
        session.refresh(t)
        session.add(TeamAgent(team_id=t.id, agent_id=a.id, position=0))
        r = Run(team_id=t.id, status='running', mode='careful', max_turns=4, max_seconds=60, token_budget=1500, consensus_threshold=1)
        session.add(r)
        session.commit()
        session.refresh(r)
        run_id = r.id
        agent_id = a.id

    capabilities = client.get('/api/agents/capabilities')
    assert capabilities.status_code == 200

    upsert = client.post(f'/api/agents/{agent_id}/capabilities', json={'preferred_model_role': 'tool_planning', 'allowed_tools': [], 'max_tool_steps': 3, 'can_critique': True, 'can_verify': True, 'can_delegate': True, 'can_use_workers': True, 'memory_scope': 'project', 'preferred_team_mode': 'careful', 'confidence_weight': 0.7})
    assert upsert.status_code == 200

    preview = client.post('/api/team/modes/preview', json={'prompt': 'Plan and verify and compare approaches', 'mode': 'careful'})
    assert preview.status_code == 200

    plan = client.post('/api/team/plan', json={'run_id': run_id, 'prompt': 'Plan and build then verify', 'mode': 'careful'})
    assert plan.status_code == 200

    assert client.get(f'/api/runs/{run_id}/plan').status_code == 200
    assert client.get(f'/api/runs/{run_id}/handoffs').status_code == 200
    assert client.get(f'/api/runs/{run_id}/collaboration-trace').status_code == 200
    assert client.get(f'/api/runs/{run_id}/team').status_code == 200
