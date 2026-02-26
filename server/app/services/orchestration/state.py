from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class RunState:
    run_id: int
    prompt: str
    mode: str
    max_turns: int
    max_seconds: int
    token_budget: int
    reflection: bool = False
    messages: list[dict] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)

    def add(self, role: str, content: str, agent_id: int | None = None, meta: dict | None = None):
        self.messages.append({'role': role, 'content': content, 'agent_id': agent_id, 'meta': meta or {}})

    def repeated(self, text: str) -> bool:
        hits = [m for m in self.messages if m['content'] == text]
        return len(hits) >= 2
