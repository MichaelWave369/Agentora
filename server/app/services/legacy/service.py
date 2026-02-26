import json
import random
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zipfile import ZipFile

from sqlmodel import Session, select

from app.models import Agent, ArenaMatch, BandTrackJob, SongJob

SOULS_DIR = Path('server/data/legacy/souls')
HEIRLOOMS_DIR = Path('server/data/legacy/heirlooms')


def _ensure_dirs() -> None:
    SOULS_DIR.mkdir(parents=True, exist_ok=True)
    HEIRLOOMS_DIR.mkdir(parents=True, exist_ok=True)


def _default_soul(agent: Agent) -> dict:
    return {
        'agent_id': agent.id,
        'agent_name': agent.name,
        'traits': {'humorous': 10, 'truthful': 10, 'creative': 10, 'empathetic': 10},
        'evolution_points': 0,
        'lineage': {'parents': [], 'children': []},
        'timeline': [],
        'avatar_stage': 1,
        'archived': False,
        'updated_at': datetime.utcnow().isoformat(),
    }


def soul_path(agent_id: int) -> Path:
    return SOULS_DIR / f'agent-{agent_id}.soul.json'


def load_or_create_soul(session: Session, agent_id: int) -> dict:
    _ensure_dirs()
    agent = session.get(Agent, agent_id)
    if not agent:
        raise ValueError('agent_not_found')
    path = soul_path(agent_id)
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    soul = _default_soul(agent)
    path.write_text(json.dumps(soul, indent=2), encoding='utf-8')
    return soul


def save_soul(soul: dict) -> dict:
    _ensure_dirs()
    soul['updated_at'] = datetime.utcnow().isoformat()
    path = soul_path(int(soul['agent_id']))
    path.write_text(json.dumps(soul, indent=2), encoding='utf-8')
    return soul


def list_souls(session: Session) -> list[dict]:
    agents = session.exec(select(Agent)).all()
    return [load_or_create_soul(session, a.id) for a in agents if a.id is not None]


def nurture(agent_id: int, dimension: str, delta: int, note: str, session: Session) -> dict:
    soul = load_or_create_soul(session, agent_id)
    if dimension not in soul['traits']:
        raise ValueError('invalid_trait')
    soul['traits'][dimension] = max(0, min(100, soul['traits'][dimension] + delta))
    soul['evolution_points'] += max(1, abs(delta))
    soul['avatar_stage'] = 1 + soul['evolution_points'] // 25
    soul['timeline'].append({'type': 'nurture', 'dimension': dimension, 'delta': delta, 'note': note, 'at': datetime.utcnow().isoformat()})
    return save_soul(soul)


def reflection(agent_id: int, session: Session) -> dict:
    soul = load_or_create_soul(session, agent_id)
    focus = max(soul['traits'], key=lambda k: soul['traits'][k])
    soul['timeline'].append({'type': 'reflection', 'insight': f'I grew most in {focus} and want to support the family with steadier tone.', 'proposed_trait_boost': focus, 'at': datetime.utcnow().isoformat()})
    soul['evolution_points'] += 3
    return save_soul(soul)


def _blend_traits(a: dict, b: dict) -> dict:
    keys = sorted(set(a['traits'].keys()) | set(b['traits'].keys()))
    return {k: int((a['traits'].get(k, 10) + b['traits'].get(k, 10)) / 2) for k in keys}


def spawn_child(session: Session, parent_ids: Iterable[int], child_name: str, specialization: str) -> dict:
    parent_ids = [int(p) for p in parent_ids]
    parents = [load_or_create_soul(session, pid) for pid in parent_ids]
    if not parents:
        raise ValueError('missing_parents')
    merged = parents[0]
    for p in parents[1:]:
        merged = {'traits': _blend_traits(merged, p)}
    child = Agent(name=child_name, model='llama3.1', role=specialization, system_prompt=f'Legacy child agent focused on {specialization}.')
    session.add(child)
    session.commit()
    session.refresh(child)

    soul = _default_soul(child)
    soul['traits'] = merged['traits']
    soul['lineage']['parents'] = parent_ids
    soul['timeline'].append({'type': 'born', 'specialization': specialization, 'at': datetime.utcnow().isoformat()})
    save_soul(soul)

    for p in parents:
        p['lineage']['children'].append(child.id)
        save_soul(p)
    return soul


def ingest_mode_history(session: Session, agent_id: int) -> dict:
    soul = load_or_create_soul(session, agent_id)
    song_count = len(session.exec(select(SongJob)).all())
    track_count = len(session.exec(select(BandTrackJob)).all())
    debate_wins = len([m for m in session.exec(select(ArenaMatch)).all() if 'winner' in (m.report_md or '').lower()])
    soul['timeline'].append({'type': 'mode_sync', 'songs_seen': song_count, 'tracks_seen': track_count, 'debates_seen': debate_wins, 'tooltip': f'This agent has sung {song_count} songs with the family ❤️', 'at': datetime.utcnow().isoformat()})
    soul['evolution_points'] += 5
    return save_soul(soul)


def export_heirloom(session: Session, agent_id: int) -> Path:
    _ensure_dirs()
    soul = load_or_create_soul(session, agent_id)
    out = HEIRLOOMS_DIR / f'agent-{agent_id}-heirloom.zip'
    with ZipFile(out, 'w') as zf:
        zf.writestr('soul.json', json.dumps(soul, indent=2))
        zf.writestr('living_story.md', '# Living Story\n\nA continuing family chronicle powered by Legacy mode.')
        zf.writestr('music_legacy_album.json', json.dumps({'tracks_reference': 'server/data/artifacts', 'note': 'Add exported songs here.'}, indent=2))
        zf.writestr('wisdom_archive.md', '# Wisdom Archive\n\nDebate victories and lessons for future agents.')
        zf.writestr('skill_branches.json', json.dumps({'growora': 'not_configured', 'branches': []}, indent=2))
    return out


def gather_legacy_stats(session: Session) -> dict:
    souls = list_souls(session)
    used_mb = round(sum(len(json.dumps(s)) for s in souls) / (1024 * 1024), 4)
    return {
        'souls': len(souls),
        'storage_mb': used_mb,
        'low_storage_warning': used_mb > 20,
        'family_night_reflection_hint': 'Gathering sessions can call /api/legacy/family-night-reflection to grow shared souls.',
        'seed': random.randint(1, 999),
    }
