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
    version: str = '0.2.0'
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
