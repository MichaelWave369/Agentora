#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
  VERSION="$(python - <<'PY'
import json
from pathlib import Path
pkg = json.loads(Path('web/package.json').read_text())
print(pkg.get('version', '0.0.0'))
PY
)"
fi

mkdir -p dist
OUT="dist/agentora-${VERSION}-release.zip"

python - "$OUT" <<'PY'
import sys
import zipfile
from pathlib import Path

root = Path('.').resolve()
out = Path(sys.argv[1]).resolve()

excluded_dirs = {
    '.git', '.github/.cache', '.venv', 'venv',
    '__pycache__', '.pytest_cache', '.mypy_cache',
    'dist', 'web/node_modules', 'web/dist',
    'server/data/artifacts', 'server/data/uploads',
}
excluded_suffixes = {'.db', '.sqlite', '.sqlite3', '.zip', '.pyc'}
excluded_files = {'.env'}

with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zf:
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        rel_s = rel.as_posix()

        if any(rel_s == d or rel_s.startswith(d + '/') for d in excluded_dirs):
            continue
        if path.is_dir():
            continue
        if path.name in excluded_files:
            continue
        if path.suffix.lower() in excluded_suffixes:
            continue

        zf.write(path, rel)

print(out)
PY

echo "Created release archive: $OUT"
