#!/usr/bin/env bash
set -euo pipefail
python -m venv .venv
source .venv/bin/activate
pip install -r server/requirements.txt
PYTHONPATH=server uvicorn app.main:app --host 0.0.0.0 --port 8000 &
cd web
npm ci
npm run dev -- --host 0.0.0.0 --port 5173
