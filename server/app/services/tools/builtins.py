from pathlib import Path
import requests

from app.core.config import settings
from app.core.security import ensure_url_allowed
from .sandbox import run_python_restricted


def _run_dir(run_id: int) -> Path:
    d = Path('server/data/artifacts') / f'run_{run_id}'
    d.mkdir(parents=True, exist_ok=True)
    return d


def notes_append(run_id: int, text: str) -> dict:
    p = _run_dir(run_id) / 'notes.md'
    with p.open('a', encoding='utf-8') as f:
        f.write(text + '\n')
    return {'ok': True, 'path': str(p)}


def local_files_write(run_id: int, path: str, content: str) -> dict:
    p = (_run_dir(run_id) / path).resolve()
    base = _run_dir(run_id).resolve()
    if not str(p).startswith(str(base)):
        return {'ok': False, 'error': 'path outside sandbox'}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding='utf-8')
    return {'ok': True, 'path': str(p)}


def local_files_read(run_id: int, path: str) -> dict:
    p = (_run_dir(run_id) / path).resolve()
    base = _run_dir(run_id).resolve()
    if not str(p).startswith(str(base)) or not p.exists():
        return {'ok': False, 'error': 'missing or blocked'}
    return {'ok': True, 'content': p.read_text(encoding='utf-8')}


def capsule_search(query: str) -> dict:
    return {'ok': False, 'message': 'capsule_search not configured', 'query': query}


def http_fetch(url: str) -> dict:
    if not settings.agentora_enable_http_fetch:
        return {'ok': False, 'error': 'http_fetch disabled'}
    ensure_url_allowed(url)
    r = requests.get(url, timeout=10)
    return {'ok': True, 'status': r.status_code, 'text': r.text[:1000]}


def code_exec(python_code: str) -> dict:
    if not settings.agentora_enable_code_exec:
        return {'ok': False, 'error': 'code_exec disabled'}
    return run_python_restricted(python_code)
