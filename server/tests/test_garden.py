from .conftest import make_client


def _seed_world(c):
    r = c.post('/api/cosmos/worlds', json={'name': 'Garden Seed', 'seed_prompt': 'a living orchard'})
    return r.json()['id']


def test_garden_map_tend_harvest_cycle():
    c = make_client()
    _seed_world(c)

    m = c.get('/api/garden/map').json()
    assert 'items' in m and len(m['items']) >= 1
    bed_id = m['items'][0]['id']

    t = c.post('/api/garden/tend', json={'bed_id': bed_id, 'gardener_role': 'Pollinator', 'note': 'new story bloom'}).json()
    assert 'growth' in t

    s = c.post('/api/garden/season/advance').json()
    assert 'season' in s

    h = c.post(f'/api/garden/harvest/{bed_id}').json()
    assert 'harvest' in h

    comm = c.get('/api/garden/community').json()
    assert 'shared_beds' in comm
