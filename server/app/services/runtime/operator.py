from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.models import OperatorRun, OperatorStep, WorkflowStep, Workflow, ActionRequest
from app.services.runtime.actions import create_action_request, execute_action_request
from app.services.runtime.trace import add_trace


def _step_payload(step: WorkflowStep) -> dict:
    return json.loads(step.params_json or '{}')


def start_operator_run(session: Session, workflow_id: int, run_id: int, mode: str = 'stepwise', worker_mode: str = 'auto') -> OperatorRun:
    wf = session.get(Workflow, workflow_id)
    if not wf:
        raise ValueError('workflow_not_found')
    op = OperatorRun(workflow_id=workflow_id, run_id=run_id, mode=mode, worker_mode=worker_mode, status='running')
    session.add(op)
    session.commit()
    session.refresh(op)

    steps = list(session.exec(select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id).order_by(WorkflowStep.position)))
    for s in steps[: settings.agentora_max_action_steps]:
        session.add(OperatorStep(operator_run_id=op.id or 0, workflow_step_id=s.id, position=s.position, status='queued'))
    session.commit()
    add_trace(session, run_id, 'operator_mode_started', {'operator_run_id': op.id, 'workflow_id': workflow_id, 'mode': mode}, agent_id=0)
    session.commit()

    if mode == 'auto':
        while True:
            advanced = advance_operator_run(session, op.id or 0)
            if not advanced:
                break
    return op


def advance_operator_run(session: Session, operator_run_id: int) -> bool:
    op = session.get(OperatorRun, operator_run_id)
    if not op or op.status != 'running':
        return False
    step = session.exec(
        select(OperatorStep)
        .where(OperatorStep.operator_run_id == operator_run_id, OperatorStep.status.in_(['queued', 'failed']))
        .order_by(OperatorStep.position)
    ).first()
    if not step:
        op.status = 'done'
        op.finished_at = datetime.utcnow()
        op.summary = 'operator run completed'
        session.add(op)
        add_trace(session, op.run_id, 'operator_run_completed', {'operator_run_id': op.id}, agent_id=0)
        session.commit()
        return False

    wf_step = session.get(WorkflowStep, step.workflow_step_id or 0)
    if not wf_step:
        step.status = 'failed'
        step.error = 'workflow_step_missing'
        session.add(step)
        session.commit()
        return True

    params = _step_payload(wf_step)
    req = create_action_request(
        session,
        run_id=op.run_id,
        agent_id=0,
        action_class='browser' if wf_step.step_type.startswith('browser') else 'desktop',
        tool_name=wf_step.tool_name,
        params=params,
        requested_worker=op.worker_mode == 'prefer_worker',
    )
    step.action_request_id = req.id
    step.started_at = datetime.utcnow()
    step.status = 'waiting_approval' if req.status == 'pending' else 'running'
    session.add(step)
    add_trace(session, op.run_id, 'operator_step_requested', {'operator_run_id': op.id, 'step_id': step.id, 'action_request_id': req.id, 'tool_name': req.tool_name}, agent_id=0)
    session.commit()

    if req.status == 'approved':
        ex = execute_action_request(session, req.id or 0)
        step.status = 'done' if ex.status == 'done' else 'failed'
        step.finished_at = datetime.utcnow()
        step.result_json = ex.result_json
        step.error = ex.error
        session.add(step)
        add_trace(session, op.run_id, 'operator_step_executed' if ex.status == 'done' else 'operator_step_failed', {'operator_run_id': op.id, 'step_id': step.id, 'execution_status': ex.status}, agent_id=0)
        session.commit()
    return True


def pause_operator_run(session: Session, operator_run_id: int) -> OperatorRun:
    op = session.get(OperatorRun, operator_run_id)
    if not op:
        raise ValueError('operator_run_not_found')
    op.status = 'paused'
    session.add(op)
    add_trace(session, op.run_id, 'operator_run_paused', {'operator_run_id': op.id}, agent_id=0)
    session.commit()
    return op


def resume_operator_run(session: Session, operator_run_id: int) -> OperatorRun:
    op = session.get(OperatorRun, operator_run_id)
    if not op:
        raise ValueError('operator_run_not_found')
    op.status = 'running'
    session.add(op)
    add_trace(session, op.run_id, 'operator_run_resumed', {'operator_run_id': op.id}, agent_id=0)
    session.commit()
    return op


def retry_operator_step(session: Session, operator_run_id: int, step_id: int) -> OperatorStep:
    step = session.get(OperatorStep, step_id)
    if not step or step.operator_run_id != operator_run_id:
        raise ValueError('operator_step_not_found')
    if step.retries >= 3:
        raise ValueError('retry_limit_reached')
    step.status = 'failed'
    step.retries += 1
    step.error = ''
    session.add(step)
    session.commit()
    advance_operator_run(session, operator_run_id)
    session.refresh(step)
    return step


def skip_operator_step(session: Session, operator_run_id: int, step_id: int, reason: str = '') -> OperatorStep:
    step = session.get(OperatorStep, step_id)
    if not step or step.operator_run_id != operator_run_id:
        raise ValueError('operator_step_not_found')
    step.status = 'skipped'
    step.finished_at = datetime.utcnow()
    step.error = reason
    session.add(step)
    session.commit()
    return step


def list_operator_runs(session: Session) -> list[OperatorRun]:
    return list(session.exec(select(OperatorRun).order_by(OperatorRun.id.desc())))


def get_operator_run_details(session: Session, operator_run_id: int) -> dict:
    op = session.get(OperatorRun, operator_run_id)
    if not op:
        raise ValueError('operator_run_not_found')
    steps = list(session.exec(select(OperatorStep).where(OperatorStep.operator_run_id == operator_run_id).order_by(OperatorStep.position)))
    action_ids = [s.action_request_id for s in steps if s.action_request_id]
    approvals: list[ActionRequest] = list(session.exec(select(ActionRequest).where(ActionRequest.id.in_(action_ids)))) if action_ids else []
    return {'run': op, 'steps': steps, 'requests': approvals}
