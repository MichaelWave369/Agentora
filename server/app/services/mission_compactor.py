import threading

from sqlmodel import Session

from app.core.config import settings
from app.db import engine
from app.services.integration_orchestrator import IntegrationOrchestrator


class MissionCompactor:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        if not settings.agentora_missions_compaction_enabled:
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name='agentora-missions-compactor', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def run_once(self) -> dict:
        with Session(engine) as session:
            return IntegrationOrchestrator(session).compact_events()

    def _loop(self) -> None:
        interval = max(30, settings.agentora_missions_compaction_interval_seconds)
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:
                pass
            self._stop.wait(interval)


mission_compactor = MissionCompactor()
