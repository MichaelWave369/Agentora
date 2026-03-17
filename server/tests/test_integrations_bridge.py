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


def test_phase_d_env_defaults_parse():
    cfg = Settings()
    assert cfg.agentora_missions_watcher_enabled is False
    assert cfg.agentora_missions_watcher_interval_seconds == 20
    assert cfg.agentora_missions_auto_writeback is False
    assert cfg.agentora_missions_mcp_enabled is False


def test_mission_context_packet_normalization_mock(monkeypatch):
    _enable_mock(monkeypatch)
    packet = PhiOSClient().get_context_pack(
        ContextPackRequest(
            persona_id='p-1',
            task='software_mission',
            repo='owner/repo',
            objective='Improve bridge',
            mission_title='Bridge upgrade',
            operator_intent='Safe rollout',
        )
    )
    assert packet.session_id.startswith('phios-mock-session')
    assert packet.mission_title == 'Bridge upgrade'
    assert packet.dispatch_brief.objective


def test_packet_to_launch_and_writeback_mappers(monkeypatch):
    _enable_mock(monkeypatch)
    packet = PhiOSClient().get_context_pack(
        ContextPackRequest(persona_id='p-2', task='software_mission', repo='owner/repo', objective='Map launch payload')
    )
    launch = map_packet_to_launch_request(packet, ['A'], ['B'], dry_run=True)
    assert launch.mission_title
    assert launch.persona_name
    assert launch.dispatch_brief
    assert launch.dry_run is True

    status = AgentCeptionJobStatus(
        job_id='job-1',
        status='completed',
        phase='pr_opened',
        branch='feat/x',
        pr_url='https://example/pr/1',
        issue_urls=['https://example/issues/1'],
        artifact_urls=['https://example/artifacts/1'],
        summary='Done',
        updated_at='2026-01-01T00:00:00Z',
    )
    outcome = normalize_job_status(status)
    assert is_meaningful_outcome(outcome)
    assert outcome_fingerprint(outcome)
    writeback = map_outcome_to_writeback_payload(
        session_id='sess-1',
        task_id='job-1',
        repo='owner/repo',
        objective='Ship',
        outcome=outcome,
    )
    assert writeback.outcome_status == 'completed'
    assert writeback.pr_url.endswith('/1')


def _launch_mock_run(client):
    prepared = client.post(
        '/api/integrations/runs/prepare',
        json={
            'persona_id': 'persona-1',
            'repo': 'owner/repo',
            'mission_title': 'Mission Alpha',
            'objective': 'Objective Alpha',
            'operator_intent': 'Intent Alpha',
            'constraints': ['thin integration'],
        },
    )
    assert prepared.status_code == 200
    launch = client.post(
        '/api/integrations/runs/launch',
        json={
            'persona_id': 'persona-1',
            'repo': 'owner/repo',
            'mission_title': 'Mission Alpha',
            'objective': 'Objective Alpha',
            'operator_intent': 'Intent Alpha',
            'acceptance_criteria': ['status refresh'],
            'constraints': ['thin integration'],
            'dry_run': True,
            'prepared_packet': prepared.json(),
        },
    )
    assert launch.status_code == 200
    return launch.json()['id']


def test_orchestrator_routes_filters_compare_and_watch(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    run_id = _launch_mock_run(client)

    refresh = client.post(f'/api/integrations/runs/{run_id}/refresh', json={})
    assert refresh.status_code == 200

    unwatch = client.post(f'/api/integrations/runs/{run_id}/unwatch', json={})
    assert unwatch.status_code == 200
    assert unwatch.json()['watch_enabled'] is False
    watch = client.post(f'/api/integrations/runs/{run_id}/watch', json={})
    assert watch.status_code == 200
    assert watch.json()['watch_enabled'] is True

    listing = client.get('/api/integrations/runs?status=running&repo=owner/repo&persona_id=persona-1&search=Objective')
    assert listing.status_code == 200
    assert isinstance(listing.json(), list)

    run_id_2 = _launch_mock_run(client)
    compare = client.get(f'/api/integrations/runs/compare?left_run_id={run_id}&right_run_id={run_id_2}')
    assert compare.status_code == 200
    body = compare.json()
    assert 'left' in body and 'right' in body


def test_debounce_auto_writeback_and_manual_writeback(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_auto_writeback', True)
    monkeypatch.setattr(settings, 'agentora_missions_writeback_debounce_seconds', 9999)

    calls = {'n': 0}

    def _mock_writeback(_self, _payload):
        calls['n'] += 1
        return {'ok': True, 'id': f"wb-{calls['n']}"}

    monkeypatch.setattr(PhiOSClient, 'write_mission_result', _mock_writeback)

    client = make_client()
    run_id = _launch_mock_run(client)

    from app.db import Session, engine
    from app.services.integration_orchestrator import IntegrationOrchestrator

    with Session(engine) as session:
        orchestrator = IntegrationOrchestrator(session)
        row = session.get(IntegrationRun, run_id)
        row.auto_writeback_enabled = True
        row.writeback_policy = 'auto'
        session.add(row)
        session.commit()
        orchestrator.refresh_run(run_id, source='watcher')
        orchestrator.refresh_run(run_id, source='watcher')

    assert calls['n'] == 1

    wb1 = client.post(f'/api/integrations/runs/{run_id}/writeback', json={'operator_notes': 'manual', 'tags': ['x']})
    assert wb1.status_code == 200
    assert calls['n'] >= 2


def test_watcher_active_selection(monkeypatch):
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
        assert len(rows) >= 1
        assert all(r.status in {'running', 'launched', 'queued', 'preparing_launch'} for r in rows)
        assert all(r.watch_enabled for r in rows)


def test_mcp_exposure_wiring(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_mcp_enabled', True)
    client = make_client()
    caps = client.get('/api/integrations/mcp/capabilities')
    assert caps.status_code == 200
    assert caps.json()['ok'] is True
    call = client.post('/api/integrations/mcp/call', json={'tool': 'list_missions', 'args': {'limit': 5}})
    assert call.status_code == 200
    assert call.json()['ok'] is True

def test_watcher_run_once_updates_outcome(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_watcher_max_active_runs', 10)
    client = make_client()
    run_id = _launch_mock_run(client)

    from app.services.mission_watcher import MissionWatcher

    watcher = MissionWatcher()
    processed = watcher.run_once()
    assert processed >= 1

    detail = client.get(f'/api/integrations/runs/{run_id}')
    assert detail.status_code == 200
    assert detail.json().get('agentception_result_json')
