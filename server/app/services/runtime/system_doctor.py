from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib
import os
import shutil
import socket

import requests

from app.core.config import settings


@dataclass
class DiagnosticItem:
    key: str
    ok: bool
    severity: str
    detail: str
    fix_hint: str = ''

    def as_dict(self) -> dict:
        return {
            'key': self.key,
            'ok': self.ok,
            'severity': self.severity,
            'detail': self.detail,
            'fix_hint': self.fix_hint,
        }


def _can_import(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def run_doctor() -> dict:
    items: list[DiagnosticItem] = []
    items.append(
        DiagnosticItem(
            key='python',
            ok=True,
            severity='info',
            detail='python runtime available',
        )
    )
    items.append(
        DiagnosticItem('streamlit_import', _can_import('streamlit'), 'warn', 'streamlit import check', 'Install dependencies with pip install -r requirements.txt')
    )
    items.append(
        DiagnosticItem('fastapi_import', _can_import('fastapi'), 'warn', 'fastapi import check', 'Install dependencies with pip install -r server/requirements.txt')
    )
    node = shutil.which('node')
    npm = shutil.which('npm')
    items.append(DiagnosticItem('node', bool(node), 'warn', f'node found: {node or "missing"}', 'Install Node.js 18+ for web build support'))
    items.append(DiagnosticItem('npm', bool(npm), 'warn', f'npm found: {npm or "missing"}', 'Install npm with Node.js'))

    for root in settings.allowed_path_roots:
        p = Path(root)
        ok = p.exists() and p.is_dir() and p.is_absolute() or p.exists()
        writable = ok and p.exists() and p.is_dir() and os_access_write(p)
        items.append(DiagnosticItem(f'path_root:{root}', bool(writable), 'error', f'allowed root writable={writable}', 'Set AGENTORA_ALLOWED_PATH_ROOTS to writable folders'))

    db_dir = Path(settings.database_url.replace('sqlite:///', '', 1)).parent if settings.database_url.startswith('sqlite:///') else Path('.')
    items.append(DiagnosticItem('database_dir', os_access_write(db_dir), 'error', f'database directory writable={os_access_write(db_dir)}', 'Ensure database parent directory is writable'))

    ollama_ok = False
    ollama_detail = 'mock mode enabled'
    if not settings.agentora_use_mock_ollama:
        try:
            r = requests.get(f"{settings.ollama_url.rstrip('/')}/api/tags", timeout=3)
            ollama_ok = r.ok
            ollama_detail = f'ollama reachable status={r.status_code}'
        except Exception as exc:
            ollama_detail = f'ollama unavailable: {exc}'
    else:
        ollama_ok = True
    items.append(DiagnosticItem('ollama', ollama_ok, 'warn', ollama_detail, 'Start Ollama or enable AGENTORA_USE_MOCK_OLLAMA=true'))

    worker_urls = [u.strip() for u in settings.agentora_worker_urls.split(',') if u.strip()]
    for url in worker_urls:
        ok = False
        detail = 'unreachable'
        try:
            host = url.split('://', 1)[-1].split('/', 1)[0].split(':', 1)[0]
            socket.gethostbyname(host)
            ok = True
            detail = 'dns_resolves'
        except Exception as exc:
            detail = f'worker dns failed: {exc}'
        items.append(DiagnosticItem(f'worker:{url}', ok, 'warn', detail, 'Check worker URL and LAN reachability'))

    summary = 'ok'
    if any((not i.ok) and i.severity == 'error' for i in items):
        summary = 'error'
    elif any(not i.ok for i in items):
        summary = 'warn'

    return {
        'status': summary,
        'items': [i.as_dict() for i in items],
    }


def os_access_write(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / '.agentora_write_probe'
        probe.write_text('ok', encoding='utf-8')
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False
