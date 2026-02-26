from pathlib import Path
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Run, Message, ToolCall

router = APIRouter(prefix='/api/exports', tags=['exports'])


@router.get('/run/{run_id}')
def export_run(run_id: int, session: Session = Depends(get_session)):
    run = session.get(Run, run_id)
    if not run:
        raise HTTPException(404, 'run not found')
    messages = list(session.exec(select(Message).where(Message.run_id == run_id)))
    calls = list(session.exec(select(ToolCall).where(ToolCall.run_id == run_id)))
    outdir = Path('server/data/artifacts') / f'run_{run_id}'
    outdir.mkdir(parents=True, exist_ok=True)
    run_json = outdir / 'run.json'
    report = outdir / 'report.md'
    payload = {
        'run': run.model_dump(),
        'messages': [m.model_dump() for m in messages],
        'tool_calls': [c.model_dump() for c in calls],
    }
    run_json.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    report.write_text('# Agentora Report\n\n## Executive Summary\n\nTODO\n\n## Debate Notes\n\nTODO\n', encoding='utf-8')
    return {'run_json': str(run_json), 'report_md': str(report)}
