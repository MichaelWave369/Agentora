import json
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlmodel import Session

from app.core.config import settings
from app.db import get_session
from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.phios_client import IntegrationClientError, PhiOSClient
from app.integrations.schemas import ApplyPolicyTemplateRequest, BranchSetCreateRequest, ContextPackRequest, DecisionStateRequest, LaunchMissionRequest, PatternActionRequest, PersonaBranchSetCreateRequest, PersonaPolicyCheckRequest, PortfolioDecisionRequest, PrepareMissionRequest, ReplayDraftRequest, ReplayLaunchRequest, SoftwareTaskRequest, WritebackRequest
from app.models import IntegrationRun, IntegrationSetting, Message, Run
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


@router.get('/api/integrations/personas')
def integration_personas(session: Session = Depends(get_session)):
    return {'personas': IntegrationOrchestrator(session).list_personas()}


@router.get('/api/integrations/personas/{persona_id}')
def integration_persona_detail(persona_id: str, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).resolve_persona(persona_id)
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
    return IntegrationOrchestrator(session).launch_from_request(payload).model_dump(mode='json')


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
    confidence_level: str | None = Query(default=None),
    mission_score_min: int | None = Query(default=None),
    mission_score_max: int | None = Query(default=None),
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_session),
):
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    rows = IntegrationOrchestrator(session).list_runs(status=status, repo=repo, persona_id=persona_id, writeback_status=writeback_status, confidence_level=confidence_level, mission_score_min=mission_score_min, mission_score_max=mission_score_max, start_date=start_dt, end_date=end_dt, search=search, limit=limit, offset=offset)
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


