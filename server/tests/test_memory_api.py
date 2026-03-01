from sqlmodel import Session

from app.db import engine
from app.models import Capsule
from .conftest import make_client


def test_memory_endpoints_smoke():
    client = make_client()
    with Session(engine) as session:
        cap = Capsule(run_id=9901, source='unit', text='memory api capsule', memory_layer='L1_SHORT')
        session.add(cap)
        session.commit()
        session.refresh(cap)

    layers = client.get('/api/memory/layers')
    assert layers.status_code == 200

    detail = client.get(f'/api/memory/capsules/{cap.id}')
    assert detail.status_code == 200

    contexts = client.get('/api/memory/runs/9901/contexts')
    assert contexts.status_code == 200

    trace = client.get('/api/memory/runs/9901/trace')
    assert trace.status_code == 200

    health = client.get('/api/memory/health')
    assert health.status_code == 200

    lineage = client.get(f'/api/memory/capsules/{cap.id}/lineage')
    assert lineage.status_code == 200

    neighbors = client.get(f'/api/memory/capsules/{cap.id}/neighbors')
    assert neighbors.status_code == 200

    maintenance = client.post('/api/memory/maintenance/run', json={'run_id': 9901, 'try_worker': False})
    assert maintenance.status_code == 200

    promote = client.post(f'/api/memory/capsules/{cap.id}/promote')
    assert promote.status_code == 200

    demote = client.post(f'/api/memory/capsules/{cap.id}/demote')
    assert demote.status_code == 200
