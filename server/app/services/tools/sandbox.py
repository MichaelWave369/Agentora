import subprocess
import tempfile
from pathlib import Path


def run_python_sandboxed(code: str, timeout: int = 2) -> dict:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'snippet.py'
        p.write_text(code, encoding='utf-8')
        try:
            proc = subprocess.run(['python', str(p)], capture_output=True, text=True, timeout=timeout)
            return {'ok': True, 'stdout': proc.stdout[:1000], 'stderr': proc.stderr[:1000], 'code': proc.returncode}
        except subprocess.TimeoutExpired:
            return {'ok': False, 'error': 'timed_out'}
