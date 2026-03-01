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
        @property
        def sidebar(self): return self
        def radio(self, _l, options): return options[0] if options else ''
        def selectbox(self, *_a, **_k): return ''
        def text_input(self, *_a, **_k): return ''
        def text_area(self, *_a, **_k): return ''
        def slider(self, *_a, **_k): return 60
        def button(self, *_a, **_k): return False
        def checkbox(self, *_a, **_k): return False
        def stop(self): raise RuntimeError('streamlit stop called')
        def set_page_config(self, *_a, **_k): return None
        def balloons(self): return None
        @property
        def session_state(self): return {}

    st = _NoopStreamlit()

ROOT = Path(__file__).resolve().parent
SERVER_DIR = ROOT / 'server'
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

ACTIVE_MODE = 'embedded'


def _resolve_streamlit_db_url() -> str:
    explicit = os.getenv('AGENTORA_DATABASE_URL', '').strip()
    if explicit:
        return explicit
    return f"sqlite:///{(ROOT / 'agentora.db').as_posix()}"


@st.cache_resource
def init_backend_resources(db_url: str):
    from app.db import init_db

    engine = init_db(db_url)
    return {'engine': str(engine.url), 'db_url': db_url}




def initialize_database() -> dict:
    if st.session_state.get('db_ready'):
        return st.session_state.get('backend_resources', {})
    init_msg = st.info('Initializing database...')
    resources = init_backend_resources(_db_url_from_state())
    st.session_state['backend_resources'] = resources
    st.session_state['db_ready'] = True
    init_msg.empty()
    return resources

@st.cache_resource
def embedded_client(db_url: str):
    init_backend_resources(db_url)
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


def _http_get(path: str):
    return requests.get(f'{api_base()}{path}', timeout=3)


def _http_post(path: str, payload: dict):
    return requests.post(f'{api_base()}{path}', json=payload, timeout=5)




def _db_url_from_state() -> str:
    db_url = st.session_state.get('db_url') if hasattr(st, 'session_state') else None
    if not db_url:
        db_url = _resolve_streamlit_db_url()
        try:
            st.session_state['db_url'] = db_url
        except Exception:
            pass
    return db_url

def _embedded_get(path: str) -> dict:
    response = embedded_client(_db_url_from_state()).get(path)
    response.raise_for_status()
    return response.json()


def _embedded_post(path: str, payload: dict) -> dict:
    response = embedded_client(_db_url_from_state()).post(path, json=payload)
    response.raise_for_status()
    return response.json()


def api_get(path: str) -> dict:
    global ACTIVE_MODE
    mode = os.getenv('AGENTORA_STREAMLIT_MODE', 'auto').lower()
    if mode == 'http':
        ACTIVE_MODE = 'http'
        r = _http_get(path)
        r.raise_for_status()
        return r.json()
    if mode == 'embedded':
        ACTIVE_MODE = 'embedded'
        return _embedded_get(path)
    try:
        r = _http_get(path)
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
        r = _http_post(path, payload)
        r.raise_for_status()
        return r.json()
    if mode == 'embedded':
        ACTIVE_MODE = 'embedded'
        return _embedded_post(path, payload)
    try:
        r = _http_post(path, payload)
        r.raise_for_status()
        ACTIVE_MODE = 'http'
        return r.json()
    except Exception:
        ACTIVE_MODE = 'embedded'
        return _embedded_post(path, payload)


def safe_api_get(path: str, label: str = 'request') -> dict:
    try:
        return api_get(path)
    except Exception as exc:
        st.error(f'{label} failed: {exc}')
        return {'error': str(exc)}


def safe_api_post(path: str, payload: dict, label: str = 'request') -> dict:
    try:
        return api_post(path, payload)
    except Exception as exc:
        st.error(f'{label} failed: {exc}')
        return {'error': str(exc)}


def _panel_json(title: str, path: str):
    with st.expander(title, expanded=False):
        st.json(safe_api_get(path, title))


def _theme_css():
    st.markdown(
        """
<style>
.stApp {background: radial-gradient(circle at top, #1e1b4b 0%, #07090d 55%, #05070b 100%); color: #e2e8f0;}
.block-container {padding-top: 1rem;}
.agentora-card {border:1px solid #334155; border-radius:12px; padding:12px; background:#0f172a90; margin-bottom:12px;}
.agentora-pill {display:inline-block; padding:4px 8px; border-radius:999px; border:1px solid #22d3ee; margin-right:6px;}
.backend-ok {background: #14532d; color: #dcfce7; padding: 10px 14px; border-radius: 10px; border: 1px solid #22c55e; font-weight: 700;}
</style>
""",
        unsafe_allow_html=True,
    )


