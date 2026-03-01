from .conftest import make_client


def test_workflow_create_and_run():
    c = make_client()
    create = c.post('/api/workflows', json={
        'name': 'wf-test',
        'description': 'desc',
        'params_schema': {},
        'steps': [
            {'position': 0, 'step_type': 'desktop', 'tool_name': 'desktop_list_dir', 'params': {'path': '.'}, 'requires_approval': False},
        ],
    })
    assert create.status_code == 200
    wf_id = create.json()['item']['id']

    run = c.post(f'/api/workflows/{wf_id}/run', json={'run_id': 7010, 'inputs': {}})
    assert run.status_code == 200

    runs = c.get(f'/api/workflows/{wf_id}/runs')
    assert runs.status_code == 200
    assert runs.json()['items']
