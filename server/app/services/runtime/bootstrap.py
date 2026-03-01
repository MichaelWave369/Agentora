from __future__ import annotations

from datetime import datetime
import json

from sqlmodel import Session, select

from app.models import BootstrapState
from app.services.runtime.system_doctor import run_doctor


def run_bootstrap(session: Session, auto_fix: bool = False) -> dict:
    report = run_doctor()
    state = session.exec(select(BootstrapState).order_by(BootstrapState.id.desc())).first()
    if not state:
        state = BootstrapState(version='0.9.6')
    state.doctor_status = report['status']
    state.report_json = json.dumps({'auto_fix': auto_fix, 'report': report})
    state.updated_at = datetime.utcnow()
    session.add(state)
    session.commit()
    session.refresh(state)
    return {
        'ok': True,
        'status': report['status'],
        'report': report,
        'bootstrap_state_id': state.id,
        'auto_fix_applied': False,
    }
