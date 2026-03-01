from .conftest import make_client


def test_bootstrap_endpoint_persists_state():
    client = make_client()
    r = client.post('/api/system/bootstrap', json={'auto_fix': False})
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['status'] in {'ok', 'warn', 'error'}
    assert body['bootstrap_state_id'] > 0
