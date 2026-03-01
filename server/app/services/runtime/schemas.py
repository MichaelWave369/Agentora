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


class CapsuleSearchRequest(BaseModel):
    query: str
    top_k: int = 6
    run_id: int | None = None


class CapsuleSearchResult(BaseModel):
    capsule_id: int
    score: float
    text: str
    source: str = ''
