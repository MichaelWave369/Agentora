from app.core.config import Settings, settings
from app.integrations.agentception_client import AgentCeptionClient
from app.integrations.phios_client import PhiOSClient
from app.integrations.schemas import AgentCeptionLaunchRequest, ContextPackRequest
from app.services.integration_orchestrator import IntegrationOrchestrator


def make_client():
    from fastapi.testclient import TestClient

    from app.db import create_db_and_tables
    from app.main import create_app

    create_db_and_tables()
    return TestClient(create_app())


def test_integration_env_defaults_parse():
    cfg = Settings()
    assert cfg.agentora_phios_enabled is False
    assert cfg.agentora_phios_url == 'http://127.0.0.1:8090'
    assert cfg.agentora_agentception_url == 'http://127.0.0.1:1337'
    assert cfg.agentora_integrations_mock is False


def test_phios_mock_adapter(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_phios_enabled', False)
    client = PhiOSClient()
    persona = client.get_persona('p-1')
    ctx = client.get_context_pack(ContextPackRequest(persona_id='p-1', task='task', repo='owner/repo', objective='obj', limit=2))
    assert persona.id == 'p-1'
    assert ctx.session_id.startswith('phios-mock-session')
    assert len(ctx.memory_snippets) >= 1


def test_agentception_mock_adapter(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_agentception_enabled', False)
    client = AgentCeptionClient()
    launch = client.launch_job(
        AgentCeptionLaunchRequest(
            title='Test',
            repo='owner/repo',
            objective='Ship',
            context_summary='Context',
            acceptance_criteria=[],
            constraints=[],
            persona_name='Mock',
            persona_role='Engineer',
            memory_snippets=[],
            dry_run=True,
        )
    )
    status = client.get_job_status(launch.job_id)
    assert launch.job_id == 'ac-mock-job-001'
    assert status.status in {'running', 'queued', 'completed'}


def test_orchestration_mapping(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_phios_enabled', False)
    monkeypatch.setattr(settings, 'agentora_agentception_enabled', False)
    from app.db import create_db_and_tables, engine
    from sqlmodel import Session

    create_db_and_tables()
    with Session(engine) as session:
        orchestrator = IntegrationOrchestrator(session)
        rec = orchestrator.run_software_task_with_context(
            persona_id='persona-7',
            repo='owner/repo',
            objective='Implement bridge',
            acceptance_criteria=['route returns json'],
            constraints=['no vendoring'],
            dry_run=True,
        )
        assert rec.persona_id == 'persona-7'
        assert rec.phios_session_id
        assert rec.agentception_job_id


def test_integration_routes_smoke(monkeypatch):
    monkeypatch.setattr(settings, 'agentora_integrations_mock', True)
    monkeypatch.setattr(settings, 'agentora_phios_enabled', False)
    monkeypatch.setattr(settings, 'agentora_agentception_enabled', False)
    client = make_client()

    health = client.get('/api/integrations/phios/health')
    assert health.status_code == 200

    launch = client.post(
        '/api/integrations/agentception/launch',
        json={
            'persona_id': 'persona-1',
            'repo': 'owner/repo',
            'objective': 'Route smoke',
            'acceptance_criteria': ['status endpoint works'],
            'constraints': ['thin integration only'],
            'dry_run': True,
        },
    )
    assert launch.status_code == 200
    run_id = launch.json()['id']

    refresh = client.post(f'/api/integrations/runs/{run_id}/refresh', json={})
    assert refresh.status_code == 200

    writeback = client.post(f'/api/integrations/runs/{run_id}/writeback', json={'summary': 'done', 'details': 'ok', 'tags': ['test']})
    assert writeback.status_code == 200
