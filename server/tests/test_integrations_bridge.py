from app.core.config import Settings, settings
from app.integrations.mappers import map_outcome_to_writeback_payload, map_packet_to_launch_request, normalize_job_status
from app.integrations.phios_client import PhiOSClient
from app.integrations.schemas import AgentCeptionJobStatus, ContextPackRequest


def make_client():
    from fastapi.testclient import TestClient

    from app.db import create_db_and_tables
    from app.main import create_app

    create_db_and_tables()
    return TestClient(create_app())


def test_integration_env_defaults_parse():
    cfg = Settings()
    assert cfg.agentora_phios_enabled is False
    assert cfg.agentora_agentception_enabled is False
    assert cfg.agentora_integrations_mock is False


def test_mission_context_packet_normalization_mock(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_phios_enabled', False)
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


def test_packet_to_launch_mapper(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    packet = PhiOSClient().get_context_pack(
        ContextPackRequest(persona_id='p-2', task='software_mission', repo='owner/repo', objective='Map launch payload')
    )
    launch = map_packet_to_launch_request(packet, ['A'], ['B'], dry_run=True)
    assert launch.mission_title
    assert launch.persona_name
    assert launch.dispatch_brief
    assert launch.dry_run is True


def test_result_to_writeback_mapper():
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
    writeback = map_outcome_to_writeback_payload(
        session_id='sess-1',
        task_id='job-1',
        repo='owner/repo',
        objective='Ship',
        outcome=outcome,
    )
    assert writeback.outcome_status == 'completed'
    assert writeback.pr_url.endswith('/1')


def test_orchestrator_and_routes_flow(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_phios_enabled', False)
    monkeypatch.setattr(settings, 'agentora_agentception_enabled', False)

    client = make_client()

    prepared = client.post(
        '/api/integrations/runs/prepare',
        json={
            'persona_id': 'persona-1',
            'repo': 'owner/repo',
            'mission_title': 'Mission',
            'objective': 'Objective',
            'operator_intent': 'Intent',
            'constraints': ['thin integration'],
        },
    )
    assert prepared.status_code == 200

    launch = client.post(
        '/api/integrations/runs/launch',
        json={
            'persona_id': 'persona-1',
            'repo': 'owner/repo',
            'mission_title': 'Mission',
            'objective': 'Objective',
            'operator_intent': 'Intent',
            'acceptance_criteria': ['status refresh'],
            'constraints': ['thin integration'],
            'dry_run': True,
            'prepared_packet': prepared.json(),
        },
    )
    assert launch.status_code == 200
    record = launch.json()
    assert record['phios_packet_json']
    run_id = record['id']

    refresh = client.post(f'/api/integrations/runs/{run_id}/refresh', json={})
    assert refresh.status_code == 200
    refreshed = refresh.json()
    assert refreshed['agentception_result_json']

    writeback = client.post(
        f'/api/integrations/runs/{run_id}/writeback',
        json={'operator_notes': 'manual', 'tags': ['test']},
    )
    assert writeback.status_code == 200

    detail = client.get(f'/api/integrations/runs/{run_id}')
    assert detail.status_code == 200
    assert detail.json()['writeback_status'] in {'written', 'failed'}

    timeline = client.get(f'/api/integrations/runs/{run_id}/timeline')
    assert timeline.status_code == 200
    assert timeline.json()['events']
