import json
from datetime import datetime
from pathlib import Path
from typing import Optional
from zipfile import ZipFile

from sqlmodel import Session, select

from app.models import ArenaMatch, CosmosTimeline, CosmosWorld, SongJob
from app.services.legacy.service import list_souls

SEEDS_DIR = Path('server/data/cosmos/seeds')


def _ensure_dirs() -> None:
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)


def _seed_map(name: str, seed_prompt: str) -> list[dict]:
    return [
        {'id': 'core-star', 'label': f'{name} Core', 'kind': 'legacy-core', 'x': 24, 'y': 48},
        {'id': 'origin', 'label': 'Origin Event', 'kind': 'chapter', 'note': seed_prompt, 'x': 52, 'y': 42},
        {'id': 'future', 'label': 'Possible Future', 'kind': 'oracle', 'x': 76, 'y': 58},
    ]


def create_world(session: Session, name: str, seed_prompt: str, warmth: int = 60) -> CosmosWorld:
    world = CosmosWorld(
        name=name,
        seed_prompt=seed_prompt,
        warmth=max(0, min(100, warmth)),
        map_json=json.dumps(_seed_map(name, seed_prompt)),
        rules_json=json.dumps({'privacy': 'offline-local-only', 'telemetry': False}),
        history_json=json.dumps([{'type': 'created', 'at': datetime.utcnow().isoformat(), 'seed': seed_prompt}]),
    )
    session.add(world)
    session.commit()
    session.refresh(world)

    root = CosmosTimeline(world_id=world.id, title='Prime Timeline', branch_prompt='root timeline', diff_json='{}')
    session.add(root)
    session.commit()
    return world


def list_worlds(session: Session) -> list[CosmosWorld]:
    return session.exec(select(CosmosWorld).order_by(CosmosWorld.created_at.desc())).all()


def get_world(session: Session, world_id: int) -> Optional[CosmosWorld]:
    return session.get(CosmosWorld, world_id)


def branch_timeline(session: Session, world_id: int, parent_timeline_id: int, title: str, branch_prompt: str) -> CosmosTimeline:
    diff = {
        'branch_prompt': branch_prompt,
        'emotional_microcopy': 'This branch feels hopeful…',
        'created_at': datetime.utcnow().isoformat(),
    }
    timeline = CosmosTimeline(
        world_id=world_id,
        parent_timeline_id=parent_timeline_id,
        title=title,
        branch_prompt=branch_prompt,
        diff_json=json.dumps(diff),
    )
    session.add(timeline)
    session.commit()
    session.refresh(timeline)
    return timeline


def list_timelines(session: Session, world_id: int) -> list[CosmosTimeline]:
    return session.exec(select(CosmosTimeline).where(CosmosTimeline.world_id == world_id).order_by(CosmosTimeline.created_at)).all()


def collapse_timelines(session: Session, world_id: int) -> dict:
    timelines = list_timelines(session, world_id)
    kept = 0
    for tl in timelines:
        if tl.parent_timeline_id == 0 and kept == 0:
            kept += 1
            continue
        tl.status = 'collapsed'
        session.add(tl)
    session.commit()
    return {'world_id': world_id, 'collapsed': max(0, len(timelines) - 1)}


def prune_timeline(session: Session, timeline_id: int) -> bool:
    tl = session.get(CosmosTimeline, timeline_id)
    if not tl:
        return False
    tl.status = 'pruned'
    session.add(tl)
    session.commit()
    return True


def eternal_archive(session: Session, query: str = '') -> dict:
    songs = session.exec(select(SongJob)).all()
    debates = session.exec(select(ArenaMatch)).all()
    souls = list_souls(session)
    query_l = query.lower().strip()

    def _match(text: str) -> bool:
        return not query_l or query_l in (text or '').lower()

    return {
        'songs': [
            {'id': s.id, 'status': s.status, 'summary': 'studio song artifact'}
            for s in songs
            if _match(s.status)
        ],
        'debates': [
            {'id': d.id, 'topic': d.topic, 'status': d.status}
            for d in debates
            if _match(d.topic)
        ],
        'souls': [
            {'agent_id': s['agent_id'], 'agent_name': s['agent_name'], 'evolution_points': s['evolution_points']}
            for s in souls
            if _match(s['agent_name'])
        ],
    }


def cosmic_reflection(session: Session, world_id: int, warmth: int = 60) -> dict:
    world = get_world(session, world_id)
    if not world:
        raise ValueError('world_not_found')
    tone = 'hopeful' if warmth >= 60 else 'realistic'
    return {
        'world_id': world_id,
        'tone': tone,
        'message': f"Around the cosmic fire, your family agents see a {tone} path forward.",
        'oracle': 'What would my great-grandchild’s AI companion say? Keep love and truth in balance.',
    }


def export_eternal_seed(session: Session, world_id: int) -> Path:
    _ensure_dirs()
    world = get_world(session, world_id)
    if not world:
        raise ValueError('world_not_found')
    timelines = list_timelines(session, world_id)
    souls = list_souls(session)
    out = SEEDS_DIR / f'cosmos-{world_id}-eternal-seed.zip'
    with ZipFile(out, 'w') as zf:
        zf.writestr('world.json', json.dumps(world.model_dump(), default=str, indent=2))
        zf.writestr('timelines.json', json.dumps([t.model_dump() for t in timelines], default=str, indent=2))
        zf.writestr('souls.json', json.dumps(souls, indent=2))
        zf.writestr('README.txt', 'Eternal Seed v2.0 — local-first archive for future generations.')
    return out


def storage_warning(session: Session) -> dict:
    worlds = list_worlds(session)
    timelines = session.exec(select(CosmosTimeline)).all()
    score = len(worlds) + len(timelines)
    return {'warning': score > 100, 'worlds': len(worlds), 'timelines': len(timelines)}
