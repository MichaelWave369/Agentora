import json
import random
from datetime import datetime

from sqlmodel import Session, select

from app.models import CosmosWorld, GardenBed, WorldGardenEvent, WorldGardenNode


def _default_latlon(seed: int) -> tuple[float, float]:
    random.seed(seed)
    return random.uniform(-60, 70), random.uniform(-170, 170)


def sync_world_nodes(session: Session) -> int:
    worlds = session.exec(select(CosmosWorld)).all()
    created = 0
    for w in worlds:
        node = session.exec(select(WorldGardenNode).where(WorldGardenNode.source_kind == 'cosmos', WorldGardenNode.source_id == w.id)).first()
        if node:
            continue
        lat, lon = _default_latlon(w.id or 0)
        session.add(WorldGardenNode(
            source_kind='cosmos',
            source_id=w.id or 0,
            title=w.name,
            lat=lat,
            lon=lon,
            glow=35,
            visibility='private',
            credits_json=json.dumps([{'name': 'Local Family', 'role': 'gardener'}]),
        ))
        created += 1
    session.commit()
    return created


def world_map(session: Session) -> dict:
    sync_world_nodes(session)
    nodes = session.exec(select(WorldGardenNode).order_by(WorldGardenNode.created_at.desc())).all()
    return {'items': [
        {
            'id': n.id,
            'title': n.title,
            'lat': n.lat,
            'lon': n.lon,
            'glow': n.glow,
            'visibility': n.visibility,
            'credits': json.loads(n.credits_json),
            'icon': '🌸' if n.glow > 60 else '🌿',
        }
        for n in nodes
    ]}


def infinite_bloom(session: Session, node_id: int, reason: str) -> dict:
    node = session.get(WorldGardenNode, node_id)
    if not node:
        raise ValueError('node_not_found')
    node.glow = min(100, node.glow + 20)
    evt = WorldGardenEvent(event_type='bloom', payload_json=json.dumps({'node_id': node_id, 'reason': reason, 'at': datetime.utcnow().isoformat()}))
    session.add(node)
    session.add(evt)
    session.commit()
    return {'node_id': node_id, 'glow': node.glow, 'message': 'Infinite Bloom awakened across the garden ✨'}


def cross_pollinate(session: Session, from_node: int, to_node: int, preview_only: bool = False) -> dict:
    a = session.get(WorldGardenNode, from_node)
    b = session.get(WorldGardenNode, to_node)
    if not a or not b:
        raise ValueError('node_not_found')
    preview = {
        'conflicts': ['title overlap'] if a.title == b.title else [],
        'merged_title': f'{a.title} × {b.title}',
        'credits': list({c['name'] for c in json.loads(a.credits_json) + json.loads(b.credits_json)}),
    }
    if preview_only:
        return {'preview': preview, 'applied': False}
    b.glow = min(100, b.glow + 12)
    b.credits_json = json.dumps([{'name': n, 'role': 'co-creator'} for n in preview['credits']])
    session.add(b)
    session.add(WorldGardenEvent(event_type='cross_pollination', payload_json=json.dumps(preview)))
    session.commit()
    return {'preview': preview, 'applied': True}


def constellation_links(session: Session) -> dict:
    nodes = session.exec(select(WorldGardenNode).order_by(WorldGardenNode.id)).all()
    links = []
    for i in range(0, max(0, len(nodes) - 1)):
        links.append({'from': nodes[i].id, 'to': nodes[i + 1].id, 'light': 'soft-cyan'})
    return {'links': links}


def harvest_festival(session: Session) -> dict:
    beds = session.exec(select(GardenBed)).all()
    top = sorted(beds, key=lambda b: b.growth, reverse=True)[:8]
    payload = {
        'festival': 'Eternal Harvest Festival',
        'highlights': [{'bed_id': b.id, 'plant': b.plant_name, 'growth': b.growth} for b in top],
        'created_at': datetime.utcnow().isoformat(),
    }
    session.add(WorldGardenEvent(event_type='festival', payload_json=json.dumps(payload)))
    session.commit()
    return payload
