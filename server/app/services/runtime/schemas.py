from __future__ import annotations

from pydantic import BaseModel, Field


class ToolInvocation(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)


class RuntimeAction(BaseModel):
    thought: str = ''
    need_memory: bool = False
    memory_queries: list[str] = Field(default_factory=list)
    tool_calls: list[ToolInvocation] = Field(default_factory=list)
    final: str = ''
    handoff: str = ''
    done: bool = False


class RuntimeResult(BaseModel):
    final_text: str
    tool_calls_count: int = 0
    stop_reason: str = 'completed'
    warnings: list[str] = Field(default_factory=list)
    worker_used: bool = False
    model_used: list[str] = Field(default_factory=list)


class CapsuleSearchRequest(BaseModel):
    query: str
    top_k: int = 6
    run_id: int | None = None
    source_weight: dict[str, float] = Field(default_factory=dict)


class CapsuleSearchResult(BaseModel):
    capsule_id: int
    score: float
    text: str
    source: str = ''
    is_summary: bool = False
    created_at: str = ''
