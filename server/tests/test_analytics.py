from .conftest import make_client


def test_analytics_overview_schema():
    c = make_client()
    r = c.get('/api/analytics/overview')
    assert r.status_code == 200
    j = r.json()
    assert 'runs' in j and 'total_tokens_out' in j
