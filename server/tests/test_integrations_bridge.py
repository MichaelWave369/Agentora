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


def test_persona_catalog_fallback_and_detail(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    personas = client.get('/api/integrations/personas')
    assert personas.status_code == 200
    items = personas.json()['personas']
    assert items
    pid = items[0]['id']
    detail = client.get(f'/api/integrations/personas/{pid}')
    assert detail.status_code == 200
    assert detail.json()['id'] == pid


def test_persona_overlay_and_branch_set(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='PersonaRoot', objective='Improve branch orchestration')
    overlays = client.get('/api/integrations/persona-overlays')
    assert overlays.status_code == 200
    assert 'skeptic_reviewer' in overlays.json()['overlays']

    create = client.post(
        f'/api/integrations/runs/{source}/persona-branch-set',
        json={
            'specs': [
                {'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer', 'preset': 'conservative_fix', 'branch_label': 'skeptic-safe'},
                {'persona_id': 'architect', 'overlay': 'architect_refactorer', 'preset': 'aggressive_refactor', 'branch_label': 'arch-refactor'},
            ],
            'dry_run': True,
        },
    )
    assert create.status_code == 200
    body = create.json()
    assert len(body['created_drafts']) == 2
    assert body['created_drafts'][0]['assigned_persona_id']
    assert body['created_drafts'][0]['persona_strategy_overlay']


def test_persona_portfolio_override_and_summary(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='PersonaPortfolio', objective='Persona compare objective')
    created = client.post(
        f'/api/integrations/runs/{source}/persona-branch-set',
        json={'specs': [{'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer'}, {'persona_id': 'architect', 'overlay': 'architect_refactorer'}]},
    )
    assert created.status_code == 200
    run_id = created.json()['created_drafts'][0]['id']

    override = client.post(f'/api/integrations/runs/{run_id}/override', json={'decision': 'reject_recommendation', 'shortlisted': False, 'eliminated': True, 'note': 'operator rejected'})
    assert override.status_code == 200
    assert override.json()['operator_override_status'] == 'reject_recommendation'
    assert override.json()['recommendation_state'] == 'rejected'

    persona_portfolio = client.get(f'/api/integrations/lineage/{source}/persona-portfolio')
    assert persona_portfolio.status_code == 200
    assert persona_portfolio.json()['branches']

    persona_summary = client.get(f'/api/integrations/lineage/{source}/persona-summary')
    assert persona_summary.status_code == 200
    assert 'persona_metrics' in persona_summary.json()


def test_export_import_preserves_persona_metadata(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='PersonaExport', objective='Export persona metadata')
    created = client.post(f'/api/integrations/runs/{source}/persona-branch-set', json={'specs': [{'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer'}]})
    assert created.status_code == 200
    run_id = created.json()['created_drafts'][0]['id']
    client.post(f'/api/integrations/runs/{run_id}/override', json={'decision': 'manual_override', 'note': 'manual pick'})

    exported = client.get('/api/integrations/export')
    assert exported.status_code == 200
    rows = [r for r in exported.json()['runs'] if r.get('id') == run_id]
    assert rows and rows[0]['assigned_persona_id']
    assert rows[0]['operator_override_status'] == 'manual_override'

    imported = client.post('/api/integrations/import', json=exported.json())
    assert imported.status_code == 200


def test_operator_decision_events_persist_and_timeline(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='AuditRoot', objective='Audit decision flow')
    created = client.post(f'/api/integrations/runs/{source}/persona-branch-set', json={'specs': [{'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer'}]})
    assert created.status_code == 200
    branch_id = created.json()['created_drafts'][0]['id']

    ov = client.post(f'/api/integrations/runs/{branch_id}/override', json={'decision': 'manual_override', 'note': 'human override'})
    assert ov.status_code == 200

    events = client.get(f'/api/integrations/runs/{branch_id}/decision-events')
    assert events.status_code == 200
    assert events.json()['events']

    timeline = client.get(f'/api/integrations/runs/{branch_id}/timeline')
    assert timeline.status_code == 200
    assert any(e.get('event') in {'override_applied', 'operator-override'} for e in timeline.json()['events'])


def test_persona_delta_compare_route(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='CompareRoot', objective='Compare personas')
    created = client.post(
        f'/api/integrations/runs/{source}/persona-branch-set',
        json={'specs': [{'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer'}, {'persona_id': 'architect', 'overlay': 'architect_refactorer'}]},
    )
    assert created.status_code == 200
    a, b = created.json()['created_drafts'][0]['id'], created.json()['created_drafts'][1]['id']
    cmp = client.get(f'/api/integrations/runs/{a}/persona-compare?other_run_id={b}')
    assert cmp.status_code == 200
    body = cmp.json()
    assert 'field_differences' in body
    assert 'compare_note' in body


def test_persona_trends_and_matrix(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='TrendRoot', objective='Trend mission')
    client.post(f'/api/integrations/runs/{source}/persona-branch-set', json={'specs': [{'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer'}, {'persona_id': 'architect', 'overlay': 'architect_refactorer'}]})

    t7 = client.get('/api/integrations/persona-trends?window=7d')
    assert t7.status_code == 200
    assert 'persona_trends' in t7.json()

    t30 = client.get('/api/integrations/persona-trends?window=30d')
    assert t30.status_code == 200

    tall = client.get('/api/integrations/persona-trends?window=all')
    assert tall.status_code == 200

    matrix = client.get('/api/integrations/persona-trends/matrix?window=30d')
    assert matrix.status_code == 200
    assert 'matrix' in matrix.json()


def test_policy_block_and_override_reason_requirement(monkeypatch):
    _enable_mock(monkeypatch)
    monkeypatch.setattr(settings, 'agentora_persona_policy_enabled', True)
    monkeypatch.setattr(settings, 'agentora_persona_policy_require_override_reason', True)
    client = make_client()
    source = _launch_mock_run(client, title='PolicyRoot', objective='Policy mission')
    created = client.post(f'/api/integrations/runs/{source}/persona-branch-set', json={'specs': [{'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer'}]})
    branch_id = created.json()['created_drafts'][0]['id']

    bad = client.post(f'/api/integrations/runs/{branch_id}/override', json={'decision': 'manual_override', 'note': ''})
    assert bad.status_code == 400

    events = client.get(f'/api/integrations/runs/{branch_id}/decision-events')
    assert events.status_code == 200
    assert any(e.get('event_type') == 'policy_blocked_action' for e in events.json()['events'])


def test_export_import_preserves_operator_decision_events(monkeypatch):
    _enable_mock(monkeypatch)
    client = make_client()
    source = _launch_mock_run(client, title='ExportAuditRoot', objective='Export audit')
    created = client.post(f'/api/integrations/runs/{source}/persona-branch-set', json={'specs': [{'persona_id': 'skeptic', 'overlay': 'skeptic_reviewer'}]})
    branch_id = created.json()['created_drafts'][0]['id']
    client.post(f'/api/integrations/runs/{branch_id}/override', json={'decision': 'accept_recommendation', 'note': 'looks good'})

    exported = client.get('/api/integrations/export')
    assert exported.status_code == 200
    payload = exported.json()
    assert 'operator_decision_events' in payload

    imported = client.post('/api/integrations/import', json=payload)
    assert imported.status_code == 200
    assert 'imported_operator_decision_events' in imported.json()
