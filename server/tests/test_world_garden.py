from .conftest import make_client


def _seed_world(c, name='WG Seed'):
    return c.post('/api/cosmos/worlds', json={'name': name, 'seed_prompt': 'world garden seed'}).json()['id']


def test_world_garden_flow():
    c = make_client()
    _seed_world(c, 'Garden Alpha')
    _seed_world(c, 'Garden Beta')

    m = c.get('/api/world-garden/map').json()
    assert 'items' in m and len(m['items']) >= 2
    a = m['items'][0]['id']
    b = m['items'][1]['id']

    bloom = c.post('/api/world-garden/bloom', json={'node_id': a, 'reason': 'new song'}).json()
    assert bloom['glow'] >= 35

    preview = c.post('/api/world-garden/cross-pollinate', json={'from_node': a, 'to_node': b, 'preview_only': True}).json()
    assert preview['applied'] is False

    apply_merge = c.post('/api/world-garden/cross-pollinate', json={'from_node': a, 'to_node': b, 'preview_only': False}).json()
    assert apply_merge['applied'] is True

    links = c.get('/api/world-garden/constellations').json()
    assert 'links' in links

    festival = c.post('/api/world-garden/festival/harvest').json()
    assert festival['festival'] == 'Eternal Harvest Festival'
