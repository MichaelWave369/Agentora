from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models import ActionExecution, ActionRequest, ApprovalDecisionLog
from app.schemas import ActionDecisionIn, ActionRequestIn
from app.services.runtime.actions import approve_action, create_action_request, deny_action

router = APIRouter(prefix='/api/actions', tags=['actions'])


def _req_payload(a: ActionRequest) -> dict:
    return {
        'id': a.id,
        'run_id': a.run_id,
        'agent_id': a.agent_id,
        'subgoal_id': a.subgoal_id,
        'action_class': a.action_class,
        'tool_name': a.tool_name,
        'params_json': a.params_json,
        'policy_decision': a.policy_decision,
        'status': a.status,
        'requires_approval': a.requires_approval,
        'approval_reason': a.policy_decision,
        'scope_preview': a.params_json[:300],
        'requested_worker': a.requested_worker,
        'requested_at': a.requested_at.isoformat() if a.requested_at else '',
    }


def _exec_payload(e: ActionExecution) -> dict:
    return {
        'id': e.id,
        'action_request_id': e.action_request_id,
        'run_id': e.run_id,
        'status': e.status,
        'execution_mode': e.execution_mode,
        'worker_job_id': e.worker_job_id,
        'started_at': e.started_at.isoformat() if e.started_at else '',
        'finished_at': e.finished_at.isoformat() if e.finished_at else None,
        'result_json': e.result_json,
        'error': e.error,
    }


@router.get('/pending')
def pending_actions(session: Session = Depends(get_session)):
    items = list(session.exec(select(ActionRequest).where(ActionRequest.status == 'pending').order_by(ActionRequest.id.desc())))
    return {'ok': True, 'items': [_req_payload(x) for x in items]}


@router.get('/history')
def action_history(session: Session = Depends(get_session)):
    items = list(session.exec(select(ActionRequest).order_by(ActionRequest.id.desc()).limit(200)))
    executions = list(session.exec(select(ActionExecution).order_by(ActionExecution.id.desc()).limit(200)))
    logs = list(session.exec(select(ApprovalDecisionLog).order_by(ApprovalDecisionLog.id.desc()).limit(200)))
    return {'ok': True, 'items': [_req_payload(x) for x in items], 'executions': [_exec_payload(x) for x in executions], 'approval_history': logs}


@router.post('')
def request_action(payload: ActionRequestIn, session: Session = Depends(get_session)):
    req = create_action_request(
        session,
        run_id=payload.run_id,
        agent_id=payload.agent_id,
        subgoal_id=payload.subgoal_id,
        action_class=payload.action_class,
        tool_name=payload.tool_name,
        params=payload.params,
        requested_worker=payload.requested_worker,
    )
    return {'ok': True, 'item': _req_payload(req)}


@router.post('/{action_id}/approve')
def approve(action_id: int, payload: ActionDecisionIn, session: Session = Depends(get_session)):
    try:
        ex = approve_action(session, action_id, decided_by='api', reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'execution': _exec_payload(ex)}


@router.post('/{action_id}/deny')
def deny(action_id: int, payload: ActionDecisionIn, session: Session = Depends(get_session)):
    try:
        req = deny_action(session, action_id, decided_by='api', reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {'ok': True, 'item': _req_payload(req)}
