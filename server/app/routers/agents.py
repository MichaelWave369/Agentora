import json
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models import Agent
from app.schemas import AgentIn

router = APIRouter(prefix='/api/agents', tags=['agents'])


@router.get('')
def list_agents(session: Session = Depends(get_session)):
    return [a.model_dump() for a in session.exec(select(Agent))]


@router.post('')
def create_agent(payload: AgentIn, session: Session = Depends(get_session)):
    obj = Agent(**payload.model_dump(exclude={'tools'}), tools_json=json.dumps(payload.tools))
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj.model_dump()
