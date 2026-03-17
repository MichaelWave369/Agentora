from datetime import datetime

from pydantic import BaseModel, Field


class PersonaSummary(BaseModel):
    id: str
    name: str
    role: str
    style: str
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class MemorySnippet(BaseModel):
    id: str
    text: str
    source: str
    score: float
    timestamp: datetime


class ContextPackRequest(BaseModel):
    persona_id: str
    task: str
    repo: str
    objective: str
    limit: int = 5


class ContextPackResponse(BaseModel):
    persona: PersonaSummary
    session_id: str
    summary: str
    memory_snippets: list[MemorySnippet] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)


class MemoryWriteRequest(BaseModel):
    session_id: str
    source_system: str
    task_id: str
    summary: str
    details: str
    tags: list[str] = Field(default_factory=list)


class AgentCeptionLaunchRequest(BaseModel):
    title: str
    repo: str
    objective: str
    context_summary: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    persona_name: str
    persona_role: str
    memory_snippets: list[str] = Field(default_factory=list)
    dry_run: bool = False


class AgentCeptionLaunchResponse(BaseModel):
    job_id: str
    status: str
    message: str
    launch_url: str = ''


class AgentCeptionJobStatus(BaseModel):
    job_id: str
    status: str
    phase: str = ''
    branch: str = ''
    pr_url: str = ''
    issue_urls: list[str] = Field(default_factory=list)
    artifact_urls: list[str] = Field(default_factory=list)
    updated_at: datetime
    summary: str = ''


class OrchestrationRunRecord(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    status: str
    persona_id: str
    repo: str
    objective: str
    phios_session_id: str = ''
    agentception_job_id: str = ''
    agentception_status: str = ''
    pr_url: str = ''
    summary: str = ''
    raw_payload_json: str = '{}'
    error_message: str = ''


class SoftwareTaskRequest(BaseModel):
    persona_id: str
    repo: str
    objective: str
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    dry_run: bool = False


class WritebackRequest(BaseModel):
    summary: str = ''
    details: str = ''
    tags: list[str] = Field(default_factory=list)
