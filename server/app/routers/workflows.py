from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import Workflow, WorkflowRun, WorkflowStep
from app.schemas import WorkflowIn, WorkflowRunIn
from app.services.runtime.workflows import create_workflow, list_workflow_runs, run_workflow

router = APIRouter(prefix='/api/workflows', tags=['workflows'])


def _wf_payload(w: Workflow) -> dict:
    return {
        'id': w.id,
        'name': w.name,
        'description': w.description,
        'params_schema_json': w.params_schema_json,
        'enabled': w.enabled,
        'created_at': w.created_at.isoformat() if w.created_at else '',
    }


def _step_payload(s: WorkflowStep) -> dict:
    return {
        'id': s.id,
        'workflow_id': s.workflow_id,
        'position': s.position,
        'step_type': s.step_type,
        'tool_name': s.tool_name,
        'params_json': s.params_json,
        'requires_approval': s.requires_approval,
    }


def _run_payload(r: WorkflowRun) -> dict:
    return {
        'id': r.id,
        'workflow_id': r.workflow_id,
        'run_id': r.run_id,
        'status': r.status,
        'input_json': r.input_json,
        'output_json': r.output_json,
        'started_at': r.started_at.isoformat() if r.started_at else '',
        'finished_at': r.finished_at.isoformat() if r.finished_at else None,
    }


@router.get('')
def list_workflows(session: Session = Depends(get_session)):
    items = list(session.exec(select(Workflow).order_by(Workflow.id.desc())))
    return {'ok': True, 'items': [_wf_payload(x) for x in items]}


@router.post('')
def create(payload: WorkflowIn, session: Session = Depends(get_session)):
    wf = create_workflow(
        session,
        name=payload.name,
        description=payload.description,
        params_schema=payload.params_schema,
        steps=[s.model_dump() for s in payload.steps],
    )
    return {'ok': True, 'item': _wf_payload(wf)}


@router.get('/{workflow_id}')
def get_workflow(workflow_id: int, session: Session = Depends(get_session)):
    wf = session.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(404, 'workflow not found')
    steps = list(session.exec(select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id).order_by(WorkflowStep.position)))
    return {'ok': True, 'item': _wf_payload(wf), 'steps': [_step_payload(s) for s in steps]}


@router.post('/{workflow_id}/run')
def run(workflow_id: int, payload: WorkflowRunIn, session: Session = Depends(get_session)):
    try:
        wr = run_workflow(session, workflow_id=workflow_id, run_id=payload.run_id, inputs=payload.inputs)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'item': _run_payload(wr)}


@router.get('/{workflow_id}/runs')
def runs(workflow_id: int, session: Session = Depends(get_session)):
    return {'ok': True, 'items': [_run_payload(r) for r in list_workflow_runs(session, workflow_id)]}
