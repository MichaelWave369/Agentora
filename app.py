import importlib.util
from pathlib import Path


def _load_streamlit_app_module():
    module_path = Path(__file__).resolve().parent / 'streamlit_app.py'
    spec = importlib.util.spec_from_file_location('agentora_streamlit_app', module_path)
    if not spec or not spec.loader:
        raise RuntimeError('streamlit_app_loader_unavailable')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def render_dashboard():
    mod = _load_streamlit_app_module()
    mod.render_dashboard()


if __name__ == '__main__':
    render_dashboard()
