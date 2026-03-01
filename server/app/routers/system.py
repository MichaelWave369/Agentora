from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.core.config import settings
from app.db import get_session
from app.services.runtime.bootstrap import run_bootstrap
from app.services.runtime.system_doctor import run_doctor

router = APIRouter(prefix='/api/system', tags=['system'])


@router.get('/health')
def health():
    return {'ok': True, 'service': settings.app_name, 'mode': settings.agentora_network_mode}


@router.get('/version')
def version():
    return {
        'ok': True,
        'version': '0.9.6',
        'title': 'Agentora v0.9.6 — Operator Mode & One-Click Deployment',
    }


@router.get('/doctor')
def doctor():
    report = run_doctor()
    return {'ok': True, **report}


@router.post('/bootstrap')
def bootstrap(payload: dict | None = None, session: Session = Depends(get_session)):
    auto_fix = bool((payload or {}).get('auto_fix', False))
    return run_bootstrap(session, auto_fix=auto_fix)