def _backend_status_banner():
    health = safe_api_get('/api/health', 'backend health check')
    ok = bool(health.get('ok'))
    if ok:
        st.markdown("<div class='backend-ok'>✅ Backend Connected</div>", unsafe_allow_html=True)
    else:
        st.warning('Backend status degraded. The app will stay up and show partial data.')
    return health


def _dashboard_page():
    st.subheader('Dashboard')
    health = _backend_status_banner()
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown("<div class='agentora-card'><h4>Health</h4></div>", unsafe_allow_html=True)
        st.json(health)
    with c2:
        st.markdown("<div class='agentora-card'><h4>Runs</h4></div>", unsafe_allow_html=True)
        runs_payload = safe_api_get('/api/runs', 'runs')
        if isinstance(runs_payload, list) and not runs_payload:
            st.caption('No runs yet')
        else:
            st.json(runs_payload)

    with st.expander('Runtime Trace Viewer', expanded=False):
        run_id = st.text_input('Run ID for trace', value='')
        if run_id.strip():
            trace_payload = safe_api_get(f'/api/runs/{run_id.strip()}/trace', 'run trace')
            st.json(trace_payload)



    with st.expander('Action Center / Automation Inspector', expanded=False):
        st.json(safe_api_get('/api/actions/pending', 'pending actions'))
        st.json(safe_api_get('/api/actions/history', 'action history'))
        st.json(safe_api_get('/api/workflows', 'workflows'))
        action_id = st.text_input('Action ID decision', value='', key='action_decision_id')
        c1, c2 = st.columns(2)
        with c1:
            if st.button('Approve Action') and action_id.strip():
                st.json(safe_api_post(f'/api/actions/{action_id.strip()}/approve', {'reason': 'approved from streamlit'}, 'approve action'))
        with c2:
            if st.button('Deny Action') and action_id.strip():
                st.json(safe_api_post(f'/api/actions/{action_id.strip()}/deny', {'reason': 'denied from streamlit'}, 'deny action'))

        wf_name = st.text_input('New workflow name', value='', key='wf_name')
        if st.button('Create sample workflow') and wf_name.strip():
            payload = {
                'name': wf_name.strip(),
                'description': 'Sample safe workflow',
                'params_schema': {},
                'steps': [
                    {'position': 0, 'step_type': 'desktop', 'tool_name': 'desktop_list_dir', 'params': {'path': '.'}, 'requires_approval': False},
                    {'position': 1, 'step_type': 'browser', 'tool_name': 'browser_page_summary', 'params': {'url': 'http://localhost:8088/api/health'}, 'requires_approval': True},
                ],
            }
            st.json(safe_api_post('/api/workflows', payload, 'create workflow'))
        wf_id = st.text_input('Workflow ID run', value='', key='wf_id_run')
        wf_run_id = st.text_input('Run ID for workflow', value='', key='wf_run_id')
        if st.button('Run workflow') and wf_id.strip():
            st.json(safe_api_post(f'/api/workflows/{wf_id.strip()}/run', {'run_id': int(wf_run_id or 0), 'inputs': {}}, 'run workflow'))

    with st.expander('Team Collaboration Inspector', expanded=False):
        collab_run_id = st.text_input('Run ID for team collaboration', value='', key='collab_run_id')
        if collab_run_id.strip():
            st.json(safe_api_get(f'/api/runs/{collab_run_id.strip()}/plan', 'team plan'))
            st.json(safe_api_get(f'/api/runs/{collab_run_id.strip()}/team', 'team overview'))
            st.json(safe_api_get(f'/api/runs/{collab_run_id.strip()}/handoffs', 'handoffs'))
            st.json(safe_api_get(f'/api/runs/{collab_run_id.strip()}/collaboration-trace', 'collaboration trace'))
        st.json(safe_api_get('/api/agents/capabilities', 'agent capabilities'))

    with st.expander('Lattice Memory Inspector', expanded=False):
        st.json(safe_api_get('/api/memory/health', 'memory health'))
        st.json(safe_api_get('/api/memory/layers', 'memory layers'))
        st.json(safe_api_get('/api/memory/conflicts', 'memory conflicts'))
        st.json(safe_api_get('/api/memory/duplicates', 'memory duplicates'))
        mem_run_id = st.text_input('Run ID for memory contexts', value='', key='mem_run_id')
        if mem_run_id.strip():
            st.json(safe_api_get(f'/api/memory/runs/{mem_run_id.strip()}/contexts', 'memory contexts'))
            st.json(safe_api_get(f'/api/memory/runs/{mem_run_id.strip()}/retrieval', 'memory retrieval view'))
            st.json(safe_api_get(f'/api/memory/runs/{mem_run_id.strip()}/trace', 'memory trace'))
        cap_id = st.text_input('Capsule ID for lineage', value='', key='mem_capsule_id')
        if cap_id.strip():
            st.json(safe_api_get(f'/api/memory/capsules/{cap_id.strip()}/lineage', 'capsule lineage'))
            st.json(safe_api_get(f'/api/memory/capsules/{cap_id.strip()}/neighbors', 'capsule neighbors'))
        if st.button('Run memory maintenance now'):
            st.json(safe_api_post('/api/memory/maintenance/run', {'try_worker': True}, 'memory maintenance'))
    with c3:
        st.markdown("<div class='agentora-card'><h4>Marketplace</h4></div>", unsafe_allow_html=True)
        market = safe_api_get('/api/marketplace/templates', 'marketplace')
        templates = market.get('templates') if isinstance(market, dict) else None
        if isinstance(templates, list) and not templates:
            st.caption('Marketplace empty — install your first template')
        else:
            st.json(market)


