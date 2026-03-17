import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session

from app.core.config import settings
from app.db import get_session
from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.phios_client import IntegrationClientError, PhiOSClient
from app.integrations.schemas import ContextPackRequest, LaunchMissionRequest, PrepareMissionRequest, SoftwareTaskRequest, WritebackRequest
from app.models import IntegrationSetting, Message, Run
from app.services.adapters.integrations import statuses
from app.services.integration_orchestrator import IntegrationOrchestrator

router = APIRouter(tags=['integrations'])

MCP_MUTATING_TOOLS = {'launch_mission', 'refresh_mission', 'writeback_mission'}


def _enforce_mcp_policy(tool: str, x_api_key: str | None):
    if not settings.agentora_missions_mcp_enabled:
        return {'ok': False, 'detail': 'MCP mission exposure disabled (set AGENTORA_MISSIONS_MCP_ENABLED=true).'}
    if settings.agentora_missions_mcp_api_key and x_api_key != settings.agentora_missions_mcp_api_key:
        return {'ok': False, 'detail': 'Invalid or missing MCP API key.'}
    allowed = settings.missions_mcp_allowed_tools
    if allowed and tool and tool not in allowed:
        return {'ok': False, 'detail': f'Tool not allowed by policy: {tool}'}
    if settings.agentora_missions_mcp_read_only and tool in MCP_MUTATING_TOOLS:
        return {'ok': False, 'detail': f'MCP is read-only; tool blocked: {tool}'}
    return None


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
    return {'skill_graph': {'nodes': [{'id': 'skill-1', 'label': run.mode if run else 'unknown'}]}, 'micro_drills': [m.content[:80] for m in msgs[:3]]}


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
        return IntegrationOrchestrator(session).prepare_mission_context(payload).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/launch')
def integration_launch(payload: LaunchMissionRequest, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).launch_software_mission(payload).model_dump(mode='json')


@router.get('/api/integrations/runs')
def integration_runs(
    status: str | None = Query(default=None),
    repo: str | None = Query(default=None),
    persona_id: str | None = Query(default=None),
    writeback_status: str | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    orchestrator = IntegrationOrchestrator(session)
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    rows = orchestrator.list_runs(status=status, repo=repo, persona_id=persona_id, writeback_status=writeback_status, start_date=start_dt, end_date=end_dt, search=search, limit=limit, offset=offset)
    return [r.model_dump(mode='json') for r in rows]


@router.get('/api/integrations/runs/compare')
def integration_compare(left_run_id: int, right_run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).compare_runs(left_run_id, right_run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/runs/{run_id}')
def integration_run(run_id: int, session: Session = Depends(get_session)):
    item = IntegrationOrchestrator(session).get_run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail='run not found')
    return item.model_dump(mode='json')


@router.post('/api/integrations/runs/{run_id}/refresh')
def integration_refresh(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).refresh_run(run_id).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/watch')
def integration_watch(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).set_watch(run_id, True).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/unwatch')
def integration_unwatch(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).set_watch(run_id, False).model_dump(mode='json')
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


@router.get('/api/integrations/metrics')
def integration_metrics(session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_metrics()


@router.get('/api/integrations/watcher/events')
def integration_watcher_events(limit: int = 100, session: Session = Depends(get_session)):
    return {'events': IntegrationOrchestrator(session).list_watcher_events(limit=limit)}


@router.get('/api/integrations/insights')
def integration_insights(session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_insights()


@router.get('/api/integrations/mcp/capabilities')
def integration_mcp_capabilities(x_api_key: str | None = Header(default=None, alias='X-API-Key')):
    policy = _enforce_mcp_policy('', x_api_key)
    if policy:
        return policy
    tools = ['prepare_mission', 'launch_mission', 'refresh_mission', 'writeback_mission', 'get_mission', 'list_missions', 'get_mission_timeline']
    allowed = settings.missions_mcp_allowed_tools
    if allowed:
        tools = [t for t in tools if t in allowed]
    return {'ok': True, 'read_only': settings.agentora_missions_mcp_read_only, 'tools': tools}


@router.post('/api/integrations/mcp/call')
def integration_mcp_call(payload: dict, session: Session = Depends(get_session), x_api_key: str | None = Header(default=None, alias='X-API-Key')):
    tool = payload.get('tool', '')
    policy = _enforce_mcp_policy(tool, x_api_key)
    if policy:
        return policy
    args = payload.get('args', {})
    orchestrator = IntegrationOrchestrator(session)
    try:
        if tool == 'prepare_mission':
            return {'ok': True, 'result': orchestrator.prepare_mission_context(PrepareMissionRequest(**args)).model_dump(mode='json')}
        if tool == 'launch_mission':
            return {'ok': True, 'result': orchestrator.launch_software_mission(LaunchMissionRequest(**args)).model_dump(mode='json')}
        if tool == 'refresh_mission':
            return {'ok': True, 'result': orchestrator.refresh_run(int(args['run_id'])).model_dump(mode='json')}
        if tool == 'writeback_mission':
            return {'ok': True, 'result': orchestrator.writeback_run(int(args['run_id']), args.get('operator_notes', ''), args.get('tags', []))}
        if tool == 'get_mission':
            record = orchestrator.get_run(int(args['run_id']))
            return {'ok': bool(record), 'result': record.model_dump(mode='json') if record else None}
        if tool == 'list_missions':
            items = orchestrator.list_runs(limit=int(args.get('limit', 20)))
            return {'ok': True, 'result': [x.model_dump(mode='json') for x in items]}
        if tool == 'get_mission_timeline':
            return {'ok': True, 'result': orchestrator.run_timeline(int(args['run_id']))}
        return {'ok': False, 'detail': f'Unsupported tool: {tool}'}
    except Exception as exc:
        return {'ok': False, 'detail': str(exc)}
