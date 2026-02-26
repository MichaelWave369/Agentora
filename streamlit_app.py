import os
import sys
from pathlib import Path

import requests
from fastapi.testclient import TestClient

try:
    import streamlit as st
except Exception:  # pragma: no cover - fallback for test environments without streamlit
    class _NoopContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class _NoopStreamlit:
        def cache_resource(self, fn=None, **_kwargs):
            def _decorator(func):
                return func
            return _decorator(fn) if fn else _decorator

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

        def json(self, *_args, **_kwargs):
            return None

        def expander(self, *_args, **_kwargs):
            return _NoopContext()

    st = _NoopStreamlit()

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / 'server'
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app.main import create_app


@st.cache_resource
def embedded_client() -> TestClient:
    return TestClient(create_app())


def api_base() -> str | None:
    mode = os.getenv('AGENTORA_STREAMLIT_MODE', 'auto').lower()
    if mode == 'embedded':
        return None
    explicit = os.getenv('AGENTORA_API_URL', '').strip()
    if explicit:
        return explicit.rstrip('/')
    port = os.getenv('AGENTORA_PORT', '8088')
    return f'http://127.0.0.1:{port}'


def http_get(path: str):
    base = api_base()
    if not base:
        raise RuntimeError('embedded')
    return requests.get(f'{base}{path}', timeout=2)


def api_get(path: str) -> dict:
    mode = os.getenv('AGENTORA_STREAMLIT_MODE', 'auto').lower()
    if mode in ('auto', 'http'):
        try:
            response = http_get(path)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            if mode == 'http':
                raise
            st.warning(f'HTTP API unavailable; using embedded mode. ({exc})')

    client = embedded_client()
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def render_dashboard() -> None:
    st.title('Agentora Dashboard')
    st.caption('Mode: HTTP first with embedded fallback for Streamlit Cloud/local resilience.')

    for tab, path in {
        'Dashboard': '/api/health',
        'Templates': '/api/teams/templates',
        'Marketplace': '/api/marketplace/templates',
        'Runs': '/api/runs',
        'Analytics': '/api/analytics/overview',
        'Settings': '/api/integrations/status',
    }.items():
        with st.expander(tab, expanded=tab == 'Dashboard'):
            try:
                st.json(api_get(path))
            except Exception as exc:
                st.error(f'API unavailable: {exc}')


if __name__ == '__main__':
    render_dashboard()
