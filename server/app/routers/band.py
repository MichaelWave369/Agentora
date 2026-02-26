import json
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlmodel import Session

from app.db import get_session
from app.models import BandTrackJob
from app.services.audio_utils import sine_wave

router = APIRouter(prefix='/api/band', tags=['band'])


@router.post('/create_track')
def create_track(payload: dict, session: Session = Depends(get_session)):
    d = Path('server/data/band') / f"track_{payload.get('team_id',0)}_{payload.get('genre','noir')}"
    d.mkdir(parents=True, exist_ok=True)
    stems = {
        'drums': sine_wave(str(d / 'drums.wav'), 120),
        'bass': sine_wave(str(d / 'bass.wav'), 80),
        'melody': sine_wave(str(d / 'melody.wav'), 440),
        'vocals': sine_wave(str(d / 'vocals.wav'), 260),
        'fx': sine_wave(str(d / 'fx.wav'), 700),
    }
    master = sine_wave(str(d / 'master.wav'), 320)
    plan = {'bpm': payload.get('bpm', 110), 'genre': payload.get('genre', 'synthwave'), 'iterations': [{'vote': {'BeatSmith': 8, 'MixMaster': 9}}]}
    lyrics = {'lines': [{'t': 0, 'text': 'Neon pulse in midnight code'}]}
    job = BandTrackJob(team_id=payload.get('team_id', 0), status='completed', plan_json=json.dumps(plan), lyrics_json=json.dumps(lyrics), master_path=master, stems_json=json.dumps(stems))
    session.add(job)
    session.commit()
    session.refresh(job)
    return {'track_job_id': job.id}


@router.get('/track/{track_id}/status')
def track_status(track_id: int, session: Session = Depends(get_session)):
    row = session.get(BandTrackJob, track_id)
    return {'status': row.status, 'plan': json.loads(row.plan_json)}


@router.get('/track/{track_id}/master.wav')
def track_master(track_id: int, session: Session = Depends(get_session)):
    row = session.get(BandTrackJob, track_id)
    return FileResponse(row.master_path, media_type='audio/wav')


@router.get('/track/{track_id}/stems/{stem}.wav')
def track_stem(track_id: int, stem: str, session: Session = Depends(get_session)):
    row = session.get(BandTrackJob, track_id)
    stems = json.loads(row.stems_json)
    if stem not in stems:
        raise HTTPException(404, 'missing stem')
    return FileResponse(stems[stem], media_type='audio/wav')


@router.get('/track/{track_id}/lyrics.json')
def track_lyrics(track_id: int, session: Session = Depends(get_session)):
    row = session.get(BandTrackJob, track_id)
    return json.loads(row.lyrics_json)


@router.post('/track/{track_id}/publish_coevo')
def publish_coevo(track_id: int, payload: dict):
    if not payload.get('coevo_url'):
        return {'ok': False, 'message': 'Not configured'}
    return {'ok': True, 'published': False, 'message': 'adapter stub'}