def _studio_page():
    st.subheader('Studio')
    _panel_json('Personas', '/api/studio/personas')


def _band_page():
    st.subheader('Band')
    _panel_json('Templates', '/api/marketplace/templates')


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
        name = st.text_input('New cosmos name', value='Family Cosmos v0.7')
        seed = st.text_area('Seed', value='A shared story of compassion and courage')
        warmth = st.slider('Warmth', 0, 100, 70)
        if st.button('Create New Cosmos'):
            st.json(safe_api_post('/api/cosmos/worlds', {'name': name, 'seed_prompt': seed, 'warmth': warmth}, 'create cosmos'))
    with c2:
        st.json(safe_api_get('/api/cosmos/worlds', 'cosmos worlds'))
        st.json(safe_api_get('/api/cosmos/archive', 'cosmos archive'))


def _open_cosmos_page():
    st.subheader('Open Cosmos')
    worlds = safe_api_get('/api/cosmos/worlds', 'cosmos worlds').get('items', [])
    world_ids = [w.get('id') for w in worlds if w.get('id')]

    st.markdown("<div class='agentora-card'><h4>Safe Sharing & Merge</h4></div>", unsafe_allow_html=True)
    share_world = st.selectbox('Cosmos to share', options=world_ids) if world_ids else None
    visibility = st.selectbox('Privacy mode', ['private', 'anonymized', 'public_with_credits'])
    if st.button('Share Cosmos (.agentora)') and share_world:
        st.json(safe_api_post('/api/open-cosmos/share', {'world_id': share_world, 'visibility': visibility, 'wisdom_mode': 'anonymized'}, 'share cosmos'))

    package_name = st.text_input('Import package name', value='')
    if st.button('Import & Merge') and package_name:
        st.json(safe_api_post('/api/open-cosmos/import', {'package_name': package_name, 'keep_timelines': []}, 'import cosmos'))

    question = st.text_input('Ask Living Archive', value='What have other families learned about raising kind children?')
    if st.button('Query Archive'):
        st.json(safe_api_post('/api/open-cosmos/archive/query', {'question': question}, 'archive query'))

    w1 = st.selectbox('From cosmos', options=world_ids, key='w_from') if world_ids else None
    w2 = st.selectbox('To cosmos', options=world_ids, key='w_to') if world_ids else None
    if st.button('Wisdom Exchange') and w1 and w2:
        st.balloons()
        st.json(safe_api_post('/api/open-cosmos/exchange', {'world_a': w1, 'world_b': w2}, 'wisdom exchange'))

    if st.button('Grand Synthesis (Meta-Cosmos)') and world_ids:
        st.balloons()
        st.json(safe_api_post('/api/open-cosmos/synthesis', {'world_ids': world_ids, 'title': 'Meta Cosmos v0.7'}, 'grand synthesis'))

    if st.button('Forecast Values 2050') and world_ids:
        st.json(safe_api_post('/api/open-cosmos/forecast', {'world_ids': world_ids}, 'forecast'))

    st.json(safe_api_get('/api/open-cosmos/spotlight', 'community spotlight'))




