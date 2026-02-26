import os
import sys
from pathlib import Path

import requests

try:
    import streamlit as st
except Exception:
    class _NoopContext:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
    class _NoopStreamlit:
        def cache_resource(self, fn=None, **_kwargs):
            def _decorator(func): return func
            return _decorator(fn) if fn else _decorator
        def title(self,*_a,**_k): return None
        def caption(self,*_a,**_k): return None
        def warning(self,*_a,**_k): return None
        def error(self,*_a,**_k): return None
        def info(self,*_a,**_k): return None
        def success(self,*_a,**_k): return None
        def json(self,*_a,**_k): return None
        def tabs(self, labels): return [_NoopContext() for _ in labels]
        def expander(self,*_a,**_k): return _NoopContext()
        def stop(self): raise RuntimeError('streamlit stop called')
    st = _NoopStreamlit()

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / 'server'
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

ACTIVE_MODE = 'embedded'

@st.cache_resource
def embedded_client():
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:
        st.error('Embedded mode requires FastAPI installed. Ensure requirements.txt includes -r server/requirements.txt')
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
    global ACTIVE_MODE
    mode = os.getenv('AGENTORA_STREAMLIT_MODE', 'auto').lower()
    if mode == 'http':
        ACTIVE_MODE = 'http'
        r = http_get(path)
        r.raise_for_status()
        return r.json()
    if mode == 'embedded':
        ACTIVE_MODE = 'embedded'
        return _embedded_get(path)
    try:
        r = http_get(path)
        r.raise_for_status()
        ACTIVE_MODE = 'http'
        return r.json()
    except Exception:
        ACTIVE_MODE = 'embedded'
        return _embedded_get(path)


def panel(title: str, path: str):
    with st.expander(title, expanded=title == 'Health'):
        try:
            st.json(api_get(path))
        except Exception as exc:
            st.error(f'API unavailable: {exc}')


def render_dashboard() -> None:
    st.title('Agentora v0.4 — Legacy & Evolution')
    st.info(f'API Mode: {ACTIVE_MODE.upper()} | Local-first party edition')
    tabs = st.tabs(['Studio', 'Band', 'Arena', 'Gathering', 'Legacy', 'Core'])
    with tabs[0]:
        panel('Personas', '/api/studio/personas')
    with tabs[1]:
        panel('Marketplace', '/api/marketplace/templates')
    with tabs[2]:
        panel('Leaderboard', '/api/arena/leaderboard')
    with tabs[3]:
        panel('LAN Discover', '/api/gathering/discover')
        panel('Gathering Templates', '/api/gathering/templates')
    with tabs[4]:
        panel('Legacy Souls', '/api/legacy/souls')
        panel('Legacy Tree', '/api/legacy/tree')
    with tabs[5]:
        panel('Health', '/api/health')
        panel('Runs', '/api/runs')


if __name__ == '__main__':
    render_dashboard()
