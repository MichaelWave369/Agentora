from .conftest import make_client


def test_snapshot_png():
    c = make_client()
    t = c.post('/api/teams', json={'name':'Snap','mode':'sequential','description':'','yaml_text':''}).json()
    run = c.post('/api/runs', json={'team_id': t['id'], 'prompt':'snap', 'max_turns':1, 'max_seconds':10, 'token_budget':100}).json()
    r = c.get(f"/api/snapshot.png?run_id={run['run_id']}")
    assert r.status_code == 200
    assert r.content[:8] == b'\x89PNG\r\n\x1a\n'
