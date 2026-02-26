from .conftest import make_client


def test_health_ok():
    c = make_client()
    r = c.get('/api/health')
    assert r.status_code == 200
    assert r.json()['ok'] is True
