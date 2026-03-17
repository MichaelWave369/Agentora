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
    refresh_count: int = 0
    mission_score: int = 0
    confidence_level: str = 'low'
    completion_signal: str = 'unknown'
    result_quality_signal: str = 'low'
    writeback_readiness_signal: str = 'low'
    risk_signal: str = 'high'
    mission_snapshot_json: str = '{}'
    snapshot_hash: str = ''
    parent_run_id: int | None = None
    root_run_id: int | None = None
    lineage_depth: int = 0
    replay_source_snapshot_hash: str = ''
    replay_kind: str = ''
    provenance_note: str = ''
    fork_reason: str = ''
    immutable_origin_created_at: datetime | None = None
    branch_set_id: str = ''
    branch_label: str = ''
    branch_strategy: str = ''
    decision_status: str = 'undecided'
    shortlisted: bool = False
    eliminated: bool = False
    branch_order: int = 0
    decision_note: str = ''
    assigned_persona_id: str = ''
    assigned_persona_name: str = ''
    assigned_persona_role: str = ''
    persona_strategy_overlay: str = ''
    persona_assignment_reason: str = ''
    operator_override_status: str = 'none'
    operator_override_note: str = ''
    recommendation_state: str = 'pending'
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


class WatcherEventRecord(BaseModel):
    id: int
    run_id: int | None = None
    event_type: str
    status: str = ''
    latency_ms: float = 0.0
    detail_json: str = '{}'
    created_at: datetime


class AlertEventRecord(BaseModel):
    id: int
    run_id: int | None = None
    alert_type: str
    severity: str = 'info'
    delivery_status: str = 'logged'
    detail_json: str = '{}'
    created_at: datetime


class OperatorDecisionEventRecord(BaseModel):
    id: int
    run_id: int
    root_run_id: int
    created_at: datetime
    event_type: str
    actor_type: str = 'operator'
    previous_state_json: str = '{}'
    new_state_json: str = '{}'
    rationale: str = ''
    related_persona_id: str = ''
    related_strategy: str = ''
    metadata_json: str = '{}'


class ReplayDraftRequest(BaseModel):
    replay_kind: str = 'exact_replay'
    mission_title: str | None = None
    objective: str | None = None
    operator_intent: str | None = None
    acceptance_criteria: list[str] | None = None
    constraints: list[str] | None = None
    persona_id: str | None = None
    repo: str | None = None
    dry_run: bool = True
    provenance_note: str = ''
    fork_reason: str = ''


class ReplayLaunchRequest(BaseModel):
    dry_run: bool = True


class BranchDraftSpec(BaseModel):
    preset: str = 'exploratory_branch'
    branch_label: str | None = None
    objective: str | None = None
    constraints: list[str] | None = None
    persona_id: str | None = None
    fork_reason: str | None = None
    provenance_note: str | None = None
    launch: bool = False


class BranchSetCreateRequest(BaseModel):
    branch_set_id: str | None = None
    set_label: str = ''
    dry_run: bool = True
    auto_launch_selected: bool = False
    specs: list[BranchDraftSpec] = Field(default_factory=list)


class BranchSetCreateResponse(BaseModel):
    root_run_id: int
    branch_set_id: str
    created_drafts: list[OrchestrationRunRecord] = Field(default_factory=list)
    launched_runs: list[OrchestrationRunRecord] = Field(default_factory=list)


class BranchPortfolioBranch(BaseModel):
    run_id: int
    root_run_id: int | None = None
    branch_set_id: str = ''
    branch_label: str = ''
    branch_strategy: str = ''
    persona_id: str = ''
    assigned_persona_id: str = ''
    assigned_persona_name: str = ''
    assigned_persona_role: str = ''
    persona_strategy_overlay: str = ''
    objective_delta: str = ''
    status: str = ''
    mission_score: int = 0
    confidence_level: str = 'low'
    risk_signal: str = 'high'
    pr_present: bool = False
    writeback_status: str = 'not_written'
    shortlisted: bool = False
    eliminated: bool = False
    decision_status: str = 'undecided'
    operator_override_status: str = 'none'
    recommendation_state: str = 'pending'


class BranchPortfolioSummary(BaseModel):
    root_run_id: int
    branch_set_id: str | None = None
    branches: list[BranchPortfolioBranch] = Field(default_factory=list)
    ranking_summary: list[dict[str, Any]] = Field(default_factory=list)
    shortlist_suggestions: list[int] = Field(default_factory=list)
    elimination_suggestions: list[int] = Field(default_factory=list)
    interpretation_note: str = ''


class DecisionStateRequest(BaseModel):
    decision_note: str = ''


class PersonaBranchSpec(BaseModel):
    persona_id: str
    overlay: str = ''
    preset: str = 'exploratory_branch'
    branch_label: str | None = None
    objective: str | None = None
    constraints: list[str] | None = None
    launch: bool = False
    persona_assignment_reason: str = ''


class PersonaBranchSetCreateRequest(BaseModel):
    branch_set_id: str | None = None
    dry_run: bool = True
    auto_launch_selected: bool = False
    specs: list[PersonaBranchSpec] = Field(default_factory=list)


class PersonaBranchSetCreateResponse(BaseModel):
    root_run_id: int
    branch_set_id: str
    created_drafts: list[OrchestrationRunRecord] = Field(default_factory=list)
    launched_runs: list[OrchestrationRunRecord] = Field(default_factory=list)


class PersonaPortfolioBranch(BaseModel):
    run_id: int
    branch_label: str = ''
    branch_strategy: str = ''
    assigned_persona_id: str = ''
    assigned_persona_name: str = ''
    assigned_persona_role: str = ''
    persona_strategy_overlay: str = ''
    status: str = ''
    mission_score: int = 0
    confidence_level: str = 'low'
    risk_signal: str = 'high'
    pr_present: bool = False
    writeback_status: str = 'not_written'
    shortlisted: bool = False
    eliminated: bool = False
    operator_override_status: str = 'none'
    recommendation_state: str = 'pending'
    recommendation_explanation: dict[str, Any] = Field(default_factory=dict)


class PersonaPortfolioSummary(BaseModel):
    root_run_id: int
    branches: list[PersonaPortfolioBranch] = Field(default_factory=list)
    best_scoring_persona_branch: int | None = None
    lowest_risk_persona_branch: int | None = None
    persona_branches_with_prs: list[int] = Field(default_factory=list)
    persona_branches_with_successful_writeback: list[int] = Field(default_factory=list)
    persona_divergence_interpretation: str = ''
    recommended_next_persona_branch: int | None = None
    explanation_note: str = ''


class PortfolioDecisionRequest(BaseModel):
    decision: str = 'accept_recommendation'
    shortlisted: bool | None = None
    eliminated: bool | None = None
    note: str = ''


class PersonaPolicyCheckRequest(BaseModel):
    action: str = 'writeback'


class ApplyPolicyTemplateRequest(BaseModel):
    template_name: str


class LineageNode(BaseModel):
    id: int
    parent_run_id: int | None = None
    root_run_id: int | None = None
    lineage_depth: int = 0
    mission_title: str = ''
    status: str = ''
    replay_kind: str = ''


class LineageTreeResponse(BaseModel):
    root_run_id: int
    ancestry: list[LineageNode] = Field(default_factory=list)
    descendants: list[LineageNode] = Field(default_factory=list)
