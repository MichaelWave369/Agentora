import json

from app.core.config import Settings, settings
from app.integrations.mappers import map_packet_to_launch_request
from app.integrations.phios_client import PhiOSClient
from app.integrations.schemas import ContextPackRequest


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


def test_phase_f_env_defaults_parse():
    cfg = Settings()
    assert cfg.agentora_missions_events_ttl_days == 30
    assert cfg.agentora_missions_events_max_per_run == 200
    assert cfg.agentora_missions_compaction_enabled is False
    assert cfg.agentora_missions_alerts_enabled is False


def test_calibration_applies(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_score_pr_bonus', 40)
    packet = PhiOSClient().get_context_pack(ContextPackRequest(persona_id='p', task='software_mission', repo='owner/repo', objective='obj'))
    launch = map_packet_to_launch_request(packet, [], [], True)
    assert launch.repo == 'owner/repo'


def test_retention_compaction_and_metrics_routes(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_events_max_per_run', 1)
    client = make_client()
    run_id = _launch_mock_run(client)
    client.post(f'/api/integrations/runs/{run_id}/refresh', json={})
    client.post(f'/api/integrations/runs/{run_id}/refresh', json={})

    retention = client.get('/api/integrations/retention')
    assert retention.status_code == 200
    assert 'total_events' in retention.json()

    compact = client.post('/api/integrations/retention/compact', json={})
    assert compact.status_code == 200
    assert 'deleted_events' in compact.json()

    metrics = client.get('/api/integrations/metrics')
    assert metrics.status_code == 200
    assert 'refresh_attempts' in metrics.json()


def test_export_import_round_trip(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    run_id = _launch_mock_run(client)
    client.post(f'/api/integrations/runs/{run_id}/refresh', json={})

    exported = client.get('/api/integrations/export')
    assert exported.status_code == 200
    payload = exported.json()
    assert payload['schema_version'] == 'mission-export-v1'
    assert payload['runs']

    imported = client.post('/api/integrations/import', json=payload)
    assert imported.status_code == 200
    assert imported.json()['ok'] is True

    bad = client.post('/api/integrations/import', json={'schema_version': 'wrong'})
    assert bad.status_code == 400


def test_alert_hook_failure_tolerant(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_alerts_enabled', True)
    monkeypatch.setattr(settings, 'agentora_missions_alerts_webhook_url', 'http://127.0.0.1:9/unreachable')

    client = make_client()
    run_id = _launch_mock_run(client)
    client.post(f'/api/integrations/runs/{run_id}/refresh', json={})
    client.post(f'/api/integrations/runs/{run_id}/writeback', json={'operator_notes': 'manual', 'tags': ['x']})

    alerts = client.get('/api/integrations/alerts/events')
    assert alerts.status_code == 200
    assert isinstance(alerts.json().get('events'), list)


def test_cohorts_and_compare_severity_and_snapshot(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    left = _launch_mock_run(client, title='Left', objective='Obj left')
    right = _launch_mock_run(client, title='Right', objective='Obj right')
    client.post(f'/api/integrations/runs/{left}/refresh', json={})
    client.post(f'/api/integrations/runs/{right}/refresh', json={})

    cohorts = client.get('/api/integrations/cohorts?group_by=repo')
    assert cohorts.status_code == 200
    assert cohorts.json()['groups']

    summary = client.get('/api/integrations/cohorts/summary?group_by=repo')
    assert summary.status_code == 200
    assert 'average_mission_score' in summary.json()

    compare = client.get(f'/api/integrations/runs/compare?left_run_id={left}&right_run_id={right}')
    assert compare.status_code == 200
    cmp = compare.json()
    assert 'overall_severity' in cmp
    assert 'field_severity' in cmp

    snap = client.get(f'/api/integrations/runs/{left}/snapshot')
    assert snap.status_code == 200
    assert 'prepared_packet' in snap.json()


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
