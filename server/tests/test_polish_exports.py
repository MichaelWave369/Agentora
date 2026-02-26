from .conftest import make_client


def test_full_project_export_endpoints_and_voice_status():
    c = make_client()
    team = c.post('/api/teams', json={'name':'Expo','mode':'sequential','description':'','yaml_text':''}).json()
    song = c.post('/api/studio/sing', json={'team_id': team['id'], 'prompt':'p'}).json()
    s = c.get(f"/api/studio/song/{song['song_job_id']}/export-project.zip")
    assert s.status_code == 200
    assert s.headers['content-type'].startswith('application/zip')

    track = c.post('/api/band/create_track', json={'team_id':1,'genre':'x'}).json()
    b = c.get(f"/api/band/track/{track['track_job_id']}/export-project.zip")
    assert b.status_code == 200

    v = c.get('/api/voice/status').json()
    assert 'install_command' in v
