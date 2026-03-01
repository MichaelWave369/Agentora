from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Workflow, WorkflowRun
from app.schemas import OperatorRunIn, OperatorStepDecisionIn
from app.services.runtime.operator import (
    advance_operator_run,
    get_operator_run_details,
    list_operator_runs,
    pause_operator_run,
    resume_operator_run,
    retry_operator_step,
    skip_operator_step,
    start_operator_run,
)

router = APIRouter(prefix='/api/operator', tags=['operator'])


def _run_payload(row):
    return {
        'id': row.id,
        'workflow_id': row.workflow_id,
        'run_id': row.run_id,
        'mode': row.mode,
        'worker_mode': row.worker_mode,
        'status': row.status,
        'summary': row.summary,
        'started_at': row.started_at.isoformat() if row.started_at else '',
        'finished_at': row.finished_at.isoformat() if row.finished_at else None,
    }


@router.get('/runs')
def runs(session: Session = Depends(get_session)):
    return {'ok': True, 'items': [_run_payload(x) for x in list_operator_runs(session)]}


@router.post('/runs')
def create_run(payload: OperatorRunIn, session: Session = Depends(get_session)):
    try:
        row = start_operator_run(session, workflow_id=payload.workflow_id, run_id=payload.run_id, mode=payload.mode, worker_mode=payload.worker_mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'item': _run_payload(row)}


@router.get('/runs/{run_id}')
def run_details(run_id: int, session: Session = Depends(get_session)):
    try:
        details = get_operator_run_details(session, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'run': _run_payload(details['run']), 'steps': details['steps'], 'requests': details['requests']}


@router.post('/runs/{run_id}/advance')
def advance(run_id: int, session: Session = Depends(get_session)):
    return {'ok': True, 'advanced': advance_operator_run(session, run_id)}


@router.post('/runs/{run_id}/pause')
def pause(run_id: int, session: Session = Depends(get_session)):
    try:
        op = pause_operator_run(session, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'item': _run_payload(op)}


@router.post('/runs/{run_id}/resume')
def resume(run_id: int, session: Session = Depends(get_session)):
    try:
        op = resume_operator_run(session, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    return {'ok': True, 'item': _run_payload(op)}


@router.post('/runs/{run_id}/retry-step')
def retry_step(run_id: int, payload: OperatorStepDecisionIn, session: Session = Depends(get_session)):
    try:
        step = retry_operator_step(session, run_id, payload.step_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'item': step}


@router.post('/runs/{run_id}/skip-step')
def skip_step(run_id: int, payload: OperatorStepDecisionIn, session: Session = Depends(get_session)):
    try:
        step = skip_operator_step(session, run_id, payload.step_id, payload.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'item': step}


@router.get('/workflows')
def workflows(session: Session = Depends(get_session)):
    items = list(session.exec(select(Workflow).order_by(Workflow.id.desc())))
    return {'ok': True, 'items': items}


@router.get('/workflows/{workflow_id}/history')
def workflow_history(workflow_id: int, session: Session = Depends(get_session)):
    items = list(session.exec(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id).order_by(WorkflowRun.id.desc())))
    return {'ok': True, 'items': items}
