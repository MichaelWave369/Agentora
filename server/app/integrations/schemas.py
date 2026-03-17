from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PersonaSummary(BaseModel):
    id: str
    name: str
    role: str
    style: str = ''
    goals: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class MemorySnippet(BaseModel):
    id: str
    text: str
    source: str = ''
    score: float = 0.0
    timestamp: datetime


class CodingStylePreference(BaseModel):
    name: str
    detail: str = ''


class ArchitecturalPrinciple(BaseModel):
    name: str
    rationale: str = ''


class RiskFlag(BaseModel):
    name: str
    severity: str = 'medium'
    mitigation: str = ''


class SuccessCriterion(BaseModel):
    name: str
    metric: str = ''


class DispatchBrief(BaseModel):
    objective: str = ''
    scope: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)


class ContextPackRequest(BaseModel):
    persona_id: str
    task: str
    repo: str
    objective: str
    operator_intent: str = ''
    mission_title: str = ''
    limit: int = 5


class MissionContextPacket(BaseModel):
    session_id: str
    persona: PersonaSummary
    mission_title: str = ''
    mission_objective: str
    repo: str
    operator_intent: str = ''
    summary: str = ''
    memory_snippets: list[MemorySnippet] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    coding_style_preferences: list[CodingStylePreference] = Field(default_factory=list)
    architectural_principles: list[ArchitecturalPrinciple] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    dispatch_brief: DispatchBrief = Field(default_factory=DispatchBrief)
    generated_at: datetime


class MemoryWriteRequest(BaseModel):
    session_id: str
    source_system: str
    task_id: str
    summary: str
    details: str
    tags: list[str] = Field(default_factory=list)


class AgentCeptionLaunchRequest(BaseModel):
    mission_title: str = ''
    repo: str
    objective: str
    operator_intent: str = ''
    context_summary: str
    dispatch_brief: dict[str, Any] = Field(default_factory=dict)
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    persona_name: str
    persona_role: str
    persona_style: str = ''
    memory_snippets: list[str] = Field(default_factory=list)
    coding_style_preferences: list[dict[str, str]] = Field(default_factory=list)
    architectural_principles: list[dict[str, str]] = Field(default_factory=list)
    risk_flags: list[dict[str, str]] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    success_criteria: list[dict[str, str]] = Field(default_factory=list)
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


class AgentExecutionOutcome(BaseModel):
    job_id: str
    status: str
    phase: str = ''
    branch: str = ''
    pr_url: str = ''
    issue_urls: list[str] = Field(default_factory=list)
    artifact_urls: list[str] = Field(default_factory=list)
    summary: str = ''
    result_kind: str = 'status_update'
    completed_at: datetime | None = None
    raw_status_payload: dict[str, Any] = Field(default_factory=dict)


class MissionWritebackPayload(BaseModel):
    session_id: str
    source_system: str
    task_id: str
    repo: str
    objective: str
    outcome_status: str
    summary: str
    branch: str = ''
    pr_url: str = ''
    issue_urls: list[str] = Field(default_factory=list)
    artifact_urls: list[str] = Field(default_factory=list)
    recommended_followups: list[str] = Field(default_factory=list)
    operator_notes: str = ''
    tags: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class OrchestrationRunRecord(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    status: str
    persona_id: str
    repo: str
    objective: str
    mission_title: str = ''
    operator_intent: str = ''
    context_summary: str = ''
    dispatch_brief: str = ''
    acceptance_criteria_json: str = '[]'
    constraints_json: str = '[]'
    success_criteria_json: str = '[]'
    recommended_actions_json: str = '[]'
    phios_session_id: str = ''
    agentception_job_id: str = ''
    agentception_status: str = ''
    branch: str = ''
    pr_url: str = ''
    issue_urls_json: str = '[]'
    artifact_urls_json: str = '[]'
    summary: str = ''
    raw_payload_json: str = '{}'
    phios_packet_json: str = '{}'
    agentception_result_json: str = '{}'
    writeback_status: str = 'not_written'
    writeback_at: datetime | None = None
    writeback_error: str = ''
    last_outcome_hash: str = ''
    last_writeback_hash: str = ''
    last_writeback_attempt_at: datetime | None = None
    writeback_policy: str = 'manual'
    auto_writeback_enabled: bool = False
    watch_enabled: bool = True
    last_refreshed_at: datetime | None = None
    watch_error: str = ''
    error_message: str = ''


class SoftwareTaskRequest(BaseModel):
    persona_id: str
    repo: str
    mission_title: str = ''
    objective: str
    operator_intent: str = ''
    acceptance_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    dry_run: bool = False


class WritebackRequest(BaseModel):
    operator_notes: str = ''
    tags: list[str] = Field(default_factory=list)


class LaunchMissionRequest(SoftwareTaskRequest):
    prepared_packet: MissionContextPacket | None = None


class PrepareMissionRequest(BaseModel):
    persona_id: str
    repo: str
    mission_title: str = ''
    objective: str
    operator_intent: str = ''
    constraints: list[str] = Field(default_factory=list)
