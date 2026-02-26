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
    result_summary: str = ''


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
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Artifact(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    run_id: int
    kind: str
    path: str
    meta_json: str = '{}'
    created_at: datetime = Field(default_factory=datetime.utcnow)
