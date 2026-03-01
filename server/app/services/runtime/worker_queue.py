from __future__ import annotations

from datetime import datetime, timedelta
import json
from typing import Any

import requests
from sqlmodel import Session, select

from app.core.config import settings
from app.models import WorkerNode, WorkerJob


TASK_CAPABILITY = {
    'embed_batch': 'embed_batch',
    'capsule_ingest': 'capsule_ingest',
    'python_exec': 'python_exec',
    'long_tool_job': 'long_tool_job',
}


class WorkerQueue:
    def register(self, session: Session, name: str, url: str, capabilities: list[str]) -> WorkerNode:
        existing = session.exec(select(WorkerNode).where(WorkerNode.url == url)).first()
        if existing:
            existing.name = name
            existing.capabilities_json = json.dumps(capabilities)
            existing.status = 'idle'
            existing.last_seen_at = datetime.utcnow()
            session.add(existing)
            session.commit()
            session.refresh(existing)
            return existing
        node = WorkerNode(name=name, url=url, capabilities_json=json.dumps(capabilities), status='idle', last_seen_at=datetime.utcnow())
        session.add(node)
        session.commit()
        session.refresh(node)
        return node

    def heartbeat(self, session: Session, worker_id: int, status: str = 'idle') -> WorkerNode | None:
        node = session.get(WorkerNode, worker_id)
        if not node:
            return None
        node.status = status if status in {'idle', 'busy', 'offline', 'degraded'} else 'degraded'
        node.last_seen_at = datetime.utcnow()
        session.add(node)
        session.commit()
        session.refresh(node)
        return node

    def list_nodes(self, session: Session) -> list[WorkerNode]:
        rows = list(session.exec(select(WorkerNode).order_by(WorkerNode.id.desc())))
        now = datetime.utcnow()
        for node in rows:
            if node.last_seen_at < now - timedelta(seconds=90):
                node.status = 'offline'
        return rows

    def _parse_caps(self, node: WorkerNode) -> set[str]:
        try:
            return set(json.loads(node.capabilities_json or '[]'))
        except Exception:
            return set()

    def _eligible_workers(self, session: Session, job_type: str) -> list[WorkerNode]:
        needed = TASK_CAPABILITY.get(job_type, job_type)
        workers = [w for w in self.list_nodes(session) if w.status in {'idle', 'busy'}]
        return [w for w in workers if needed in self._parse_caps(w)]

    def _create_job(self, session: Session, job_type: str, payload: dict[str, Any], priority: int) -> WorkerJob:
        job = WorkerJob(
            job_type=job_type,
            payload_json=json.dumps(payload),
            priority=max(1, min(10, priority)),
            status='queued',
            max_retries=settings.agentora_max_worker_retries,
            retries=0,
            updated_at=datetime.utcnow(),
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        return job

    def dispatch(self, session: Session, job_type: str, payload: dict, priority: int = 5) -> WorkerJob:
        job = self._create_job(session, job_type=job_type, payload=payload, priority=priority)
        urls = [u.strip() for u in settings.agentora_worker_urls.split(',') if u.strip()]
        candidates = self._eligible_workers(session, job_type)
        if not candidates and urls:
            # implicit workers from env urls with unknown capabilities
            candidates = [WorkerNode(id=None, name='env-worker', url=u, capabilities_json='[]', status='idle') for u in urls]

        if not candidates:
            job.status = 'fallback_local'
            job.used_fallback_local = True
            job.result_json = json.dumps({'mode': 'local', 'reason': 'no_worker_available'})
            job.updated_at = datetime.utcnow()
            session.add(job)
            session.commit()
            return job

        for node in sorted(candidates, key=lambda x: x.status != 'idle'):
            timeout = 12
            for attempt in range(settings.agentora_max_worker_retries + 1):
                job.retries = attempt
                job.status = 'running'
                job.worker_node_id = node.id
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()
                try:
                    r = requests.post(
                        f'{node.url.rstrip("/")}/api/worker/execute',
                        json={'job_id': job.id, 'type': job_type, 'payload': payload, 'priority': priority},
                        timeout=timeout,
                    )
                    if r.ok:
                        job.status = 'done'
                        job.result_json = r.text[:8000]
                        job.updated_at = datetime.utcnow()
                        session.add(job)
                        if node.id:
                            db_node = session.get(WorkerNode, node.id)
                            if db_node:
                                db_node.status = 'idle'
                                db_node.last_seen_at = datetime.utcnow()
                                session.add(db_node)
                        session.commit()
                        return job
                    job.error = f'http {r.status_code}'
                except requests.Timeout:
                    job.error = 'worker_timeout'
                except Exception as exc:
                    job.error = str(exc)
                job.updated_at = datetime.utcnow()
                session.add(job)
                session.commit()

        job.status = 'fallback_local'
        job.used_fallback_local = True
        job.result_json = json.dumps({'mode': 'local', 'reason': job.error or 'worker_failed'})
        job.updated_at = datetime.utcnow()
        session.add(job)
        session.commit()
        return job


worker_queue = WorkerQueue()
