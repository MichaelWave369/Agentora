import importlib.util
from pathlib import Path


def test_streamlit_primary_entry_imports():
    module_path = Path(__file__).resolve().parents[2] / 'app.py'
    spec = importlib.util.spec_from_file_location('agentora_streamlit_entry', module_path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
