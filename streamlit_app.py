import streamlit as st
import requests

API = st.secrets.get('API_URL', 'http://localhost:8000') if hasattr(st, 'secrets') else 'http://localhost:8000'
st.title('Agentora v0.2 Quick Dashboard')

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
            st.json(requests.get(API + path, timeout=5).json())
        except Exception as exc:
            st.warning(f'API unavailable: {exc}')
