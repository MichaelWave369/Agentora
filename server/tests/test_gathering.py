from .conftest import make_client


def test_gathering_discovery_and_room_join():
    c = make_client()
    d = c.get('/api/gathering/discover')
    assert d.status_code == 200
    created = c.post('/api/gathering/session/create', json={'host_name':'Host','mode':'studio'}).json()
    assert len(created['room_code']) == 4
    joined = c.post('/api/gathering/session/join', json={'room_code': created['room_code'], 'name': 'PhoneGuest'})
    assert joined.status_code == 200


def test_gathering_memory_consent_gate():
    c = make_client()
    s = c.post('/api/gathering/session/create', json={'host_name':'Host','mode':'arena'}).json()
    denied = c.post('/api/gathering/memory/import', json={'session_id': s['id'], 'consent': False, 'items':[{'text':'story'}]}).json()
    assert denied['ok'] is False
    ok = c.post('/api/gathering/memory/import', json={'session_id': s['id'], 'consent': True, 'items':[{'text':'story'}]}).json()
    assert ok['ok'] is True
