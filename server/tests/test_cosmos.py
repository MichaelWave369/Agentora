from .conftest import make_client


def test_create_branch_and_reflect_cosmos():
    c = make_client()
    created = c.post('/api/cosmos/worlds', json={'name': 'Family Universe', 'seed_prompt': 'A dream of a warm city', 'warmth': 72}).json()
    world_id = created['id']
    assert created['name'] == 'Family Universe'

    branched = c.post('/api/cosmos/branch', json={'world_id': world_id, 'parent_timeline_id': 0, 'title': 'Chico 2025', 'branch_prompt': 'What if I moved to Chico in 2025?'}).json()
    assert branched['title'] == 'Chico 2025'

    timelines = c.get(f'/api/cosmos/world/{world_id}/timelines').json()
    assert len(timelines['items']) >= 2

    reflection = c.post(f'/api/cosmos/reflection/{world_id}?warmth=80').json()
    assert reflection['tone'] == 'hopeful'


def test_archive_and_eternal_seed():
    c = make_client()
    created = c.post('/api/cosmos/worlds', json={'name': 'Archive World', 'seed_prompt': 'Family story', 'warmth': 40}).json()
    world_id = created['id']

    archive = c.get('/api/cosmos/archive?query=archive').json()
    assert 'songs' in archive and 'souls' in archive

    zipped = c.get(f'/api/cosmos/world/{world_id}/eternal-seed.zip')
    assert zipped.status_code == 200

    collapsed = c.post(f'/api/cosmos/world/{world_id}/collapse').json()
    assert 'collapsed' in collapsed
