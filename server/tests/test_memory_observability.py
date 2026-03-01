from sqlmodel import Session

from app.db import engine
from app.models import Capsule
from .conftest import make_client


def test_memory_health_lineage_and_neighbors_endpoints():
    client = make_client()
    with Session(engine) as session:
        root = Capsule(run_id=9810, source='unit', text='root capsule', memory_layer='L2_SESSION', lineage_root_id=None)
        session.add(root)
        session.commit()
        session.refresh(root)
        root_id = root.id
        child = Capsule(run_id=9810, source='unit', text='child capsule', memory_layer='L2_SESSION', parent_capsule_id=root_id, lineage_root_id=root_id)
        session.add(child)
        session.commit()
        session.refresh(child)
        child_id = child.id

    health = client.get('/api/memory/health')
    assert health.status_code == 200
    assert 'counts_by_layer' in health.json()

    lineage = client.get(f'/api/memory/capsules/{child_id}/lineage')
    assert lineage.status_code == 200
    assert lineage.json().get('descendants')

    neighbors = client.get(f'/api/memory/capsules/{root_id}/neighbors')
    assert neighbors.status_code == 200


def test_memory_conflict_and_duplicates_endpoints():
    client = make_client()
    with Session(engine) as session:
        c1 = Capsule(run_id=9811, source='unit', text='system is not available now', memory_layer='L2_SESSION')
        c2 = Capsule(run_id=9811, source='unit', text='system is available now', memory_layer='L2_SESSION')
        session.add(c1)
        session.add(c2)
        session.commit()

    post_conflicts = client.post('/api/memory/maintenance/conflicts', json={'run_id': 9811})
    assert post_conflicts.status_code == 200

    conflicts = client.get('/api/memory/conflicts')
    assert conflicts.status_code == 200

    duplicates = client.get('/api/memory/duplicates')
    assert duplicates.status_code == 200
