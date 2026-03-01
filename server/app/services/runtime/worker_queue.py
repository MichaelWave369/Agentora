from __future__ import annotations

from datetime import datetime
import json
from itertools import cycle

import requests
from sqlmodel import Session, select

from app.core.config import settings
from app.models import WorkerNode, WorkerJob


class WorkerQueue:
    def __init__(self):
        urls = [u.strip() for u in settings.agentora_worker_urls.split(',') if u.strip()]
        self._urls = urls
        self._rr = cycle(urls) if urls else None

    def register(self, session: Session, name: str, url: str, capabilities: list[str]) -> WorkerNode:
        node = WorkerNode(name=name, url=url, capabilities_json=json.dumps(capabilities), status='online', last_seen_at=datetime.utcnow())
        session.add(node)
        session.commit()
        session.refresh(node)
        return node

    def list_nodes(self, session: Session) -> list[WorkerNode]:
        return list(session.exec(select(WorkerNode).order_by(WorkerNode.id.desc())))

    def dispatch(self, session: Session, job_type: str, payload: dict) -> WorkerJob:
        job = WorkerJob(job_type=job_type, payload_json=json.dumps(payload), status='queued')
        session.add(job)
        session.commit()
        session.refresh(job)
        if not self._urls:
            job.status = 'fallback_local'
            job.result_json = '{"mode":"local"}'
            session.add(job)
            session.commit()
            return job

        target = next(self._rr)
        try:
            r = requests.post(f'{target.rstrip("/")}/api/worker/execute', json={'type': job_type, 'payload': payload}, timeout=20)
            if r.ok:
                job.status = 'done'
                job.result_json = r.text[:4000]
            else:
                job.status = 'failed'
                job.error = f'http {r.status_code}'
        except Exception as exc:
            job.status = 'fallback_local'
            job.error = str(exc)
            job.result_json = '{"mode":"local"}'
        session.add(job)
        session.commit()
        return job


worker_queue = WorkerQueue()
