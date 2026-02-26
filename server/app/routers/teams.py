from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Team, TeamAgent
from app.schemas import TeamIn
from app.services.orchestration.templates import load_templates
from app.services.orchestration.yaml_loader import parse_team_yaml

router = APIRouter(prefix='/api/teams', tags=['teams'])


@router.get('/templates')
def templates():
    return {'templates': load_templates()}


@router.get('')
def list_teams(session: Session = Depends(get_session)):
    return list(session.exec(select(Team)))


@router.post('')
def create_team(payload: TeamIn, session: Session = Depends(get_session)):
    data = payload.model_dump()
    agent_ids = data.pop('agent_ids', [])
    team = Team(**data)
    session.add(team)
    session.commit()
    session.refresh(team)
    for idx, aid in enumerate(agent_ids):
        session.add(TeamAgent(team_id=team.id, agent_id=aid, position=idx))
    session.commit()
    return team


@router.post('/import-yaml')
def import_yaml(payload: dict):
    text = payload.get('yaml_text', '')
    try:
        return {'ok': True, 'team': parse_team_yaml(text)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post('/export-yaml')
def export_yaml(payload: dict):
    return {'yaml_text': payload.get('yaml_text', '')}
