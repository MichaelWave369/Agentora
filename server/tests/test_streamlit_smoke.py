import os
import importlib.util
from pathlib import Path


def test_streamlit_embedded_api_health():
    os.environ['AGENTORA_STREAMLIT_MODE'] = 'embedded'
    os.environ['AGENTORA_USE_MOCK_OLLAMA'] = 'true'

    module_path = Path(__file__).resolve().parents[2] / 'streamlit_app.py'
    spec = importlib.util.spec_from_file_location('streamlit_app', module_path)
    streamlit_app = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(streamlit_app)

    payload = streamlit_app.api_get('/api/health')
    assert payload['ok'] is True
