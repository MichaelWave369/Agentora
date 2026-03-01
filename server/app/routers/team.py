from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Run, Team, TeamAgent, Agent
from app.schemas import TeamPlanPreviewIn, TeamPlanRequestIn
from app.services.runtime.team import create_team_plan, list_plan

router = APIRouter(prefix='/api/team', tags=['team'])


@router.post('/modes/preview')
def preview_mode(payload: TeamPlanPreviewIn):
    text = payload.prompt.lower()
    if len(text) < 120 and 'and' not in text and 'compare' not in text:
        return {'ok': True, 'recommended_mode': 'fast', 'reason': 'simple_prompt'}
    return {'ok': True, 'recommended_mode': payload.mode or 'careful', 'reason': 'complex_prompt'}


@router.post('/plan')
def create_plan(payload: TeamPlanRequestIn, session: Session = Depends(get_session)):
    run = session.get(Run, payload.run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    team = session.get(Team, run.team_id)
    links = list(session.exec(select(TeamAgent).where(TeamAgent.team_id == team.id).order_by(TeamAgent.position))) if team else []
    agents = [session.get(Agent, link.agent_id) for link in links if session.get(Agent, link.agent_id)]
    plan = create_team_plan(session, run_id=run.id, prompt=payload.prompt, agents=agents, requested_mode=payload.mode)
    return list_plan(session, run_id=run.id)
