import os
os.environ['AGENTORA_DATABASE_URL'] = 'sqlite:///server/data/test.db'
os.environ['AGENTORA_USE_MOCK_OLLAMA'] = 'true'
os.environ['AGENTORA_USE_MOCK_VOICE'] = 'true'

from fastapi.testclient import TestClient
from app.main import create_app


def make_client():
    return TestClient(create_app())
