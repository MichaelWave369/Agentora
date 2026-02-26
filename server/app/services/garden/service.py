import json
import random
from datetime import datetime

from sqlmodel import Session, select

from app.models import CosmosWorld, GardenBed, GardenHarvest

ROLES = ['Waterer', 'Pruner', 'Pollinator', 'Harvester']
SEASONS = ['Spring', 'Summer', 'Autumn', 'Winter']


def ensure_garden_beds(session: Session):
    worlds = session.exec(select(CosmosWorld)).all()
    created = 0
    for w in worlds:
        exists = session.exec(select(GardenBed).where(GardenBed.cosmos_world_id == w.id)).first()
        if exists:
            continue
        bed = GardenBed(
            cosmos_world_id=w.id,
            plant_name=f'{w.name} Tree',
            season='Spring',
            growth=random.randint(5, 25),
            gardener_role=random.choice(ROLES),
            memories_json=json.dumps([{'kind': 'seed', 'text': w.seed_prompt, 'at': datetime.utcnow().isoformat()}]),
        )
        session.add(bed)
        created += 1
    session.commit()
    return created


def garden_map(session: Session) -> dict:
    ensure_garden_beds(session)
    beds = session.exec(select(GardenBed).order_by(GardenBed.created_at)).all()
    return {
        'items': [
            {
                'id': b.id,
                'cosmos_world_id': b.cosmos_world_id,
                'plant_name': b.plant_name,
                'season': b.season,
                'growth': b.growth,
                'gardener_role': b.gardener_role,
                'memories': json.loads(b.memories_json),
            }
            for b in beds
        ]
    }


def tend_bed(session: Session, bed_id: int, gardener_role: str, note: str = '') -> dict:
    bed = session.get(GardenBed, bed_id)
    if not bed:
        raise ValueError('garden_bed_not_found')
    bed.gardener_role = gardener_role if gardener_role in ROLES else bed.gardener_role
    bed.growth = min(100, bed.growth + random.randint(5, 18))
    memories = json.loads(bed.memories_json)
    if note:
        memories.append({'kind': 'bloom', 'text': note, 'at': datetime.utcnow().isoformat()})
    bed.memories_json = json.dumps(memories)
    session.add(bed)
    session.commit()
    session.refresh(bed)
    return {'id': bed.id, 'growth': bed.growth, 'message': 'This memory is blooming beautifully ❤️'}


def advance_season(session: Session) -> dict:
    beds = session.exec(select(GardenBed)).all()
    for bed in beds:
        idx = SEASONS.index(bed.season) if bed.season in SEASONS else 0
        bed.season = SEASONS[(idx + 1) % len(SEASONS)]
        bed.growth = max(0, min(100, bed.growth + (8 if bed.season in ['Spring', 'Summer'] else -2)))
        session.add(bed)
    session.commit()
    return {'season': beds[0].season if beds else 'Spring', 'beds_updated': len(beds)}


def harvest_bed(session: Session, bed_id: int) -> dict:
    bed = session.get(GardenBed, bed_id)
    if not bed:
        raise ValueError('garden_bed_not_found')
    payload = {
        'plant_name': bed.plant_name,
        'season': bed.season,
        'wisdom': f"Harvest from {bed.plant_name}: nurture, prune, and let stories bloom.",
        'growth': bed.growth,
    }
    event = GardenHarvest(garden_bed_id=bed.id, harvest_type='wisdom', payload_json=json.dumps(payload))
    bed.growth = max(5, bed.growth - 30)
    session.add(event)
    session.add(bed)
    session.commit()
    return {'harvest': payload, 'message': 'Harvest complete — new seeds are ready to plant.'}


def community_garden(session: Session) -> dict:
    beds = session.exec(select(GardenBed)).all()
    return {
        'shared_beds': [
            {
                'bed_id': b.id,
                'plant_name': b.plant_name,
                'growth': b.growth,
                'season': b.season,
                'animation': 'sparkle-grow',
            }
            for b in beds[:12]
        ]
    }
