from __future__ import annotations

from sqlmodel import Session

from app.models import WorkerJob

from .capsules import ingest_text_as_capsules
from .worker_queue import worker_queue


async def route_capsule_ingest(session: Session, run_id: int, text: str, source: str, attachment_id: int | None = None) -> dict:
    inserted = await ingest_text_as_capsules(session=session, run_id=run_id, text=text, source=source, attachment_id=attachment_id)
    return {'ok': True, 'capsules_created': inserted}


def route_worker_job(session: Session, job_type: str, payload: dict) -> WorkerJob:
    return worker_queue.dispatch(session=session, job_type=job_type, payload=payload)
