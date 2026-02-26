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
            def _decorator(func):
                return func
            return _decorator(fn) if fn else _decorator
        def title(self, *_a, **_k): return None
        def caption(self, *_a, **_k): return None
        def warning(self, *_a, **_k): return None
        def error(self, *_a, **_k): return None
        def info(self, *_a, **_k): return None
        def success(self, *_a, **_k): return None
        def json(self, *_a, **_k): return None
        def markdown(self, *_a, **_k): return None
        def subheader(self, *_a, **_k): return None
        def code(self, *_a, **_k): return None
        def tabs(self, labels): return [_NoopContext() for _ in labels]
        def expander(self, *_a, **_k): return _NoopContext()
        def columns(self, n): return [_NoopContext() for _ in range(n)]
        def sidebar(self): return self
        def selectbox(self, *_a, **_k): return ''
        def text_input(self, *_a, **_k): return ''
        def text_area(self, *_a, **_k): return ''
        def slider(self, *_a, **_k): return 60
        def button(self, *_a, **_k): return False
        def checkbox(self, *_a, **_k): return False
        def stop(self): raise RuntimeError('streamlit stop called')
        def set_page_config(self, *_a, **_k): return None
        @property
        def session_state(self): return {}
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
    return requests.get(f'{api_base()}{path}', timeout=3)


def http_post(path: str, payload: dict):
    return requests.post(f'{api_base()}{path}', json=payload, timeout=5)


def _embedded_get(path: str) -> dict:
    response = embedded_client().get(path)
    response.raise_for_status()
    return response.json()


def _embedded_post(path: str, payload: dict) -> dict:
    response = embedded_client().post(path, json=payload)
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


def api_post(path: str, payload: dict) -> dict:
    global ACTIVE_MODE
    mode = os.getenv('AGENTORA_STREAMLIT_MODE', 'auto').lower()
    if mode == 'http':
        ACTIVE_MODE = 'http'
        r = http_post(path, payload)
        r.raise_for_status()
        return r.json()
    if mode == 'embedded':
        ACTIVE_MODE = 'embedded'
        return _embedded_post(path, payload)
    try:
        r = http_post(path, payload)
        r.raise_for_status()
        ACTIVE_MODE = 'http'
        return r.json()
    except Exception:
        ACTIVE_MODE = 'embedded'
        return _embedded_post(path, payload)


def _panel_json(title: str, path: str):
    with st.expander(title, expanded=False):
        try:
            st.json(api_get(path))
        except Exception as exc:
            st.error(f'API unavailable: {exc}')


def _theme_css():
    st.markdown(
        """
<style>
.stApp {background: radial-gradient(circle at top, #1e1b4b 0%, #07090d 55%, #05070b 100%); color: #e2e8f0;}
.block-container {padding-top: 1rem;}
.agentora-card {border:1px solid #334155; border-radius:12px; padding:12px; background:#0f172a90; margin-bottom:12px;}
.agentora-pill {display:inline-block; padding:4px 8px; border-radius:999px; border:1px solid #22d3ee; margin-right:6px;}
</style>
""",
        unsafe_allow_html=True,
    )


def _dashboard_page():
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("<div class='agentora-card'><h4>Health</h4></div>", unsafe_allow_html=True)
        st.json(api_get('/api/health'))
    with col2:
        st.markdown("<div class='agentora-card'><h4>Runs</h4></div>", unsafe_allow_html=True)
        st.json(api_get('/api/runs'))
    with col3:
        st.markdown("<div class='agentora-card'><h4>Marketplace</h4></div>", unsafe_allow_html=True)
        st.json(api_get('/api/marketplace/templates'))


def _studio_page():
    st.subheader('Studio')
    _panel_json('Personas', '/api/studio/personas')


def _band_page():
    st.subheader('Band')
    _panel_json('Band templates / market', '/api/marketplace/templates')


def _arena_page():
    st.subheader('Arena')
    _panel_json('Leaderboard', '/api/arena/leaderboard')


def _gathering_page():
    st.subheader('Gathering')
    _panel_json('LAN Discover', '/api/gathering/discover')
    _panel_json('Gathering Templates', '/api/gathering/templates')


def _legacy_page():
    st.subheader('Legacy')
    _panel_json('Legacy Souls', '/api/legacy/souls')
    _panel_json('Legacy Tree', '/api/legacy/tree')


