import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Agent, AgentCapabilityProfile
from app.schemas import AgentCapabilityIn, AgentIn
from app.services.runtime.team import ensure_capability_profile

router = APIRouter(prefix='/api/agents', tags=['agents'])


def _agent_payload(a: Agent) -> dict:
    return {
        'id': a.id,
        'name': a.name,
        'model': a.model,
        'role': a.role,
        'system_prompt': a.system_prompt,
        'tools_json': a.tools_json,
        'memory_mode': a.memory_mode,
        'created_at': a.created_at.isoformat() if a.created_at else '',
    }


@router.get('')
def list_agents(session: Session = Depends(get_session)):
    return [_agent_payload(a) for a in session.exec(select(Agent))]


@router.post('')
def create_agent(payload: AgentIn, session: Session = Depends(get_session)):
    obj = Agent(**payload.model_dump(exclude={'tools'}), tools_json=json.dumps(payload.tools))
    session.add(obj)
    session.commit()
    session.refresh(obj)
    ensure_capability_profile(session, obj)
    return _agent_payload(obj)


@router.get('/capabilities')
def list_capabilities(session: Session = Depends(get_session)):
    profiles = list(session.exec(select(AgentCapabilityProfile).order_by(AgentCapabilityProfile.id.desc())))
    return {'ok': True, 'items': profiles}


@router.post('/{agent_id}/capabilities')
def upsert_capabilities(agent_id: int, payload: AgentCapabilityIn, session: Session = Depends(get_session)):
    agent = session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, 'agent not found')
    profile = session.exec(select(AgentCapabilityProfile).where(AgentCapabilityProfile.agent_id == agent_id)).first()
    if not profile:
        profile = AgentCapabilityProfile(agent_id=agent_id)

    profile.preferred_model_role = payload.preferred_model_role
    profile.allowed_tools_json = json.dumps(payload.allowed_tools)
    profile.max_tool_steps = payload.max_tool_steps
    profile.can_critique = payload.can_critique
    profile.can_verify = payload.can_verify
    profile.can_delegate = payload.can_delegate
    profile.can_use_workers = payload.can_use_workers
    profile.memory_scope = payload.memory_scope
    profile.preferred_team_mode = payload.preferred_team_mode
    profile.confidence_weight = payload.confidence_weight
    profile.updated_at = datetime.utcnow()
    session.add(profile)
    session.commit()
    session.refresh(profile)
    return {'ok': True, 'item': profile}
