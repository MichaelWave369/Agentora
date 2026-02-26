import os
import sys
from pathlib import Path

import requests

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

        def info(self, *_args, **_kwargs):
            return None

        def json(self, *_args, **_kwargs):
            return None

        def stop(self):
            raise RuntimeError('streamlit stop called')

        def expander(self, *_args, **_kwargs):
            return _NoopContext()

    st = _NoopStreamlit()

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / 'server'
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))


@st.cache_resource
def embedded_client():
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:
        st.error(
            'Embedded mode requires FastAPI installed. Ensure requirements.txt includes -r server/requirements.txt'
        )
        st.stop()
        raise RuntimeError('embedded_mode_unavailable') from exc

    from app.main import create_app

    return TestClient(create_app())


def api_base() -> str:
    explicit = os.getenv('AGENTORA_API_URL', '').strip()
    if explicit:
        return explicit.rstrip('/')
    port = os.getenv('AGENTORA_PORT', '8088')
    return f'http://127.0.0.1:{port}'


def http_get(path: str):
    return requests.get(f'{api_base()}{path}', timeout=2)


def _embedded_get(path: str) -> dict:
    client = embedded_client()
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def api_get(path: str) -> dict:
    mode = os.getenv('AGENTORA_STREAMLIT_MODE', 'auto').lower()

    if mode == 'http':
        response = http_get(path)
        response.raise_for_status()
        return response.json()

    if mode == 'embedded':
        return _embedded_get(path)

    if os.getenv('AGENTORA_API_URL', '').strip():
        try:
            response = http_get(path)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            st.warning(f'HTTP API unavailable; falling back to embedded mode. ({exc})')

    try:
        return _embedded_get(path)
    except Exception as exc:
        st.error(
            'Embedded mode is unavailable. Configure AGENTORA_API_URL for HTTP mode or install backend deps via requirements.txt.'
        )
        raise RuntimeError('No API mode available') from exc


def render_dashboard() -> None:
    st.title('Agentora Dashboard')
    st.caption('Mode: auto/http/embedded via AGENTORA_STREAMLIT_MODE.')

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
