from sqlmodel import Session

from .conftest import make_client
from app.db import engine
from app.models import Agent


def _seed_agent() -> int:
    with Session(engine) as session:
        a = Agent(name='LegacySeed', model='llama3.1', role='guide', system_prompt='hi')
        session.add(a)
        session.commit()
        session.refresh(a)
        return a.id


def test_legacy_soul_and_nurture():
    c = make_client()
    agent_id = _seed_agent()
    souls = c.get('/api/legacy/souls').json()
    assert isinstance(souls['items'], list)

    nurtured = c.post('/api/legacy/nurture', json={'agent_id': agent_id, 'dimension': 'creative', 'delta': 5, 'note': 'great jam'}).json()
    assert nurtured['traits']['creative'] >= 15


def test_legacy_tree_child_and_heirloom():
    c = make_client()
    parent_id = _seed_agent()
    child = c.post('/api/legacy/child', json={'parent_ids': [parent_id], 'child_name': 'Historian', 'specialization': 'family stories'}).json()
    assert child['lineage']['parents'] == [parent_id]

    tree = c.get('/api/legacy/tree').json()
    assert 'nodes' in tree and 'edges' in tree

    zip_resp = c.get(f'/api/legacy/heirloom/{parent_id}.zip')
    assert zip_resp.status_code == 200
