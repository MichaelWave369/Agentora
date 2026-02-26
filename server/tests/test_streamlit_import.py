import importlib.util
from pathlib import Path


def test_streamlit_app_imports():
    module_path = Path(__file__).resolve().parents[2] / 'streamlit_app.py'
    spec = importlib.util.spec_from_file_location('streamlit_app', module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
