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



class MemoryMaintenanceIn(BaseModel):
    run_id: int | None = None
    try_worker: bool = True


class CapsuleLayerUpdateIn(BaseModel):
    reason: str = 'manual'



class MemoryFeedbackIn(BaseModel):
    run_id: int
    retrieved_capsule_ids: list[int] = []
    used_capsule_ids: list[int] = []
    helped_final_answer: bool = False
    helped_tool_execution: bool = False



class AgentCapabilityIn(BaseModel):
    preferred_model_role: str = 'chat'
    allowed_tools: list[str] = []
    max_tool_steps: int = 4
    can_critique: bool = False
    can_verify: bool = False
    can_delegate: bool = True
    can_use_workers: bool = True
    memory_scope: str = 'project'
    preferred_team_mode: str = 'careful'
    confidence_weight: float = 0.5


class TeamPlanPreviewIn(BaseModel):
    prompt: str
    mode: str = 'careful'


class TeamPlanRequestIn(BaseModel):
    run_id: int
    prompt: str
    mode: str = 'careful'
