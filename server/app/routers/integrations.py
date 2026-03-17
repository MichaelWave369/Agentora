import json

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db import get_session
from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.phios_client import IntegrationClientError, PhiOSClient
from app.integrations.schemas import (
    ContextPackRequest,
    LaunchMissionRequest,
    PrepareMissionRequest,
    SoftwareTaskRequest,
    WritebackRequest,
)
from app.models import IntegrationSetting, Message, Run
from app.services.adapters.integrations import statuses
from app.services.integration_orchestrator import IntegrationOrchestrator

router = APIRouter(tags=['integrations'])


@router.get('/api/integrations/status')
def integration_status(session: Session = Depends(get_session)):
    return {'integrations': statuses(session)}


@router.post('/api/integrations/enable')
def integration_enable(payload: dict, session: Session = Depends(get_session)):
    row = session.get(IntegrationSetting, payload['name'])
    if not row:
        row = IntegrationSetting(name=payload['name'], enabled=False, config_json='{}')
    row.enabled = bool(payload.get('enabled', True))
    row.config_json = json.dumps(payload.get('config', {}))
    session.add(row)
    session.commit()
    return {'ok': True}


@router.post('/api/exports/growora')
def export_growora(payload: dict, session: Session = Depends(get_session)):
    run = session.get(Run, payload['run_id'])
    msgs = session.query(Message).filter(Message.run_id == payload['run_id']).all()
    return {
        'skill_graph': {'nodes': [{'id': 'skill-1', 'label': run.mode if run else 'unknown'}]},
        'micro_drills': [m.content[:80] for m in msgs[:3]],
    }


@router.get('/api/integrations/phios/health')
def phios_health():
    return PhiOSClient().healthcheck()


@router.get('/api/integrations/phios/persona/{persona_id}')
def phios_persona(persona_id: str):
    try:
        return PhiOSClient().get_persona(persona_id).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/phios/context-pack')
def phios_context_pack(payload: ContextPackRequest):
    try:
        return PhiOSClient().get_context_pack(payload).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/agentception/health')
def agentception_health():
    return AgentCeptionClient().healthcheck()


@router.post('/api/integrations/agentception/launch')
def integration_launch_legacy(payload: SoftwareTaskRequest, session: Session = Depends(get_session)):
    record = IntegrationOrchestrator(session).launch_from_request(payload)
    return record.model_dump(mode='json')


@router.get('/api/integrations/agentception/jobs/{job_id}')
def integration_job(job_id: str):
    try:
        return AgentCeptionClient().get_job_status(job_id).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/prepare')
def integration_prepare(payload: PrepareMissionRequest, session: Session = Depends(get_session)):
    try:
        packet = IntegrationOrchestrator(session).prepare_mission_context(payload)
        return packet.model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/launch')
def integration_launch(payload: LaunchMissionRequest, session: Session = Depends(get_session)):
    record = IntegrationOrchestrator(session).launch_software_mission(payload)
    return record.model_dump(mode='json')


@router.get('/api/integrations/runs')
def integration_runs(session: Session = Depends(get_session)):
    return [r.model_dump(mode='json') for r in IntegrationOrchestrator(session).list_runs()]


@router.get('/api/integrations/runs/{run_id}')
def integration_run(run_id: int, session: Session = Depends(get_session)):
    item = IntegrationOrchestrator(session).get_run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail='run not found')
    return item.model_dump(mode='json')


@router.post('/api/integrations/runs/{run_id}/refresh')
def integration_refresh(run_id: int, session: Session = Depends(get_session)):
    try:
        item = IntegrationOrchestrator(session).refresh_run(run_id)
        return item.model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/writeback')
def integration_writeback(run_id: int, payload: WritebackRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).writeback_run(run_id, payload.operator_notes, payload.tags)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/runs/{run_id}/timeline')
def integration_timeline(run_id: int, session: Session = Depends(get_session)):
    try:
        return {'run_id': run_id, 'events': IntegrationOrchestrator(session).run_timeline(run_id)}
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
