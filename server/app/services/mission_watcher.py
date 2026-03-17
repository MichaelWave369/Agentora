import threading
import time

from sqlmodel import Session

from app.core.config import settings
from app.db import engine
from app.models import IntegrationRun
from app.services.integration_orchestrator import IntegrationOrchestrator


class MissionWatcher:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._in_progress: set[int] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if not settings.agentora_missions_watcher_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='agentora-missions-watcher', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _refresh_one(self, run_id: int) -> None:
        with self._lock:
            if run_id in self._in_progress:
                return
            self._in_progress.add(run_id)
        try:
            with Session(engine) as session:
                orchestrator = IntegrationOrchestrator(session)
                orchestrator.refresh_run(run_id, source='watcher')
        except Exception:
            with Session(engine) as session:
                row = session.get(IntegrationRun, run_id)
                if row:
                    row.watch_error = 'watch refresh failed'
                    session.add(row)
                    session.commit()
        finally:
            with self._lock:
                self._in_progress.discard(run_id)

    def run_once(self) -> int:
        with Session(engine) as session:
            orchestrator = IntegrationOrchestrator(session)
            rows = orchestrator.list_active_runs_for_watcher(settings.agentora_missions_watcher_max_active_runs)
            run_ids = [r.id for r in rows if r.id is not None]
        for run_id in run_ids:
            self._refresh_one(run_id)
        return len(run_ids)

    def _loop(self) -> None:
        interval = max(2, settings.agentora_missions_watcher_interval_seconds)
        while not self._stop.is_set():
            self.run_once()
            self._stop.wait(interval)


mission_watcher = MissionWatcher()
