from pathlib import Path
from .conftest import make_client


def test_yaml_import():
    c = make_client()
    y = Path('teams/truthquest.yaml').read_text(encoding='utf-8')
    r = c.post('/api/teams/import-yaml', json={'yaml_text': y})
    assert r.status_code == 200
    assert r.json()['ok'] is True
