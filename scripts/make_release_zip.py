"""Backward-compatible wrapper for release archive creation.

Prefer: scripts/create_release_archive.sh [version]
"""

from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
script = root / 'scripts' / 'create_release_archive.sh'
args = [str(script)]
if len(sys.argv) > 1:
    args.append(sys.argv[1])

subprocess.run(args, cwd=root, check=True)
