import asyncio
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import Run, Team, Message
from app.schemas import RunIn
from app.services.orchestration.engine import OrchestrationEngine

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
    run = Run(team_id=payload.team_id, mode=team.mode, status='running', max_turns=payload.max_turns, max_seconds=payload.max_seconds, token_budget=payload.token_budget)
    session.add(run)
    session.commit()
    session.refresh(run)
    state = await engine.execute(session, run, payload.prompt, payload.reflection)
    return {'run_id': run.id, 'messages': state.messages}


@router.get('/{run_id}')
def get_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    messages = list(session.exec(select(Message).where(Message.run_id == run_id)))
    return {'run': run, 'messages': messages}


@router.get('/{run_id}/stream')
def stream_run(run_id: int, session: Session = Depends(get_session)):
    messages = list(session.exec(select(Message).where(Message.run_id == run_id).order_by(Message.id)))

    async def event_gen():
        for m in messages:
            yield f"data: {m.role}: {m.content}\n\n"
            await asyncio.sleep(0.01)

    return StreamingResponse(event_gen(), media_type='text/event-stream')
