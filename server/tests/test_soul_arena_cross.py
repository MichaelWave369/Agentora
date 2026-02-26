from .conftest import make_client


def test_cross_mode_buttons_flow():
    c = make_client()
    team = c.post('/api/teams', json={'name':'Cross','mode':'sequential','description':'','yaml_text':''}).json()
    m = c.post('/api/arena/match', json={'topic':'verify truth'}).json()
    anthem = c.post('/api/studio/turn-verdict-into-anthem', json={'match_id': m['match_id'], 'team_id': team['id']})
    assert anthem.status_code == 200
    lyr = c.post('/api/arena/debate-lyrics', json={'lyrics':'local first forever'})
    assert lyr.status_code == 200
    narr = c.post('/api/studio/narrate-highlights', json={'summary':'great rounds'})
    assert narr.json()['ok'] is True
