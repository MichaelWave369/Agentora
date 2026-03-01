from pathlib import Path
from urllib.parse import urlparse
import requests

from app.core.config import settings
from app.core.security import ensure_url_allowed
from .sandbox import run_python_sandboxed


def _run_dir(run_id: int) -> Path:
    root = Path(settings.agentora_file_write_root or 'server/data/artifacts')
    d = root / f'run_{run_id}'
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


def capsule_search(query: str, run_id: int | None = None, session=None) -> dict:
    if session is None:
        return {'ok': False, 'error': 'session required'}
    import hashlib
    from app.services.runtime.capsules import search_capsules_sync

    digest = hashlib.sha256(query.encode('utf-8')).digest()
    query_vector = [((b / 255.0) * 2 - 1) for b in digest[:32]]
    items = search_capsules_sync(session=session, query_vector=query_vector, run_id=run_id)
    return {'ok': True, 'query': query, 'items': items}


def http_fetch(url: str) -> dict:
    if not settings.agentora_enable_http_fetch:
        return {'ok': False, 'error': 'http_fetch disabled'}
    parsed = urlparse(url)
    host = parsed.hostname or ''
    if settings.http_allowlist and host not in settings.http_allowlist:
        return {'ok': False, 'error': f'host not allowed: {host}'}
    ensure_url_allowed(url)
    r = requests.get(url, timeout=10)
    return {'ok': True, 'status': r.status_code, 'text': r.text[:1000]}


def python_exec(python_code: str) -> dict:
    if not settings.agentora_enable_code_exec:
        return {'ok': False, 'error': 'sandbox disabled'}
    return run_python_sandboxed(python_code)
