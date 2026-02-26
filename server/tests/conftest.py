import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['AGENTORA_DATABASE_URL'] = 'sqlite:///server/data/test.db'
os.environ['AGENTORA_USE_MOCK_OLLAMA'] = 'true'
os.environ['AGENTORA_USE_MOCK_VOICE'] = 'true'

from fastapi.testclient import TestClient
from app.main import create_app
from app.db import create_db_and_tables


def make_client():
    create_db_and_tables()
    return TestClient(create_app())
