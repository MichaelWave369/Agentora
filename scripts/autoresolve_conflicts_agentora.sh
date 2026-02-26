#!/usr/bin/env bash
set -euo pipefail

BASE_BRANCH=${1:-main}

echo '[1/6] merge base into current branch'
git merge "origin/${BASE_BRANCH}" || true

echo '[2/6] prefer ours for app code if conflicts exist'
git checkout --ours -- server/app || true
git checkout --ours -- server/tests || true
git checkout --ours -- web/src || true
git checkout --ours -- web/index.html || true
git checkout --ours -- scripts/make_release_zip.py || true
git checkout --ours -- server/requirements.txt || true

echo '[3/6] ensure no conflict markers'
if rg -n "<{7}|={7}|>{7}" .; then
  echo 'Conflict markers found; resolve manually.'
  exit 1
fi

echo '[4/6] commit resolution'
git add -A
git commit -m "chore: resolve PR conflicts and sync with main" || true

echo '[5/6] run checks'
python -m pip install -r server/requirements.txt
python -m compileall server/app
AGENTORA_USE_MOCK_OLLAMA=true pytest server/tests
(
  cd web
  npm ci || (npm install && npm ci)
  npm run build
)

echo '[6/6] push'
git push -u origin HEAD
