from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlmodel import Session, select

from app.db import get_session
from app.models import Run, Team, Message, ToolCall
from app.services.snapshot_card import render_snapshot

router = APIRouter(tags=['snapshot'])


@router.get('/api/snapshot.png')
def snapshot(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    team = session.get(Team, run.team_id)
    msgs = list(session.exec(select(Message).where(Message.run_id == run_id).order_by(Message.id.desc()).limit(10)))
    tcount = len(list(session.exec(select(ToolCall).where(ToolCall.run_id == run_id))))
    lines = [f"{m.role}: {m.content}" for m in reversed(msgs)]
    png = render_snapshot(team.name if team else 'Unknown', run.mode, run.status, lines, tcount, team.version if team else 'n/a', team.marketplace_id if team else 'n/a')
    return Response(content=png, media_type='image/png')
