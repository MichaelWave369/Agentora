from pathlib import Path

from .conftest import make_client


def test_release_readiness_happy_path_smoke(tmp_path):
    client = make_client()

    health = client.get('/api/system/health')
    assert health.status_code == 200
    assert health.json()['ok'] is True

    version = client.get('/api/system/version')
    assert version.status_code == 200
    assert version.json()['version'] == '1.0.0'

    workflow = client.post('/api/workflows', json={
        'name': 'release-smoke-workflow',
        'description': 'workflow smoke for v1.0.0',
        'params_schema': {},
        'steps': [
            {'position': 0, 'step_type': 'desktop', 'tool_name': 'desktop_list_dir', 'params': {'path': '.'}, 'requires_approval': False},
            {'position': 1, 'step_type': 'desktop', 'tool_name': 'desktop_write_text', 'params': {'path': 'server/data/release-smoke.txt', 'content': 'ok'}, 'requires_approval': True},
        ],
    })
    assert workflow.status_code == 200
    wf_id = workflow.json()['item']['id']

    first_run = client.post(f'/api/workflows/{wf_id}/run', json={'run_id': 7100, 'inputs': {}})
    assert first_run.status_code == 200

    pending = client.get('/api/actions/pending')
    assert pending.status_code == 200
    items = pending.json().get('items', [])
    if items:
        decision = client.post(f"/api/actions/{items[0]['id']}/approve", json={'reason': 'release smoke approve'})
        assert decision.status_code == 200

    history = client.get('/api/actions/history')
    assert history.status_code == 200

    memory = client.get('/api/memory/runs/7100/retrieval')
    assert memory.status_code == 200

    # Replay path: run same workflow again and verify history length
    second_run = client.post(f'/api/workflows/{wf_id}/run', json={'run_id': 7101, 'inputs': {'replay': True}})
    assert second_run.status_code == 200

    workflow_history = client.get(f'/api/workflows/{wf_id}/runs')
    assert workflow_history.status_code == 200
    assert len(workflow_history.json().get('items', [])) >= 2

    # Worker assist fallback path should remain readable and non-crashing
    worker_job = client.post('/api/workers/dispatch', json={'job_type': 'interactive_chat', 'payload': {'run_id': 7102}, 'priority': 8})
    assert worker_job.status_code == 200
    job_id = worker_job.json()['job']['id']
    job_detail = client.get(f'/api/workers/jobs/{job_id}')
    assert job_detail.status_code == 200
    assert job_detail.json()['job']['status'] in {'fallback_local', 'running', 'done'}

    assert Path('server/data').exists()
