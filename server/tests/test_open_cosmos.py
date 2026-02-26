from .conftest import make_client


def _make_world(client, name='Open World'):
    created = client.post('/api/cosmos/worlds', json={'name': name, 'seed_prompt': 'seed'}).json()
    return created['id']


def test_share_import_and_network():
    c = make_client()
    world_id = _make_world(c)

    shared = c.post('/api/open-cosmos/share', json={'world_id': world_id, 'visibility': 'public_with_credits', 'wisdom_mode': 'anonymized'}).json()
    assert shared['package_name'].endswith('.agentora')

    shares = c.get('/api/open-cosmos/shares').json()['items']
    assert len(shares) >= 1

    imported = c.post('/api/open-cosmos/import', json={'package_name': shared['package_name'], 'keep_timelines': []}).json()
    assert imported['imported_world_id'] > 0

    network = c.get('/api/open-cosmos/network').json()
    assert 'items' in network


def test_wisdom_and_revoke():
    c = make_client()
    world_id = _make_world(c)
    shared = c.post('/api/open-cosmos/share', json={'world_id': world_id}).json()
    shares = c.get('/api/open-cosmos/shares').json()['items']
    share_id = shares[0]['id']

    wisdom = c.post('/api/open-cosmos/wisdom', json={'enabled': True}).json()
    assert wisdom['enabled'] is True

    revoked = c.post(f'/api/open-cosmos/revoke/{share_id}').json()
    assert revoked['ok'] is True

    dl = c.get(f"/api/open-cosmos/download/{shared['package_name']}")
    assert dl.status_code == 200


def test_living_archive_exchange_and_synthesis():
    c = make_client()
    w1 = _make_world(c, 'Archive A')
    w2 = _make_world(c, 'Archive B')
    c.post('/api/open-cosmos/share', json={'world_id': w1, 'visibility': 'anonymized'})

    timeline = c.get('/api/open-cosmos/archive/timeline').json()
    assert 'items' in timeline

    query = c.post('/api/open-cosmos/archive/query', json={'question': 'kind children'}).json()
    assert 'synthesis' in query

    visit = c.post('/api/open-cosmos/visit', json={'from_world_id': w1, 'to_world_id': w2}).json()
    assert 'gifts' in visit

    exchange = c.post('/api/open-cosmos/exchange', json={'world_a': w1, 'world_b': w2}).json()
    assert 'merged_content' in exchange

    synth = c.post('/api/open-cosmos/synthesis', json={'world_ids': [w1, w2], 'title': 'Meta'}).json()
    assert synth['meta_world_id'] > 0

    forecast = c.post('/api/open-cosmos/forecast', json={'world_ids': [w1, w2]}).json()
    assert forecast['year'] == 2050

    spotlight = c.get('/api/open-cosmos/spotlight').json()
    assert 'items' in spotlight
