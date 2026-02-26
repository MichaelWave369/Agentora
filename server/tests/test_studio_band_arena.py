from .conftest import make_client


def test_studio_sing_mock_outputs():
    c = make_client()
    team = c.post('/api/teams', json={'name':'Soul','mode':'sequential','description':'','yaml_text':''}).json()
    out = c.post('/api/studio/sing', json={'team_id': team['id'], 'prompt': 'sing truth'}).json()
    assert 'song_job_id' in out
    w = c.get(f"/api/studio/song/{out['song_job_id']}/waveform.json").json()
    assert 'peaks' in w and len(w['peaks']) > 0


def test_band_track_mock_outputs():
    c = make_client()
    out = c.post('/api/band/create_track', json={'team_id': 1, 'genre':'synthwave'}).json()
    st = c.get(f"/api/band/track/{out['track_job_id']}/status").json()
    assert st['status'] == 'completed'


def test_arena_match_and_tournament():
    c = make_client()
    m = c.post('/api/arena/match', json={'topic':'local-first matters'}).json()
    status = c.get(f"/api/arena/{m['match_id']}/status").json()
    assert status['kind'] == 'match'
    t = c.post('/api/arena/tournament', json={'topics':['a','b','c','d']}).json()
    st = c.get(f"/api/arena/{t['tournament_id']}/status").json()
    assert st['kind'] == 'tournament'
