#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path | None = None) -> int:
    print('>>', ' '.join(cmd))
    return subprocess.call(cmd, cwd=str(cwd or ROOT))


def ensure_venv(python_bin: str) -> Path:
    venv = ROOT / '.venv'
    if not venv.exists():
        rc = run([python_bin, '-m', 'venv', str(venv)])
        if rc != 0:
            raise SystemExit('Failed to create .venv')
    return venv


def main() -> int:
    parser = argparse.ArgumentParser(description='Agentora one-click bootstrap for local operator mode.')
    parser.add_argument('--skip-web', action='store_true')
    parser.add_argument('--doctor-only', action='store_true')
    args = parser.parse_args()

    python_bin = sys.executable
    venv = ensure_venv(python_bin)
    py = venv / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')

    if run([str(py), '-m', 'pip', 'install', '-r', 'requirements.txt']) != 0:
        return 1

    if not args.skip_web and (ROOT / 'web/package.json').exists() and shutil.which('npm'):
        if run(['npm', 'ci'], cwd=ROOT / 'web') != 0:
            print('warning: web dependency install failed')

    if run([str(py), '-m', 'app.services.runtime.system_doctor'], cwd=ROOT / 'server') != 0:
        print('warning: doctor invocation via module failed; continue with API doctor endpoint at runtime')

    if args.doctor_only:
        return 0

    print('Bootstrap complete. Start backend and Streamlit using launch scripts.')
    return 0


if __name__ == '__main__':
    import shutil

    raise SystemExit(main())
