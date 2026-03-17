import json

from app.core.config import Settings, settings
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


def test_phase_g_env_defaults_parse():
    cfg = Settings()
    assert cfg.agentora_missions_replay_enabled is True
    assert cfg.agentora_missions_replay_allow_repo_change is False
    assert cfg.agentora_missions_replay_max_lineage_depth == 20


def test_snapshot_hash_determinism(monkeypatch):
    _enable_mock(monkeypatch)
    from app.db import Session, create_db_and_tables, engine
    from app.services.integration_orchestrator import IntegrationOrchestrator

    create_db_and_tables()
    with Session(engine) as session:
        orch = IntegrationOrchestrator(session)
        h1 = orch.compute_snapshot_hash({'a': 1, 'b': [2, 3]})
        h2 = orch.compute_snapshot_hash({'b': [2, 3], 'a': 1})
        assert h1 == h2


def test_replay_draft_creation_and_launch(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='Original', objective='Original objective')

    fork = client.post(f'/api/integrations/runs/{source}/fork', json={'replay_kind': 'branch_with_new_objective', 'objective': 'New branch objective', 'provenance_note': 'test fork', 'fork_reason': 'improve objective', 'dry_run': True})
    assert fork.status_code == 200
    draft = fork.json()
    assert draft['status'] == 'draft'
    assert draft['parent_run_id'] == source
    assert draft['replay_source_snapshot_hash']

    launch = client.post(f"/api/integrations/runs/{draft['id']}/launch-from-draft", json={'dry_run': True})
    assert launch.status_code == 200
    launched = launch.json()
    assert launched['parent_run_id'] == source


def test_replay_policy_validation(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_missions_replay_allow_repo_change', False)
    monkeypatch.setattr(settings, 'agentora_missions_replay_require_provenance_note', True)
    client = make_client()
    source = _launch_mock_run(client)

    bad_note = client.post(f'/api/integrations/runs/{source}/fork', json={'replay_kind': 'exact_replay', 'provenance_note': ''})
    assert bad_note.status_code == 400

    bad_repo = client.post(f'/api/integrations/runs/{source}/fork', json={'replay_kind': 'exact_replay', 'provenance_note': 'ok', 'repo': 'other/repo'})
    assert bad_repo.status_code == 400


def test_lineage_and_provenance_routes(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client)
    fork = client.post(f'/api/integrations/runs/{source}/fork', json={'replay_kind': 'exact_replay', 'provenance_note': 'lineage test'}).json()

    prov = client.get(f"/api/integrations/runs/{fork['id']}/provenance")
    assert prov.status_code == 200
    assert prov.json()['parent_run_id'] == source

    lin = client.get(f"/api/integrations/runs/{fork['id']}/lineage")
    assert lin.status_code == 200
    assert lin.json()['root_run_id']

    root = lin.json()['root_run_id']
    root_view = client.get(f'/api/integrations/lineage/{root}')
    assert root_view.status_code == 200


def test_export_import_preserves_provenance(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client)
    fork = client.post(f'/api/integrations/runs/{source}/fork', json={'replay_kind': 'recovery_replay', 'provenance_note': 'export test'}).json()

    exported = client.get('/api/integrations/export')
    assert exported.status_code == 200
    payload = exported.json()
    assert payload['schema_version'] == 'mission-export-v1'

    imported = client.post('/api/integrations/import', json=payload)
    assert imported.status_code == 200
    assert imported.json()['ok'] is True

    # provenance fields still available on original fork run detail
    detail = client.get(f"/api/integrations/runs/{fork['id']}")
    assert detail.status_code == 200
    assert 'replay_kind' in detail.json()


def test_compare_severity_and_snapshot_route(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    left = _launch_mock_run(client, title='Left', objective='obj left')
    right = _launch_mock_run(client, title='Right', objective='obj right')

    cmp = client.get(f'/api/integrations/runs/compare?left_run_id={left}&right_run_id={right}')
    assert cmp.status_code == 200
    body = cmp.json()
    assert 'overall_severity' in body
    assert 'field_severity' in body

    snap = client.get(f'/api/integrations/runs/{left}/snapshot')
    assert snap.status_code == 200
    assert snap.json().get('snapshot_hash')


def test_strategy_preset_application(monkeypatch):
    _enable_mock(monkeypatch)
    from app.db import Session, create_db_and_tables, engine
    from app.models import IntegrationRun
    from app.services.integration_orchestrator import IntegrationOrchestrator

    create_db_and_tables()
    with Session(engine) as session:
        source = IntegrationRun(status='completed', persona_id='persona-1', repo='owner/repo', mission_title='Source', objective='Fix flaky test', constraints_json=json.dumps(['No schema changes']))
        session.add(source)
        session.commit()
        session.refresh(source)
        orch = IntegrationOrchestrator(session)
        payload = orch.apply_branch_strategy_preset(source, 'constraint_tightening')
        assert payload['replay_kind'] == 'branch_with_new_constraints'
        assert any('safeguards' in c for c in payload['constraints'])


def test_bulk_branch_set_create_and_launch(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='Root', objective='Improve reliability')
    res = client.post(
        f'/api/integrations/runs/{source}/branch-set',
        json={
            'specs': [
                {'preset': 'minimal_patch', 'branch_label': 'minimal', 'launch': False},
                {'preset': 'aggressive_refactor', 'branch_label': 'refactor', 'launch': True},
            ],
            'dry_run': True,
            'auto_launch_selected': False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body['branch_set_id']
    assert len(body['created_drafts']) == 2
    assert len(body['launched_runs']) == 1


def test_portfolio_and_decision_summary_routes(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='RootPortfolio', objective='Improve API stability')
    created = client.post(
        f'/api/integrations/runs/{source}/branch-set',
        json={
            'specs': [
                {'preset': 'conservative_fix', 'branch_label': 'safe-path'},
                {'preset': 'exploratory_branch', 'branch_label': 'explore-path'},
            ]
        },
    )
    assert created.status_code == 200
    drafts = created.json()['created_drafts']
    first_branch = drafts[0]['id']

    shortlist = client.post(f'/api/integrations/runs/{first_branch}/shortlist', json={'decision_note': 'best candidate'})
    assert shortlist.status_code == 200
    assert shortlist.json()['decision_status'] == 'shortlisted'

    root_id = source
    portfolio = client.get(f'/api/integrations/lineage/{root_id}/portfolio')
    assert portfolio.status_code == 200
    p = portfolio.json()
    assert p['branches']
    assert 'interpretation_note' in p

    summary = client.get(f'/api/integrations/lineage/{root_id}/decision-summary')
    assert summary.status_code == 200
    assert summary.json()['number_of_branches'] >= 1


def test_export_import_preserves_branch_metadata(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='RootExport', objective='Export lineage branch metadata')
    created = client.post(
        f'/api/integrations/runs/{source}/branch-set',
        json={'specs': [{'preset': 'minimal_patch', 'branch_label': 'branch-a'}]},
    )
    assert created.status_code == 200
    branch_id = created.json()['created_drafts'][0]['id']
    client.post(f'/api/integrations/runs/{branch_id}/eliminate', json={'decision_note': 'too risky'})

    exported = client.get('/api/integrations/export')
    assert exported.status_code == 200
    payload = exported.json()
    branch_rows = [r for r in payload['runs'] if r.get('id') == branch_id]
    assert branch_rows and branch_rows[0].get('branch_set_id')
    assert branch_rows[0].get('decision_status') == 'eliminated'

    imported = client.post('/api/integrations/import', json=payload)
    assert imported.status_code == 200
