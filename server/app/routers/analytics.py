import csv
import io
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlmodel import Session, select

from app.db import get_session
from app.models import RunMetric, Run, TemplateUsage

router = APIRouter(prefix='/api/analytics', tags=['analytics'])


@router.get('/overview')
def overview(session: Session = Depends(get_session)):
    metrics = list(session.exec(select(RunMetric)))
    runs = list(session.exec(select(Run)))
    usages = list(session.exec(select(TemplateUsage)))
    return {
        'runs': len(runs),
        'total_tokens_out': sum(m.tokens_out for m in metrics),
        'total_tool_calls': sum(m.tool_calls for m in metrics),
        'top_templates': [{'template_id': u.template_id, 'runs_count': u.runs_count} for u in usages],
    }


@router.get('/runs/{run_id}')
def run_metrics(run_id: int, session: Session = Depends(get_session)):
    rows = list(session.exec(select(RunMetric).where(RunMetric.run_id == run_id)))
    return {'metrics': rows}


@router.get('/export.csv')
def export_csv(session: Session = Depends(get_session)):
    rows = list(session.exec(select(RunMetric)))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['run_id', 'agent_id', 'tokens_in', 'tokens_out', 'seconds', 'tool_calls'])
    for r in rows:
        w.writerow([r.run_id, r.agent_id, r.tokens_in, r.tokens_out, r.seconds, r.tool_calls])
    return Response(content=buf.getvalue(), media_type='text/csv')
