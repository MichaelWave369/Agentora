from pydantic import BaseModel


class AgentIn(BaseModel):
    name: str
    model: str
    role: str
    system_prompt: str
    tools: list[str] = []
    memory_mode: str = 'none'


class TeamIn(BaseModel):
    name: str
    description: str = ''
    mode: str = 'sequential'
    yaml_text: str = ''
    agent_ids: list[int] = []


class RunIn(BaseModel):
    team_id: int
    prompt: str
    max_turns: int = 6
    max_seconds: int = 60
    token_budget: int = 3000
    consensus_threshold: int = 1
    reflection: bool = False


class WorkerIn(BaseModel):
    name: str
    url: str
    capabilities: list[str] = []


class WorkerHeartbeatIn(BaseModel):
    worker_id: int
    status: str = "idle"


class WorkerDispatchIn(BaseModel):
    job_type: str
    payload: dict = {}
    priority: int = 5
