import inspect
from dataclasses import dataclass
from typing import Callable, Any

from . import builtins


@dataclass
class ToolSpec:
    name: str
    schema: dict
    permission: str
    fn: Callable[..., Any]


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {
            'notes_append': ToolSpec('notes_append', {'run_id': 'int', 'text': 'string'}, 'artifact:write', builtins.notes_append),
            'local_files_write': ToolSpec('local_files_write', {'run_id': 'int', 'path': 'string', 'content': 'string'}, 'artifact:write', builtins.local_files_write),
            'local_files_read': ToolSpec('local_files_read', {'run_id': 'int', 'path': 'string'}, 'artifact:read', builtins.local_files_read),
            'capsule_search': ToolSpec('capsule_search', {'query': 'string', 'run_id': 'int'}, 'memory:read', builtins.capsule_search),
            'http_fetch': ToolSpec('http_fetch', {'url': 'string'}, 'network:http', builtins.http_fetch),
            'python_exec': ToolSpec('python_exec', {'python_code': 'string'}, 'sandbox:exec', builtins.python_exec),
        }

    def list(self) -> list[dict]:
        return [{'name': t.name, 'schema': t.schema, 'permission': t.permission} for t in self._tools.values()]

    def call(self, name: str, allowed: list, **kwargs):
        if name not in self._tools:
            return {'ok': False, 'error': 'unknown tool'}
        if name not in allowed:
            return {'ok': False, 'error': 'tool not allowed'}
        fn = self._tools[name].fn
        sig = inspect.signature(fn)
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        call_kwargs = kwargs if accepts_kwargs else {k: v for k, v in kwargs.items() if k in sig.parameters}
        return fn(**call_kwargs)


registry = ToolRegistry()