def _garden_page():
    st.subheader('🌳 The Eternal Garden')
    st.markdown("<div class='agentora-card'><h4>The Living Garden Map</h4></div>", unsafe_allow_html=True)
    map_payload = safe_api_get('/api/garden/map', 'garden map')
    beds = map_payload.get('items', []) if isinstance(map_payload, dict) else []

    if not beds:
        st.caption('No garden beds yet — create a cosmos to plant your first seed.')
        return

    cols = st.columns(3)
    for idx, bed in enumerate(beds[:9]):
        with cols[idx % 3]:
            st.markdown(f"**{bed['plant_name']}**")
            st.progress(int(bed.get('growth', 0)) / 100)
            st.caption(f"Season: {bed.get('season', 'Spring')} • Gardener: {bed.get('gardener_role', 'Waterer')}")
            if st.button(f"Tend #{bed['id']}", key=f"tend_{bed['id']}"):
                st.json(safe_api_post('/api/garden/tend', {'bed_id': bed['id'], 'gardener_role': 'Waterer', 'note': 'gentle watering from the family'}, 'tend bed'))
            if st.button(f"Harvest #{bed['id']}", key=f"harvest_{bed['id']}"):
                st.balloons()
                st.json(safe_api_post(f"/api/garden/harvest/{bed['id']}", {}, 'harvest bed'))

    st.markdown("<div class='agentora-card'><h4>Community Gardens</h4></div>", unsafe_allow_html=True)
    st.json(safe_api_get('/api/garden/community', 'community garden'))
    if st.button('Advance Season (Eternal Cycle)'):
        st.json(safe_api_post('/api/garden/season/advance', {}, 'advance season'))



def _world_garden_page():
    st.subheader('🌍🌸 The World Garden')
    st.markdown("<div class='agentora-card'><h4>Living World Garden Map</h4></div>", unsafe_allow_html=True)
    world = safe_api_get('/api/world-garden/map', 'world garden map')
    items = world.get('items', []) if isinstance(world, dict) else []

    if not items:
        st.caption('No shared blooms yet. Create/share a cosmos to begin the Infinite Bloom cycle.')
        return

    # immersive pseudo-map using columns and glowing cards
    cols = st.columns(2)
    for i, node in enumerate(items[:12]):
        with cols[i % 2]:
            st.markdown(f"**{node.get('icon','🌿')} {node['title']}**")
            st.progress(min(1.0, float(node.get('glow', 0)) / 100.0))
            st.caption(f"Lat {node.get('lat',0):.1f} • Lon {node.get('lon',0):.1f} • Visibility: {node.get('visibility','private')}")
            if st.button(f"Bloom #{node['id']}", key=f"wg_bloom_{node['id']}"):
                st.balloons()
                st.json(safe_api_post('/api/world-garden/bloom', {'node_id': node['id'], 'reason': 'community creation'}, 'infinite bloom'))

    st.markdown("<div class='agentora-card'><h4>Safe Cross-Pollination</h4></div>", unsafe_allow_html=True)
    ids = [n['id'] for n in items]
    a = st.selectbox('From garden', options=ids, key='wg_from')
    b = st.selectbox('To garden', options=ids, key='wg_to')
    if st.button('Preview Merge'):
        st.json(safe_api_post('/api/world-garden/cross-pollinate', {'from_node': a, 'to_node': b, 'preview_only': True}, 'merge preview'))
    if st.button('Apply Safe Cross-Pollination'):
        st.balloons()
        st.json(safe_api_post('/api/world-garden/cross-pollinate', {'from_node': a, 'to_node': b, 'preview_only': False}, 'merge apply'))

    st.markdown("<div class='agentora-card'><h4>Infinite Bloom Constellations</h4></div>", unsafe_allow_html=True)
    st.json(safe_api_get('/api/world-garden/constellations', 'constellations'))

    st.markdown("<div class='agentora-card'><h4>Eternal Harvest Festival</h4></div>", unsafe_allow_html=True)
    if st.button('Run Harvest Festival'):
        st.balloons()
        st.json(safe_api_post('/api/world-garden/festival/harvest', {}, 'harvest festival'))

def _core_page():
    _panel_json('Health', '/api/health')
    _panel_json('Runs', '/api/runs')


def render_dashboard() -> None:
    st.set_page_config(page_title='Agentora v0.9.1', layout='wide', initial_sidebar_state='expanded')
    _theme_css()

    if 'db_url' not in st.session_state:
        st.session_state['db_url'] = _resolve_streamlit_db_url()
    initialize_database()

    st.title('Agentora v0.9.1 — Infinite Bloom & The World Garden')
    st.caption('Primary Streamlit experience • local-first • private by default')
    st.info(f"API Mode: {ACTIVE_MODE.upper()} | DB: {st.session_state['db_url']}")

    page = st.sidebar.radio('Navigate', ['Dashboard', 'Studio', 'Band', 'Arena', 'Gathering', 'Legacy', 'Cosmos', 'Open Cosmos', 'The Eternal Garden', 'The World Garden', 'Core'])
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
    elif page == 'The Eternal Garden':
        _garden_page()
    elif page == 'The World Garden':
        _world_garden_page()
    else:
        _core_page()


if __name__ == '__main__':
    render_dashboard()
