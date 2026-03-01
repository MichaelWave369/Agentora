import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Run, Team, Message, Agent, TeamAgent, AgentHandoff, CollaborationMetric, TeamPlan, TeamSubgoal, ActionRequest, ActionExecution, ActionArtifact
from app.schemas import RunIn
from app.services.orchestration.engine import OrchestrationEngine
from app.services.runtime.trace import get_run_trace
from app.services.runtime.team import collaboration_trace, list_plan

router = APIRouter(prefix='/api/runs', tags=['runs'])
engine = OrchestrationEngine()


@router.get('')
def list_runs(session: Session = Depends(get_session)):
    return list(session.exec(select(Run).order_by(Run.id.desc())))


@router.post('')
async def create_run(payload: RunIn, session: Session = Depends(get_session)):
    team = session.get(Team, payload.team_id)
    if not team:
        raise HTTPException(404, 'team not found')
    run = Run(team_id=payload.team_id, mode=team.mode, status='running', max_turns=payload.max_turns, max_seconds=payload.max_seconds, token_budget=payload.token_budget, consensus_threshold=payload.consensus_threshold)
    session.add(run)
    session.commit()
    session.refresh(run)
    state = await engine.execute(session, run, payload.prompt, payload.reflection)
    return {'run_id': run.id, 'messages': state.messages, 'status': run.status}


@router.post('/{run_id}/pause')
def pause_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    run.status = 'paused'
    run.paused_reason = 'manual'
    session.add(run)
    session.commit()
    return {'ok': True}


@router.post('/{run_id}/resume')
def resume_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    run.status = 'running'
    session.add(run)
    session.commit()
    return {'ok': True}


@router.post('/{run_id}/clone-agent')
def clone_agent(run_id: int, payload: dict, session: Session = Depends(get_session)):
    source = session.get(Agent, payload['agent_id'])
    clone = Agent(name=payload.get('name', f'{source.name}-clone'), model=source.model, role=payload.get('role', source.role), system_prompt=payload.get('system_prompt', source.system_prompt), tools_json=source.tools_json, memory_mode=source.memory_mode)
    session.add(clone)
    session.commit()
    session.refresh(clone)
    run = session.get(Run, run_id)
    links = list(session.exec(select(TeamAgent).where(TeamAgent.team_id == run.team_id).order_by(TeamAgent.position.desc())))
    pos = links[0].position + 1 if links else 0
    session.add(TeamAgent(team_id=run.team_id, agent_id=clone.id, position=pos, params_json='{}'))
    session.commit()
    return {'ok': True, 'agent_id': clone.id}


@router.get('/{run_id}')
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    messages = list(session.exec(select(Message).where(Message.run_id == run_id)))
    return {'run': run, 'messages': messages}




@router.get('/{run_id}/trace')
def run_trace(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    return {'ok': True, 'run_id': run_id, 'trace': get_run_trace(session, run_id)}

@router.get('/{run_id}/stream')
def stream_run(run_id: int, session: Session = Depends(get_session)):
    messages = list(session.exec(select(Message).where(Message.run_id == run_id).order_by(Message.id)))

    async def event_gen():
        for m in messages:
            yield f"data: {json.dumps({'role': m.role, 'content': m.content})}\n\n"
            await asyncio.sleep(0.01)

    return StreamingResponse(event_gen(), media_type='text/event-stream')


@router.get('/{run_id}/plan')
def run_plan(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    payload = list_plan(session, run_id)
    if not payload.get('ok'):
        return {'ok': True, 'plan': None, 'subgoals': []}
    return payload


@router.get('/{run_id}/handoffs')
def run_handoffs(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    items = list(session.exec(select(AgentHandoff).where(AgentHandoff.run_id == run_id).order_by(AgentHandoff.id)))
    return {'ok': True, 'items': items}


@router.get('/{run_id}/collaboration-trace')
def run_collaboration_trace(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    return {'ok': True, 'run_id': run_id, 'trace': collaboration_trace(session, run_id)}


@router.get('/{run_id}/team')
def run_team(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    plan = session.exec(select(TeamPlan).where(TeamPlan.run_id == run_id).order_by(TeamPlan.id.desc())).first()
    subgoals = list(session.exec(select(TeamSubgoal).where(TeamSubgoal.run_id == run_id).order_by(TeamSubgoal.id)))
    metric = session.exec(select(CollaborationMetric).where(CollaborationMetric.run_id == run_id)).first()
    handoffs = list(session.exec(select(AgentHandoff).where(AgentHandoff.run_id == run_id).order_by(AgentHandoff.id)))
    return {'ok': True, 'plan': plan, 'subgoals': subgoals, 'handoffs': handoffs, 'metric': metric}


@router.get('/{run_id}/actions')
def run_actions(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    requests = list(session.exec(select(ActionRequest).where(ActionRequest.run_id == run_id).order_by(ActionRequest.id.desc())))
    req_ids = [r.id for r in requests if r.id]
    executions = list(session.exec(select(ActionExecution).where(ActionExecution.action_request_id.in_(req_ids)).order_by(ActionExecution.id.desc()))) if req_ids else []
    exec_ids = [e.id for e in executions if e.id]
    artifacts = list(session.exec(select(ActionArtifact).where(ActionArtifact.action_execution_id.in_(exec_ids)).order_by(ActionArtifact.id.desc()))) if exec_ids else []
    return {'ok': True, 'requests': requests, 'executions': executions, 'artifacts': artifacts}
