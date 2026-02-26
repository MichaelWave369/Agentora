import json
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

from sqlmodel import Session, select

from app.models import CosmosTimeline, CosmosWorld, OpenCosmosMerge, OpenCosmosShare
from app.services.legacy.service import list_souls

OPEN_DIR = Path('server/data/open_cosmos')


def _ensure_dirs() -> None:
    OPEN_DIR.mkdir(parents=True, exist_ok=True)


def _manifest(world: CosmosWorld, timelines: list[CosmosTimeline], souls: list[dict], visibility: str, wisdom_mode: str) -> dict:
    return {
        'format': 'agentora-open-cosmos-v1',
        'world_id': world.id,
        'world_name': world.name,
        'created_at': datetime.utcnow().isoformat(),
        'visibility': visibility,
        'wisdom_mode': wisdom_mode,
        'timelines': len(timelines),
        'souls': len(souls),
        'backward_compatible_with': ['v0.5'],
    }


def share_cosmos(session: Session, world_id: int, visibility: str = 'private', wisdom_mode: str = 'anonymized', contributors: list[dict] | None = None) -> OpenCosmosShare:
    _ensure_dirs()
    world = session.get(CosmosWorld, world_id)
    if not world:
        raise ValueError('world_not_found')
    timelines = session.exec(select(CosmosTimeline).where(CosmosTimeline.world_id == world_id)).all()
    souls = list_souls(session)
    manifest = _manifest(world, timelines, souls, visibility, wisdom_mode)

    package_name = f"cosmos-{world_id}-{int(datetime.utcnow().timestamp())}.agentora"
    package_path = OPEN_DIR / package_name
    with ZipFile(package_path, 'w') as zf:
        zf.writestr('manifest.json', json.dumps(manifest, indent=2))
        zf.writestr('world.json', json.dumps(world.model_dump(), default=str, indent=2))
        zf.writestr('timelines.json', json.dumps([t.model_dump() for t in timelines], default=str, indent=2))
        zf.writestr('souls.json', json.dumps(souls, indent=2))
        zf.writestr('credits.json', json.dumps(contributors or [{'name': 'Local Family', 'role': 'host'}], indent=2))

    share = OpenCosmosShare(
        world_id=world_id,
        package_name=package_name,
        visibility=visibility,
        wisdom_mode=wisdom_mode,
        manifest_json=json.dumps(manifest),
        contributors_json=json.dumps(contributors or [{'name': 'Local Family', 'role': 'host'}]),
    )
    session.add(share)
    session.commit()
    session.refresh(share)
    return share


def import_package(session: Session, package_name: str, keep_timelines: list[str] | None = None) -> dict:
    _ensure_dirs()
    package_path = OPEN_DIR / package_name
    if not package_path.exists():
        raise ValueError('package_not_found')

    with ZipFile(package_path, 'r') as zf:
        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
        world_data = json.loads(zf.read('world.json').decode('utf-8'))
        timelines = json.loads(zf.read('timelines.json').decode('utf-8'))

    imported = CosmosWorld(
        name=f"{world_data['name']} (Imported)",
        seed_prompt=world_data.get('seed_prompt', 'Imported world'),
        warmth=world_data.get('warmth', 60),
        map_json=world_data.get('map_json', '[]'),
        rules_json=world_data.get('rules_json', '{}'),
        history_json=world_data.get('history_json', '[]'),
    )
    session.add(imported)
    session.commit()
    session.refresh(imported)

    keep = set(keep_timelines or [])
    conflicts = []
    imported_count = 0
    for t in timelines:
        title = t.get('title', 'Imported Timeline')
        if keep and title not in keep:
            continue
        if session.exec(select(CosmosTimeline).where(CosmosTimeline.world_id == imported.id, CosmosTimeline.title == title)).first():
            conflicts.append({'title': title, 'resolution': 'skipped_duplicate'})
            continue
        session.add(CosmosTimeline(world_id=imported.id, parent_timeline_id=0, title=title, branch_prompt=t.get('branch_prompt', ''), diff_json=t.get('diff_json', '{}')))
        imported_count += 1
    session.commit()

    merge = OpenCosmosMerge(
        world_id=imported.id,
        source_package=package_name,
        decisions_json=json.dumps({'keep_timelines': keep_timelines or 'all'}),
        conflicts_json=json.dumps(conflicts),
        status='merged_with_conflicts' if conflicts else 'merged',
    )
    session.add(merge)
    session.commit()

    return {
        'imported_world_id': imported.id,
        'imported_timelines': imported_count,
        'conflicts': conflicts,
        'message': 'Your cosmos is now safely shared with the community ❤️',
        'manifest': manifest,
    }


def list_shares(session: Session) -> list[dict]:
    return [
        {
            'id': s.id,
            'world_id': s.world_id,
            'package_name': s.package_name,
            'visibility': s.visibility,
            'wisdom_mode': s.wisdom_mode,
            'revoked': s.revoked,
            'contributors': json.loads(s.contributors_json),
            'manifest': json.loads(s.manifest_json),
        }
        for s in session.exec(select(OpenCosmosShare).order_by(OpenCosmosShare.created_at.desc())).all()
    ]


def revoke_share(session: Session, share_id: int) -> bool:
    share = session.get(OpenCosmosShare, share_id)
    if not share:
        return False
    share.revoked = True
    session.add(share)
    session.commit()
    return True


def global_wisdom_archive(session: Session, enabled: bool) -> dict:
    shares = list_shares(session)
    insights = []
    if enabled:
        for s in shares:
            insights.append({'package': s['package_name'], 'insight': 'Community branch favored empathy + truth balance.'})
    return {'enabled': enabled, 'insights': insights, 'privacy': 'local-only anonymized cache'}


def living_legacy_network(session: Session) -> dict:
    cards = []
    for s in list_shares(session):
        cards.append({'title': s['manifest']['world_name'], 'package': s['package_name'], 'thumbnail': '🌌', 'credits': s['contributors']})
    return {'items': cards}
