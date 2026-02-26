from .conftest import make_client


def test_templates_load():
    c = make_client()
    r = c.get('/api/teams/templates')
    assert r.status_code == 200
    assert len(r.json()['templates']) >= 5
