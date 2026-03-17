from app.core.config import Settings, settings
from app.integrations.mappers import (
    is_meaningful_outcome,
    map_outcome_to_writeback_payload,
    map_packet_to_launch_request,
    normalize_job_status,
    outcome_fingerprint,
)
from app.integrations.phios_client import PhiOSClient
from app.integrations.schemas import AgentCeptionJobStatus, ContextPackRequest
from app.models import IntegrationRun


def make_client():
    from fastapi.testclient import TestClient

    from app.db import create_db_and_tables
    from app.main import create_app

    create_db_and_tables()
    return TestClient(create_app())


def _enable_mock(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_phios_enabled', False)
    monkeypatch.setattr(settings, 'agentora_agentception_enabled', False)


def _launch_mock_run(client, title='Mission Alpha', objective='Objective Alpha'):
    prepared = client.post('/api/integrations/runs/prepare', json={'persona_id': 'persona-1', 'repo': 'owner/repo', 'mission_title': title, 'objective': objective, 'operator_intent': 'Intent', 'constraints': ['thin integration']})
    assert prepared.status_code == 200
    launch = client.post('/api/integrations/runs/launch', json={'persona_id': 'persona-1', 'repo': 'owner/repo', 'mission_title': title, 'objective': objective, 'operator_intent': 'Intent', 'acceptance_criteria': ['status refresh'], 'constraints': ['thin integration'], 'dry_run': True, 'prepared_packet': prepared.json()})
    assert launch.status_code == 200
    return launch.json()['id']


def test_phase_e_env_defaults_parse():
    cfg = Settings()
    assert cfg.agentora_missions_watcher_enabled is False
    assert cfg.agentora_missions_auto_writeback is False
    assert cfg.agentora_missions_mcp_enabled is False
    assert cfg.agentora_missions_mcp_read_only is False


def test_mapper_and_packet_normalization(monkeypatch):
    _enable_mock(monkeypatch)
    packet = PhiOSClient().get_context_pack(ContextPackRequest(persona_id='p-1', task='software_mission', repo='owner/repo', objective='Improve bridge', mission_title='Bridge upgrade', operator_intent='Safe rollout'))
    launch = map_packet_to_launch_request(packet, ['A'], ['B'], dry_run=True)
    assert packet.session_id.startswith('phios-mock-session')
    assert launch.persona_name

    status = AgentCeptionJobStatus(job_id='job-1', status='completed', phase='pr_opened', branch='feat/x', pr_url='https://example/pr/1', issue_urls=['https://example/issues/1'], artifact_urls=['https://example/artifacts/1'], summary='Done', updated_at='2026-01-01T00:00:00Z')
    outcome = normalize_job_status(status)
    assert is_meaningful_outcome(outcome)
    assert outcome_fingerprint(outcome)
    wb = map_outcome_to_writeback_payload(session_id='s', task_id='t', repo='r', objective='o', outcome=outcome)
    assert wb.pr_url.endswith('/1')


def test_metrics_events_insights_and_timeline(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    run_id = _launch_mock_run(client)
    assert client.post(f'/api/integrations/runs/{run_id}/refresh', json={}).status_code == 200
    assert client.post(f'/api/integrations/runs/{run_id}/writeback', json={'operator_notes': 'manual', 'tags': ['t']}).status_code == 200

    metrics = client.get('/api/integrations/metrics')
    assert metrics.status_code == 200
    assert 'refresh_attempts' in metrics.json()

    events = client.get('/api/integrations/watcher/events?limit=10')
    assert events.status_code == 200
    assert isinstance(events.json().get('events'), list)

    insights = client.get('/api/integrations/insights')
    assert insights.status_code == 200
    assert 'missions_by_status' in insights.json()

    timeline = client.get(f'/api/integrations/runs/{run_id}/timeline')
    assert timeline.status_code == 200
    assert len(timeline.json().get('events', [])) >= 2


def test_structured_compare_diff(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    left = _launch_mock_run(client, title='Mission Left', objective='Objective Left')
    right = _launch_mock_run(client, title='Mission Right', objective='Objective Right')
    client.post(f'/api/integrations/runs/{left}/refresh', json={})
    client.post(f'/api/integrations/runs/{right}/refresh', json={})

    compare = client.get(f'/api/integrations/runs/compare?left_run_id={left}&right_run_id={right}')
    assert compare.status_code == 200
    payload = compare.json()
    assert 'field_differences' in payload
    assert 'interpretation' in payload
    assert 'timeline_length_comparison' in payload


def test_evaluation_fields_persist(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    run_id = _launch_mock_run(client)
    detail = client.get(f'/api/integrations/runs/{run_id}')
    assert detail.status_code == 200
    body = detail.json()
    assert 'mission_score' in body
    assert body['confidence_level'] in {'low', 'medium', 'high'}


def test_watcher_selects_active_runs(monkeypatch):
    _enable_mock(monkeypatch)
    from app.db import Session, create_db_and_tables, engine
    from app.services.integration_orchestrator import IntegrationOrchestrator

    create_db_and_tables()
    with Session(engine) as session:
        session.add(IntegrationRun(status='running', watch_enabled=True, persona_id='p', repo='r', objective='o', agentception_job_id='j1'))
        session.add(IntegrationRun(status='completed', watch_enabled=True, persona_id='p', repo='r', objective='o', agentception_job_id='j2'))
        session.add(IntegrationRun(status='running', watch_enabled=False, persona_id='p', repo='r', objective='o', agentception_job_id='j3'))
        session.commit()
        rows = IntegrationOrchestrator(session).list_active_runs_for_watcher(limit=10)
        assert rows
        assert all(r.status in {'running', 'launched', 'queued', 'preparing_launch'} for r in rows)
        assert all(r.watch_enabled for r in rows)


def test_mcp_policy_auth_readonly_allowed_tools(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_mcp_enabled', True)
    monkeypatch.setattr(settings, 'agentora_missions_mcp_api_key', 'secret')
    monkeypatch.setattr(settings, 'agentora_missions_mcp_read_only', True)
    monkeypatch.setattr(settings, 'agentora_missions_mcp_allowed_tools', 'list_missions,get_mission')

    client = make_client()
    denied = client.get('/api/integrations/mcp/capabilities')
    assert denied.status_code == 200
    assert denied.json()['ok'] is False

    caps = client.get('/api/integrations/mcp/capabilities', headers={'X-API-Key': 'secret'})
    assert caps.status_code == 200
    assert caps.json()['ok'] is True
    assert 'launch_mission' not in caps.json().get('tools', [])

    blocked = client.post('/api/integrations/mcp/call', headers={'X-API-Key': 'secret'}, json={'tool': 'launch_mission', 'args': {}})
    assert blocked.status_code == 200
    assert blocked.json()['ok'] is False

    allowed = client.post('/api/integrations/mcp/call', headers={'X-API-Key': 'secret'}, json={'tool': 'list_missions', 'args': {'limit': 5}})
    assert allowed.status_code == 200
    assert allowed.json()['ok'] is True
