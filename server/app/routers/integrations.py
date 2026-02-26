import json
from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db import get_session
from app.models import IntegrationSetting, Run, Message
from app.services.adapters.integrations import statuses

router = APIRouter(tags=['integrations'])


@router.get('/api/integrations/status')
def integration_status(session: Session = Depends(get_session)):
    return {'integrations': statuses(session)}


@router.post('/api/integrations/enable')
def integration_enable(payload: dict, session: Session = Depends(get_session)):
    row = session.get(IntegrationSetting, payload['name'])
    if not row:
        row = IntegrationSetting(name=payload['name'], enabled=False, config_json='{}')
    row.enabled = bool(payload.get('enabled', True))
    row.config_json = json.dumps(payload.get('config', {}))
    session.add(row)
    session.commit()
    return {'ok': True}


@router.post('/api/exports/growora')
def export_growora(payload: dict, session: Session = Depends(get_session)):
    run = session.get(Run, payload['run_id'])
    msgs = session.query(Message).filter(Message.run_id == payload['run_id']).all()
    return {
        'skill_graph': {'nodes': [{'id': 'skill-1', 'label': run.mode if run else 'unknown'}]},
        'micro_drills': [m.content[:80] for m in msgs[:3]],
    }
