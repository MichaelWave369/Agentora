import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from app.db import get_session
from app.models import SongJob, VocalPersona, Team, ArenaMatch
from app.services.audio_utils import sine_wave, peaks_for_wave

router = APIRouter(prefix='/api/studio', tags=['studio'])


def ensure_personas(session: Session):
    if session.exec(select(VocalPersona)).first():
        return
    for name, style in [
        ('soulful_crooner', 'Soul'), ('metal_screamer', 'Metal'), ('ethereal_choir', 'Ambient'),
        ('rap_battle_mc', 'Rap'), ('warm_narrator', 'Narration')
    ]:
        session.add(VocalPersona(name=name, style=style, prompt_style=style))
    session.commit()


@router.get('/personas')
def list_personas(session: Session = Depends(get_session)):
    ensure_personas(session)
    return [p.model_dump() for p in session.exec(select(VocalPersona))]


@router.post('/sing')
def sing(payload: dict, session: Session = Depends(get_session)):
    team = session.get(Team, payload['team_id'])
    if not team:
        raise HTTPException(404, 'team not found')
    lyrics = {
        'sections': [
            {'t': 0, 'text': f"{payload.get('prompt','')} in neon twilight"},
            {'t': 5, 'text': 'Truth and thunder in a chorus of light'},
        ]
    }
    existing = list(session.exec(select(SongJob)))
    out = Path('server/data/studio') / f"song_{team.id}_{len(existing)+1}"
    master = sine_wave(str(out / 'master.wav'), freq=440, duration=1.2)
    stems = {'lead': sine_wave(str(out / 'lead.wav'), freq=520, duration=1.2), 'harmony': sine_wave(str(out / 'harmony.wav'), freq=330, duration=1.2)}
    job = SongJob(team_id=team.id, status='completed', lyrics_json=json.dumps(lyrics), waveform_json=json.dumps(peaks_for_wave(master)), master_path=master, stems_json=json.dumps(stems))
    session.add(job)
    session.commit()
    session.refresh(job)
    return {'run_id': 0, 'song_job_id': job.id}


@router.get('/song/{song_job_id}/status')
def song_status(song_job_id: int, session: Session = Depends(get_session)):
    job = session.get(SongJob, song_job_id)
    if not job:
        raise HTTPException(404, 'not found')
    return {'status': job.status}


@router.get('/song/{song_job_id}/master.wav')
def song_master(song_job_id: int, session: Session = Depends(get_session)):
    job = session.get(SongJob, song_job_id)
    return FileResponse(job.master_path, media_type='audio/wav', filename='master.wav')


@router.get('/song/{song_job_id}/stems/{agent}.wav')
def song_stem(song_job_id: int, agent: str, session: Session = Depends(get_session)):
    job = session.get(SongJob, song_job_id)
    stems = json.loads(job.stems_json)
    if agent not in stems:
        raise HTTPException(404, 'stem missing')
    return FileResponse(stems[agent], media_type='audio/wav', filename=f'{agent}.wav')


@router.get('/song/{song_job_id}/waveform.json')
def song_waveform(song_job_id: int, session: Session = Depends(get_session)):
    job = session.get(SongJob, song_job_id)
    return {'peaks': json.loads(job.waveform_json)}


@router.post('/turn-verdict-into-anthem')
def turn_verdict_into_anthem(payload: dict, session: Session = Depends(get_session)):
    match = session.get(ArenaMatch, payload['match_id'])
    prompt = f"Turn this verdict into an anthem: {match.report_md[:200]}"
    return sing({'team_id': payload['team_id'], 'prompt': prompt}, session)


@router.post('/narrate-highlights')
def narrate_highlights(payload: dict, session: Session = Depends(get_session)):
    return {'ok': True, 'narration': f"Tonight in the Arena: {payload.get('summary','highlights')}"}
