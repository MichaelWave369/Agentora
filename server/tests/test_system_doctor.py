from app.services.runtime.system_doctor import run_doctor
from .conftest import make_client


def test_doctor_report_shape():
    report = run_doctor()
    assert report['status'] in {'ok', 'warn', 'error'}
    assert isinstance(report['items'], list)
    assert any(item['key'] == 'ollama' for item in report['items'])


def test_system_endpoints():
    client = make_client()
    r = client.get('/api/system/version')
    assert r.status_code == 200
    assert r.json()['version'] == '1.0.0-rc1'
    assert 'title' in r.json()

    d = client.get('/api/system/doctor')
    assert d.status_code == 200
    assert 'items' in d.json()
    assert 'next_steps' in d.json()