@router.get('/api/integrations/runs/{run_id}/snapshot')
def integration_run_snapshot(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_snapshot(run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/fork')
def integration_fork(run_id: int, payload: ReplayDraftRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).create_replay_draft(run_id, payload.model_dump(mode='json')).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/replay')
def integration_replay(run_id: int, payload: ReplayDraftRequest, session: Session = Depends(get_session)):
    try:
        draft = IntegrationOrchestrator(session).create_replay_draft(run_id, payload.model_dump(mode='json'))
        launched = IntegrationOrchestrator(session).launch_replay_draft(draft.id, dry_run=bool(payload.dry_run))
        return {'draft': draft.model_dump(mode='json'), 'launched': launched.model_dump(mode='json')}
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/launch-from-draft')
def integration_launch_from_draft(run_id: int, payload: ReplayLaunchRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).launch_replay_draft(run_id, dry_run=payload.dry_run).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/runs/{run_id}/lineage')
def integration_lineage(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_lineage(run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/lineage/{root_run_id}')
def integration_lineage_root(root_run_id: int, session: Session = Depends(get_session)):
    try:
        return {'root_run_id': root_run_id, 'descendants': IntegrationOrchestrator(session).get_descendants(root_run_id)}
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/branch-strategies')
def integration_branch_strategies(session: Session = Depends(get_session)):
    return {'presets': IntegrationOrchestrator(session).get_branch_strategy_presets()}


@router.post('/api/integrations/runs/{run_id}/branch-set')
def integration_branch_set(run_id: int, payload: BranchSetCreateRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).create_branch_set(run_id, payload.model_dump(mode='json')).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/persona-overlays')
def integration_persona_overlays(session: Session = Depends(get_session)):
    return {'overlays': IntegrationOrchestrator(session).get_persona_strategy_overlays()}


@router.get('/api/integrations/policy-templates')
def integration_policy_templates(session: Session = Depends(get_session)):
    return {'templates': IntegrationOrchestrator(session).list_policy_templates()}


@router.get('/api/integrations/policy-templates/{template_name}')
def integration_policy_template(template_name: str, session: Session = Depends(get_session)):
    try:
        return {'template_name': template_name, 'template': IntegrationOrchestrator(session).get_policy_template(template_name)}
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/persona-branch-set')
def integration_persona_branch_set(run_id: int, payload: PersonaBranchSetCreateRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).create_persona_branch_set(run_id, payload.model_dump(mode='json')).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/runs/{run_id}/portfolio')
def integration_portfolio_by_run(run_id: int, branch_set_id: str | None = None, session: Session = Depends(get_session)):
    try:
        run = IntegrationOrchestrator(session).get_run(run_id)
        if not run:
            raise IntegrationClientError(f'Run {run_id} not found')
        root_id = run.root_run_id or run.parent_run_id or run.id
        return IntegrationOrchestrator(session).get_branch_portfolio(root_id, branch_set_id=branch_set_id).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/lineage/{root_run_id}/portfolio')
def integration_portfolio_by_root(root_run_id: int, branch_set_id: str | None = None, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_branch_portfolio(root_run_id, branch_set_id=branch_set_id).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/lineage/{root_run_id}/decision-summary')
def integration_decision_summary(root_run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_root_decision_summary(root_run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/lineage/{root_run_id}/persona-portfolio')
def integration_persona_portfolio(root_run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_persona_portfolio(root_run_id).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/lineage/{root_run_id}/persona-summary')
def integration_persona_summary(root_run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_persona_performance_summary(root_run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/override')
def integration_override(run_id: int, payload: PortfolioDecisionRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).apply_operator_override(run_id, payload.model_dump(mode='json')).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/apply-policy-template')
def integration_apply_policy_template(run_id: int, payload: ApplyPolicyTemplateRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).apply_policy_template(run_id, payload.template_name)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/shortlist')
def integration_shortlist(run_id: int, payload: DecisionStateRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).set_branch_decision(run_id, shortlisted=True, eliminated=False, decision_note=payload.decision_note).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/eliminate')
def integration_eliminate(run_id: int, payload: DecisionStateRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).set_branch_decision(run_id, shortlisted=False, eliminated=True, decision_note=payload.decision_note).model_dump(mode='json')
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc



@router.get('/api/integrations/lineage/{root_run_id}/decision-audit')
def integration_lineage_decision_audit(root_run_id: int, session: Session = Depends(get_session)):
    try:
        descendants = IntegrationOrchestrator(session).get_descendants(root_run_id)
        run_ids = [root_run_id] + [d['id'] for d in descendants]
        events = []
        for rid in run_ids:
            events.extend(IntegrationOrchestrator(session).list_operator_decision_events(rid, limit=50))
        events = sorted(events, key=lambda x: x.get('created_at', ''), reverse=True)
        return {'root_run_id': root_run_id, 'events': events[:200]}
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/runs/{run_id}/provenance')
def integration_provenance(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_provenance(run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/runs/{run_id}/decision-events')
def integration_decision_events(run_id: int, limit: int = 100, session: Session = Depends(get_session)):
    try:
        return {'events': IntegrationOrchestrator(session).list_operator_decision_events(run_id, limit=limit)}
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/runs/{run_id}/persona-compare')
def integration_persona_compare(run_id: int, other_run_id: int | None = None, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_persona_delta_compare(run_id, other_run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/runs/{run_id}/policy-check')
def integration_policy_check(run_id: int, payload: PersonaPolicyCheckRequest, session: Session = Depends(get_session)):
    row = IntegrationOrchestrator(session).get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail='run not found')
    real = session.get(IntegrationRun, run_id)
    if not real:
        raise HTTPException(status_code=404, detail='run not found')
    return IntegrationOrchestrator(session).evaluate_persona_policy(real, action=payload.action)


@router.get('/api/integrations/runs/{run_id}/audit-summary')
def integration_audit_summary(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).get_audit_summary(run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.get('/api/integrations/alerts/events')
def integration_alert_events(limit: int = 50, session: Session = Depends(get_session)):
    return {'events': IntegrationOrchestrator(session).list_alert_events(limit=limit)}


@router.get('/api/integrations/retention')
def integration_retention(session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_retention_status()


@router.post('/api/integrations/retention/compact')
def integration_compact(session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).compact_events()


@router.get('/api/integrations/analytics/cache')
def integration_analytics_cache(session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).analytics_cache_status()


@router.post('/api/integrations/analytics/cache/invalidate')
def integration_analytics_cache_invalidate(payload: dict, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).invalidate_analytics_cache(payload.get('prefix'))


@router.get('/api/integrations/insights')
def integration_insights(session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_insights()


@router.get('/api/integrations/persona-insights')
def integration_persona_insights(root_run_id: int | None = None, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_persona_performance_summary(root_run_id)


@router.get('/api/integrations/persona-trends')
def integration_persona_trends(window: str = '30d', repo: str | None = None, strategy: str | None = None, status: str | None = None, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_persona_trends(window=window, repo=repo, strategy=strategy, status=status)


@router.get('/api/integrations/persona-trends/matrix')
def integration_persona_matrix(window: str = '30d', repo: str | None = None, status: str | None = None, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_persona_strategy_matrix(window=window, repo=repo, status=status)


@router.get('/api/integrations/exports/persona-trends')
def integration_export_persona_trends(window: str = '30d', repo: str | None = None, strategy: str | None = None, status: str | None = None, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).export_persona_trends(window=window, repo=repo, strategy=strategy, status=status)


@router.get('/api/integrations/exports/persona-matrix')
def integration_export_persona_matrix(window: str = '30d', repo: str | None = None, status: str | None = None, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).export_persona_matrix(window=window, repo=repo, status=status)


@router.get('/api/integrations/exports/audit-summary')
def integration_export_audit_summary(root_run_id: int | None = None, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).export_audit_summary(root_run_id=root_run_id)


@router.get('/api/integrations/drilldown/persona-matrix')
def integration_drilldown_persona_matrix(persona_id: str | None = None, strategy: str | None = None, window: str = '30d', status: str | None = None, limit: int = 100, offset: int = 0, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_drilldown_runs(persona_id=persona_id, strategy=strategy, window=window, status=status, limit=limit, offset=offset)


@router.get('/api/integrations/drilldown/persona-trends')
def integration_drilldown_persona_trends(persona_id: str | None = None, window: str = '30d', status: str | None = None, limit: int = 100, offset: int = 0, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_drilldown_runs(persona_id=persona_id, window=window, status=status, limit=limit, offset=offset)


@router.get('/api/integrations/drilldown/recommendations')
def integration_drilldown_recommendations(persona_id: str | None = None, strategy: str | None = None, limit: int = 100, offset: int = 0, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_drilldown_runs(persona_id=persona_id, strategy=strategy, window='all', limit=limit, offset=offset)


@router.get('/api/integrations/drilldown/policy-blocks')
def integration_drilldown_policy_blocks(persona_id: str | None = None, limit: int = 200, offset: int = 0, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_drilldown_audit(event_type='policy_blocked_action', persona_id=persona_id, limit=limit, offset=offset)


@router.get('/api/integrations/memory/patterns')
def integration_memory_patterns(repo: str | None = None, persona: str | None = None, strategy: str | None = None, promoted_only: bool = False, archived: bool | None = None, session: Session = Depends(get_session)):
    return {'patterns': IntegrationOrchestrator(session).list_patterns(repo=repo, persona=persona, strategy=strategy, promoted_only=promoted_only, archived=archived)}


@router.get('/api/integrations/memory/patterns/candidates')
def integration_memory_pattern_candidates(repo: str | None = None, persona: str | None = None, strategy: str | None = None, window: str = '30d', session: Session = Depends(get_session)):
    return {'candidates': IntegrationOrchestrator(session).list_candidate_patterns(repo=repo, persona=persona, strategy=strategy, window=window)}


@router.post('/api/integrations/memory/patterns/{pattern_id}/promote')
def integration_memory_pattern_promote(pattern_id: int, payload: PatternActionRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).promote_pattern(pattern_id, payload.note)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/memory/patterns/{pattern_id}/reject')
def integration_memory_pattern_reject(pattern_id: int, payload: PatternActionRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).reject_pattern(pattern_id, payload.note)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post('/api/integrations/memory/patterns/{pattern_id}/archive')
def integration_memory_pattern_archive(pattern_id: int, payload: PatternActionRequest, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).archive_pattern(pattern_id, payload.note)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/memory/summaries')
def integration_memory_summaries(repo: str | None = None, persona: str | None = None, strategy: str | None = None, promoted_only: bool = False, archived: bool | None = None, session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_pattern_summaries(repo=repo, persona=persona, strategy=strategy, promoted_only=promoted_only, archived=archived)


@router.get('/api/integrations/memory/summaries/cross-repo')
def integration_memory_summaries_cross_repo(session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).get_cross_repo_memory_summary()


@router.get('/api/integrations/memory/suggestions/new-mission')
def integration_memory_suggest_new(repo: str = '', persona_id: str = '', strategy: str = '', session: Session = Depends(get_session)):
    return IntegrationOrchestrator(session).suggest_for_new_mission(repo=repo, persona_id=persona_id, strategy=strategy)


@router.get('/api/integrations/memory/suggestions/replay')
def integration_memory_suggest_replay(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).suggest_for_replay(run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/memory/suggestions/branch-set')
def integration_memory_suggest_branch_set(run_id: int, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).suggest_for_branch_set(run_id)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get('/api/integrations/cohorts')
def integration_cohorts(
    group_by: str = 'repo',
    status: str | None = None,
    writeback_status: str | None = None,
    confidence_level: str | None = None,
    mission_score_min: int | None = None,
    mission_score_max: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    session: Session = Depends(get_session),
):
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return IntegrationOrchestrator(session).cohorts(group_by=group_by, status=status, writeback_status=writeback_status, confidence_level=confidence_level, mission_score_min=mission_score_min, mission_score_max=mission_score_max, start_date=start_dt, end_date=end_dt)


@router.get('/api/integrations/cohorts/summary')
def integration_cohorts_summary(
    group_by: str = 'repo',
    status: str | None = None,
    writeback_status: str | None = None,
    confidence_level: str | None = None,
    mission_score_min: int | None = None,
    mission_score_max: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    session: Session = Depends(get_session),
):
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return IntegrationOrchestrator(session).cohorts_summary(group_by=group_by, status=status, writeback_status=writeback_status, confidence_level=confidence_level, mission_score_min=mission_score_min, mission_score_max=mission_score_max, start_date=start_dt, end_date=end_dt)


@router.get('/api/integrations/export')
def integration_export(
    start_date: str | None = None,
    end_date: str | None = None,
    repo: str | None = None,
    persona_id: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None
    return IntegrationOrchestrator(session).export_data(start_date=start_dt, end_date=end_dt, repo=repo, persona_id=persona_id, status=status)


@router.post('/api/integrations/import')
def integration_import(payload: dict, session: Session = Depends(get_session)):
    try:
        return IntegrationOrchestrator(session).import_data(payload)
    except IntegrationClientError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
