from .conftest import make_client


def test_marketplace_list_install_and_update_flag():
    c = make_client()
    listed = c.get('/api/marketplace/templates').json()['templates']
    assert len(listed) >= 8
    first = listed[0]
    r = c.post('/api/marketplace/install', json={'name': first['name'], 'version': first['version']})
    assert r.status_code == 200
    listed2 = c.get('/api/marketplace/templates').json()['templates']
    rec = [x for x in listed2 if x['name'] == first['name']][0]
    assert rec['installed_version'] == first['version']
