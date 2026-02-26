import subprocess
import tempfile
from pathlib import Path


def run_python_restricted(code: str, timeout: int = 3) -> dict:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / 'snippet.py'
        p.write_text(code, encoding='utf-8')
        try:
            proc = subprocess.run(['python', str(p)], capture_output=True, text=True, timeout=timeout)
            return {'stdout': proc.stdout, 'stderr': proc.stderr, 'code': proc.returncode}
        except subprocess.TimeoutExpired:
            return {'stdout': '', 'stderr': 'timed out', 'code': 124}
