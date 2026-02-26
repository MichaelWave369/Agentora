from .conftest import make_client


def test_lan_join_approve_flow():
    c = make_client()
    created = c.post('/api/lan/create', json={'run_id': 1}).json()
    joined = c.post('/api/lan/join', json={'join_code': created['join_code'], 'name': 'u'}).json()
    approved = c.post('/api/lan/approve', json={'join_code': created['join_code'], 'host_token': created['host_token'], 'token': joined['token']}).json()
    assert approved['ok'] is True
