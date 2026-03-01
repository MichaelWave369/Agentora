from .conftest import make_client


def _workflow_payload(name: str):
    return {
        'name': name,
        'description': 'operator test workflow',
        'params_schema': {},
        'steps': [
            {'position': 0, 'step_type': 'desktop', 'tool_name': 'desktop_list_dir', 'params': {'path': '.'}, 'requires_approval': False},
            {'position': 1, 'step_type': 'browser', 'tool_name': 'browser_navigate', 'params': {'url': 'http://localhost:8088'}, 'requires_approval': True},
        ],
    }


def test_operator_run_pause_resume_skip():
    client = make_client()
    wf = client.post('/api/workflows', json=_workflow_payload('op-wf')).json()['item']

    created = client.post('/api/operator/runs', json={'workflow_id': wf['id'], 'run_id': 0, 'mode': 'stepwise', 'worker_mode': 'auto'})
    assert created.status_code == 200
    op = created.json()['item']

    pa = client.post(f"/api/operator/runs/{op['id']}/pause")
    assert pa.status_code == 200
    assert pa.json()['item']['status'] == 'paused'

    re = client.post(f"/api/operator/runs/{op['id']}/resume")
    assert re.status_code == 200
    assert re.json()['item']['status'] == 'running'

    adv = client.post(f"/api/operator/runs/{op['id']}/advance")
    assert adv.status_code == 200
    detail = client.get(f"/api/operator/runs/{op['id']}").json()
    assert detail['ok'] is True
    assert len(detail['steps']) >= 1