def _cosmos_page():
    st.subheader('Cosmos')
    c1, c2 = st.columns(2)
    with c1:
        world_name = st.text_input('New cosmos name', value='Family Cosmos v0.7')
        seed = st.text_area('Seed', value='A shared story of compassion and courage')
        warmth = st.slider('Warmth', 0, 100, 70)
        if st.button('Create New Cosmos'):
            st.success(api_post('/api/cosmos/worlds', {'name': world_name, 'seed_prompt': seed, 'warmth': warmth}))
    with c2:
        _panel_json('Cosmos Worlds', '/api/cosmos/worlds')
        _panel_json('Eternal Archive', '/api/cosmos/archive')


def _open_cosmos_page():
    st.subheader('Open Cosmos')
    worlds = api_get('/api/cosmos/worlds').get('items', [])
    world_ids = [w['id'] for w in worlds]

    st.markdown("<div class='agentora-card'><h4>Safe Sharing & Merge</h4></div>", unsafe_allow_html=True)
    share_world = st.selectbox('Cosmos to share', options=world_ids, index=0 if world_ids else None)
    visibility = st.selectbox('Privacy mode', ['private', 'anonymized', 'public_with_credits'])
    if st.button('Share Cosmos (.agentora)') and share_world:
        st.success(api_post('/api/open-cosmos/share', {'world_id': share_world, 'visibility': visibility, 'wisdom_mode': 'anonymized'}))

    package_name = st.text_input('Import package name', value='')
    if st.button('Import & Merge') and package_name:
        st.success(api_post('/api/open-cosmos/import', {'package_name': package_name, 'keep_timelines': []}))

    st.markdown("<div class='agentora-card'><h4>Living Archive</h4></div>", unsafe_allow_html=True)
    question = st.text_input('Ask the living archive', value='What have other families learned about raising kind children?')
    if st.button('Query Archive'):
        st.json(api_post('/api/open-cosmos/archive/query', {'question': question}))

    st.markdown("<div class='agentora-card'><h4>Cross-Cosmos Visitation & Synthesis</h4></div>", unsafe_allow_html=True)
    w1 = st.selectbox('From cosmos', options=world_ids, key='visit_from', index=0 if world_ids else None)
    w2 = st.selectbox('To cosmos', options=world_ids, key='visit_to', index=(1 if len(world_ids) > 1 else 0) if world_ids else None)
    if st.button('Wisdom Exchange') and w1 and w2:
        st.balloons()
        st.json(api_post('/api/open-cosmos/exchange', {'world_a': w1, 'world_b': w2}))

    if st.button('Grand Synthesis (Meta-Cosmos)') and world_ids:
        st.success(api_post('/api/open-cosmos/synthesis', {'world_ids': world_ids, 'title': 'Meta Cosmos v0.7'}))

    if st.button('Forecast Values 2050') and world_ids:
        st.json(api_post('/api/open-cosmos/forecast', {'world_ids': world_ids}))

    st.markdown("<div class='agentora-card'><h4>Community Spotlight</h4></div>", unsafe_allow_html=True)
    st.json(api_get('/api/open-cosmos/spotlight'))


def render_dashboard() -> None:
    st.set_page_config(page_title='Agentora v0.7', layout='wide', initial_sidebar_state='expanded')
    _theme_css()
    st.title('Agentora v0.7 — Wisdom Eternal & The Living Archive')
    st.caption('Primary Streamlit experience • local-first • private by default')
    st.info(f'API Mode: {ACTIVE_MODE.upper()}')

    page = st.sidebar.radio(
        'Navigate',
        ['Dashboard', 'Studio', 'Band', 'Arena', 'Gathering', 'Legacy', 'Cosmos', 'Open Cosmos', 'Core'],
    )
    st.sidebar.markdown("<span class='agentora-pill'>NO CLOUD REQUIRED</span>", unsafe_allow_html=True)

    if page == 'Dashboard':
        _dashboard_page()
    elif page == 'Studio':
        _studio_page()
    elif page == 'Band':
        _band_page()
    elif page == 'Arena':
        _arena_page()
    elif page == 'Gathering':
        _gathering_page()
    elif page == 'Legacy':
        _legacy_page()
    elif page == 'Cosmos':
        _cosmos_page()
    elif page == 'Open Cosmos':
        _open_cosmos_page()
    else:
        _panel_json('Health', '/api/health')
        _panel_json('Runs', '/api/runs')


if __name__ == '__main__':
    render_dashboard()
