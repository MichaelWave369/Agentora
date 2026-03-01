from __future__ import annotations

import json
from datetime import datetime

from sqlmodel import Session, select

from app.core.config import settings
from app.models import ActionExecution, ActionRequest, Workflow, WorkflowRun, WorkflowStep
from app.services.runtime.actions import create_action_request, execute_action_request
from app.services.runtime.trace import add_trace


def create_workflow(session: Session, name: str, description: str, params_schema: dict, steps: list[dict]) -> Workflow:
    wf = Workflow(name=name, description=description, params_schema_json=json.dumps(params_schema or {}), enabled=True)
    session.add(wf)
    session.commit()
    session.refresh(wf)
    for s in sorted(steps, key=lambda x: int(x.get('position', 0))):
        session.add(
            WorkflowStep(
                workflow_id=wf.id or 0,
                position=int(s.get('position', 0)),
                step_type=str(s.get('step_type', 'desktop')),
                tool_name=str(s.get('tool_name', '')),
                params_json=json.dumps(s.get('params', {})),
                requires_approval=bool(s.get('requires_approval', True)),
            )
        )
    session.commit()
    return wf


def run_workflow(session: Session, workflow_id: int, run_id: int = 0, inputs: dict | None = None) -> WorkflowRun:
    wf = session.get(Workflow, workflow_id)
    if not wf:
        raise ValueError('workflow_not_found')
    wr = WorkflowRun(workflow_id=workflow_id, run_id=run_id, status='running', input_json=json.dumps(inputs or {}))
    session.add(wr)
    session.commit()
    session.refresh(wr)

    add_trace(session, run_id or 0, 'browser_workflow_started', {'workflow_id': workflow_id, 'workflow_run_id': wr.id}, agent_id=0)
    start = datetime.utcnow()
    step_rows = list(session.exec(select(WorkflowStep).where(WorkflowStep.workflow_id == workflow_id).order_by(WorkflowStep.position)))

    outputs: list[dict] = []
    for idx, step in enumerate(step_rows):
        if (datetime.utcnow() - start).total_seconds() > settings.agentora_max_workflow_duration_seconds:
            wr.status = 'failed'
            wr.output_json = json.dumps({'error': 'workflow_timeout', 'outputs': outputs})
            wr.finished_at = datetime.utcnow()
            session.add(wr)
            session.commit()
            return wr
        if idx >= settings.agentora_max_action_steps:
            break
        params = json.loads(step.params_json or '{}')
        req = create_action_request(
            session,
            run_id=run_id or 0,
            agent_id=0,
            action_class='browser' if step.step_type.startswith('browser') else 'desktop',
            tool_name=step.tool_name,
            params=params,
            requested_worker=step.step_type in {'browser', 'shell'},
        )
        if req.status == 'approved':
            ex = execute_action_request(session, req.id)
            outputs.append({'step_id': step.id, 'action_id': req.id, 'execution_id': ex.id, 'status': ex.status})
        elif req.status == 'pending':
            outputs.append({'step_id': step.id, 'action_id': req.id, 'status': 'pending_approval'})
        else:
            outputs.append({'step_id': step.id, 'action_id': req.id, 'status': req.status})

    wr.status = 'done'
    wr.output_json = json.dumps({'outputs': outputs})
    wr.finished_at = datetime.utcnow()
    session.add(wr)
    add_trace(session, run_id or 0, 'browser_workflow_completed', {'workflow_id': workflow_id, 'workflow_run_id': wr.id, 'outputs': outputs[:20]}, agent_id=0)
    session.commit()
    session.refresh(wr)
    return wr


def list_workflow_runs(session: Session, workflow_id: int) -> list[WorkflowRun]:
    return list(session.exec(select(WorkflowRun).where(WorkflowRun.workflow_id == workflow_id).order_by(WorkflowRun.id.desc())))
