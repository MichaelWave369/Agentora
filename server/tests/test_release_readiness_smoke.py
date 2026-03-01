from pathlib import Path

from .conftest import make_client


def test_release_readiness_happy_path_smoke(tmp_path):
    client = make_client()

    health = client.get('/api/system/health')
    assert health.status_code == 200
    assert health.json()['ok'] is True

    version = client.get('/api/system/version')
    assert version.status_code == 200
    assert version.json()['version'] == '0.9.7'

    workflow = client.post('/api/workflows', json={
        'name': 'release-smoke-workflow',
        'description': 'workflow smoke for v0.9.7',
        'params_schema': {},
        'steps': [
            {'position': 0, 'step_type': 'desktop', 'tool_name': 'desktop_list_dir', 'params': {'path': '.'}, 'requires_approval': False},
            {'position': 1, 'step_type': 'desktop', 'tool_name': 'desktop_write_text', 'params': {'path': 'server/data/release-smoke.txt', 'content': 'ok'}, 'requires_approval': True},
        ],
    })
    assert workflow.status_code == 200
    wf_id = workflow.json()['item']['id']

    wf_run = client.post(f'/api/workflows/{wf_id}/run', json={'run_id': 7097, 'inputs': {}})
    assert wf_run.status_code == 200

    pending = client.get('/api/actions/pending')
    assert pending.status_code == 200
    items = pending.json().get('items', [])
    if items:
        decision = client.post(f"/api/actions/{items[0]['id']}/approve", json={'reason': 'release smoke approve'})
        assert decision.status_code == 200

    history = client.get('/api/actions/history')
    assert history.status_code == 200

    memory = client.get('/api/memory/runs/7097/retrieval')
    assert memory.status_code == 200

    workflow_history = client.get(f'/api/workflows/{wf_id}/runs')
    assert workflow_history.status_code == 200

    assert Path('server/data').exists()
