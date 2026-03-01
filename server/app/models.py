from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Agent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    model: str
    role: str
    system_prompt: str
    tools_json: str = '[]'
    memory_mode: str = 'none'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Team(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ''
    mode: str = 'sequential'
    yaml_text: str = ''
    version: str = '0.3.0'
    marketplace_id: str = ''
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TeamAgent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int
    agent_id: int
    position: int = 0
    params_json: str = '{}'


class Run(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int
    status: str = 'pending'
    mode: str = 'sequential'
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    max_turns: int = 8
    max_seconds: int = 90
    token_budget: int = 4000
    consensus_threshold: int = 1
    result_summary: str = ''
    paused_reason: str = ''


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    agent_id_nullable: Optional[int] = None
    role: str
    content: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    meta_json: str = '{}'


class MemoryItem(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: int
    key: str
    value: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ToolCall(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    agent_id: int
    tool_name: str
    args_json: str = '{}'
    result_json: str = '{}'
    approved: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Artifact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    kind: str
    path: str
    meta_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class InstalledTemplate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    version: str
    description: str = ''
    tags_json: str = '[]'
    yaml_path: str
    source: str = 'marketplace'
    installed_at: datetime = Field(default_factory=datetime.utcnow)


class Attachment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    filename: str
    mime: str
    sha256: str
    path: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    meta_json: str = '{}'


class AttachmentExtract(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    attachment_id: int
    text: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ModelCapability(SQLModel, table=True):
    model_name: str = Field(primary_key=True)
    can_vision: bool = False
    can_tools: bool = True
    notes: str = ''


class RunMetric(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    agent_id: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0
    tool_calls: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)




class Capsule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    attachment_id: Optional[int] = None
    source: str = ''
    chunk_index: int = 0
    text: str
    tags_json: str = '[]'
    is_summary: bool = False
    memory_layer: str = 'L1_SHORT'
    source_type: str = 'capsule'
    project_key: str = ''
    session_key: str = ''
    archive_status: str = 'active'
    decay_class: str = 'short'
    confidence: float = 0.5
    consolidation_score: float = 0.5
    trust_score: float = 0.5
    retrieval_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    recency_score: float = 1.0
    contradiction_flag: bool = False
    drift_score: float = 0.0
    helped_final_answer_score: float = 0.0
    duplicate_cluster_id: Optional[int] = None
    duplicate_score: float = 0.0
    retrieved_and_used_count: int = 0
    retrieved_but_unused_count: int = 0
    created_from_run_id: Optional[int] = None
    parent_capsule_id: Optional[int] = None
    lineage_root_id: Optional[int] = None
    last_accessed_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryLayer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ''
    priority: int = 0
    default_weight: float = 1.0
    active_by_default: bool = True
    max_contexts: int = 4
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryCapsuleState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    capsule_id: int
    layer: str = 'L1_SHORT'
    status: str = 'active'
    confidence: float = 0.5
    consolidation_score: float = 0.5
    trust_score: float = 0.5
    retrieval_count: int = 0
    usage_count: int = 0
    last_accessed_at: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryEdge(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    from_capsule_id: int
    to_capsule_id: int
    edge_type: str = 'semantic'
    weight: float = 0.5
    confidence: float = 0.5
    trust_score: float = 0.5
    usage_count: int = 0
    last_reinforced_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemorySummary(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    summary_capsule_id: int
    source_group_key: str = ''
    member_capsule_ids_json: str = '[]'
    detail_level: str = 'project'
    refreshed_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ContextActivation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    capsule_id: int
    layer: str
    query: str
    score: float = 0.0
    reason_json: str = '{}'
    admitted: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryMaintenanceJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: Optional[int] = None
    job_type: str
    status: str = 'queued'
    details_json: str = '{}'
    used_worker: bool = False
    error: str = ''
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)




class MemoryConflict(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    left_capsule_id: int
    right_capsule_id: int
    conflict_type: str = 'contradiction'
    conflict_score: float = 0.0
    status: str = 'open'
    detail_json: str = '{}'
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DuplicateCluster(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hash_key: str
    canonical_capsule_id: int
    member_capsule_ids_json: str = '[]'
    cluster_size: int = 1
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class MemoryUsefulnessMetric(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    capsule_id: int
    retrieved_count: int = 0
    retrieved_and_used_count: int = 0
    retrieved_but_unused_count: int = 0
    helped_final_answer_score: float = 0.0
    helped_tool_execution_score: float = 0.0
    user_confirmed_useful: bool = False
    contradiction_penalty: float = 0.0
    stale_penalty: float = 0.0
    confidence_gain: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)

class CapsuleEmbedding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    capsule_id: int
    vector_json: str = '[]'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkerNode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    url: str
    capabilities_json: str = '[]'
    status: str = 'idle'
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow)


class WorkerJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    job_type: str
    payload_json: str = '{}'
    priority: int = 5
    status: str = 'queued'
    retries: int = 0
    max_retries: int = 0
    worker_node_id: Optional[int] = None
    used_fallback_local: bool = False
    result_json: str = '{}'
    error: str = ''
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RunTrace(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    agent_id: int = 0
    event_type: str
    payload_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class TemplateUsage(SQLModel, table=True):
    template_id: int
    runs_count: int = 0
    last_used_at: datetime = Field(default_factory=datetime.utcnow)
    id: Optional[int] = Field(default=None, primary_key=True)


class IntegrationSetting(SQLModel, table=True):
    name: str = Field(primary_key=True)
    enabled: bool = False
    config_json: str = '{}'


class VoiceSetting(SQLModel, table=True):
    id: Optional[int] = Field(default=1, primary_key=True)
    voice_enabled: bool = False
    whisper_cpp_path: str = ''
    piper_path: str = ''
    piper_voice_model_path: str = ''


class VocalPersona(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    style: str
    tts_voice_path: str = ''
    prompt_style: str = ''
    default_effects_json: str = '{}'


class SongJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int = 0
    team_id: int = 0
    status: str = 'pending'
    lyrics_json: str = '{}'
    waveform_json: str = '[]'
    master_path: str = ''
    stems_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BandTrackJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    team_id: int = 0
    status: str = 'pending'
    plan_json: str = '{}'
    lyrics_json: str = '{}'
    master_path: str = ''
    stems_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ArenaMatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    mode: str = 'single'
    topic: str
    status: str = 'running'
    transcript_json: str = '[]'
    report_md: str = ''
    scoreboard_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ArenaTournament(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = 'running'
    topics_json: str = '[]'
    bracket_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ArenaVote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: int
    agent_id: int
    score: int
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GatheringSession(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    room_code: str
    host_name: str
    mode: str = 'studio'
    status: str = 'open'
    invite_code: str = ''
    participants_json: str = '[]'
    waveform_json: str = '[]'
    memories_json: str = '[]'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GatheringEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int
    event_type: str
    payload_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)




class TeamPlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    goal: str
    mode: str = 'careful'
    status: str = 'active'
    confidence: float = 0.6
    urgency: float = 0.5
    priority: float = 0.5
    revision: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TeamSubgoal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int
    run_id: int
    parent_subgoal_id: Optional[int] = None
    title: str
    detail: str = ''
    assigned_agent_id: Optional[int] = None
    assigned_agent_role: str = ''
    dependency_subgoal_ids_json: str = '[]'
    status: str = 'pending'
    needs_worker: bool = False
    deliverable_type: str = 'answer'
    confidence: float = 0.5
    urgency: float = 0.5
    priority: float = 0.5
    max_steps: int = 3
    output_text: str = ''
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentHandoff(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    from_agent_id: int
    to_agent_id: int
    reason: str
    context_json: str = '{}'
    expected_output: str = 'answer'
    allow_tools: bool = True
    allow_memory: bool = True
    max_steps: int = 3
    status: str = 'open'
    deadline_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AgentCapabilityProfile(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    agent_id: int
    preferred_model_role: str = 'chat'
    allowed_tools_json: str = '[]'
    max_tool_steps: int = 4
    can_critique: bool = False
    can_verify: bool = False
    can_delegate: bool = True
    can_use_workers: bool = True
    memory_scope: str = 'project'
    preferred_team_mode: str = 'careful'
    confidence_weight: float = 0.5
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CollaborationMetric(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    handoff_success_rate: float = 1.0
    critique_usefulness_rate: float = 0.0
    worker_route_success_rate: float = 1.0
    final_synthesis_completeness: float = 0.0
    plan_execution_consistency: float = 1.0
    no_progress_terminations: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)



class PolicyRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    action_class: str = 'desktop'
    tool_name: str = ''
    agent_role: str = ''
    path_scope: str = ''
    domain_scope: str = ''
    approval_level: str = 'ask_once'
    worker_eligible: bool = False
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ActionRequest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    agent_id: int = 0
    subgoal_id: Optional[int] = None
    action_class: str = 'desktop'
    tool_name: str
    params_json: str = '{}'
    policy_rule_id: Optional[int] = None
    policy_decision: str = 'ask_once'
    status: str = 'pending'
    requires_approval: bool = True
    requested_worker: bool = False
    requested_at: datetime = Field(default_factory=datetime.utcnow)
    decided_at: Optional[datetime] = None


class ActionApproval(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    action_request_id: int
    decision: str = 'pending'
    decided_by: str = 'user'
    reason: str = ''
    decided_at: datetime = Field(default_factory=datetime.utcnow)


class ActionExecution(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    action_request_id: int
    run_id: int
    status: str = 'queued'
    execution_mode: str = 'local'
    worker_job_id: Optional[int] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    result_json: str = '{}'
    error: str = ''


class ActionArtifact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    action_execution_id: int
    kind: str = 'text'
    path: str = ''
    content_preview: str = ''
    meta_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Workflow(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    description: str = ''
    params_schema_json: str = '{}'
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_id: int
    position: int = 0
    step_type: str = 'desktop'
    tool_name: str
    params_json: str = '{}'
    requires_approval: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_id: int
    run_id: int = 0
    status: str = 'running'
    input_json: str = '{}'
    output_json: str = '{}'
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


class OperatorRun(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    workflow_id: Optional[int] = None
    run_id: int = 0
    mode: str = 'stepwise'
    status: str = 'running'
    requested_by: str = 'user'
    worker_mode: str = 'auto'
    summary: str = ''
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


class OperatorStep(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    operator_run_id: int
    workflow_step_id: Optional[int] = None
    position: int = 0
    action_request_id: Optional[int] = None
    status: str = 'queued'
    retries: int = 0
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    result_json: str = '{}'
    error: str = ''


class ApprovalDecisionLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    action_request_id: int
    decision: str = 'pending'
    reason: str = ''
    scope_preview: str = ''
    reusable: bool = False
    decided_by: str = 'user'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BootstrapState(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    version: str = '0.9.7'
    doctor_status: str = 'unknown'
    report_json: str = '{}'
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class CosmosWorld(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    seed_prompt: str
    status: str = 'active'
    warmth: int = 60
    map_json: str = '[]'
    rules_json: str = '{}'
    history_json: str = '[]'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CosmosTimeline(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    world_id: int
    parent_timeline_id: int = 0
    title: str
    branch_prompt: str = ''
    diff_json: str = '{}'
    status: str = 'active'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OpenCosmosShare(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    world_id: int
    package_name: str
    visibility: str = 'private'
    wisdom_mode: str = 'anonymized'
    manifest_json: str = '{}'
    contributors_json: str = '[]'
    revoked: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class OpenCosmosMerge(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    world_id: int
    source_package: str
    decisions_json: str = '{}'
    conflicts_json: str = '[]'
    status: str = 'merged'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GardenBed(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    cosmos_world_id: int
    plant_name: str
    season: str = 'Spring'
    growth: int = 0
    gardener_role: str = 'Waterer'
    memories_json: str = '[]'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GardenHarvest(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    garden_bed_id: int
    harvest_type: str = 'wisdom'
    payload_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorldGardenNode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    source_kind: str = 'cosmos'
    source_id: int = 0
    title: str
    lat: float = 0.0
    lon: float = 0.0
    glow: int = 30
    visibility: str = 'private'
    credits_json: str = '[]'
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorldGardenEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    event_type: str = 'bloom'
    payload_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)
