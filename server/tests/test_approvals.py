from .conftest import make_client


def test_pending_approve_deny_flow():
    c = make_client()
    req = c.post('/api/actions', json={'run_id': 7020, 'agent_id': 0, 'action_class': 'desktop', 'tool_name': 'desktop_write_text', 'params': {'path': './server/data/test-approval.txt', 'content': 'x'}, 'requested_worker': False})
    assert req.status_code == 200
    aid = req.json()['item']['id']

    pending = c.get('/api/actions/pending')
    assert pending.status_code == 200

    deny = c.post(f'/api/actions/{aid}/deny', json={'reason': 'no'})
    assert deny.status_code == 200

    req2 = c.post('/api/actions', json={'run_id': 7021, 'agent_id': 0, 'action_class': 'desktop', 'tool_name': 'desktop_write_text', 'params': {'path': './server/data/test-approval-2.txt', 'content': 'y'}, 'requested_worker': False})
    aid2 = req2.json()['item']['id']
    if req2.json()['item']['status'] == 'pending':
        approve = c.post(f'/api/actions/{aid2}/approve', json={'reason': 'yes'})
        assert approve.status_code == 200
