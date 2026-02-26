from .conftest import make_client


def _make_world(client):
    created = client.post('/api/cosmos/worlds', json={'name': 'Open World', 'seed_prompt': 'seed'}).json()
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
