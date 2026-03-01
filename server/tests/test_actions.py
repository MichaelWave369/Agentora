from pathlib import Path

from sqlmodel import Session

from app.db import engine
from app.models import ActionRequest
from .conftest import make_client


def test_desktop_action_policy_enforcement(tmp_path):
    c = make_client()
    payload = {
        'run_id': 7001,
        'agent_id': 0,
        'action_class': 'desktop',
        'tool_name': 'desktop_read_text',
        'params': {'path': '/etc/passwd'},
        'requested_worker': False,
    }
    r = c.post('/api/actions', json=payload)
    assert r.status_code == 200
    item = r.json()['item']
    assert item['status'] == 'denied'


def test_approval_required_and_execute(tmp_path):
    c = make_client()
    target = Path('./server/data/action-note.txt')
    req = c.post('/api/actions', json={'run_id': 7002, 'agent_id': 0, 'action_class': 'desktop', 'tool_name': 'desktop_write_text', 'params': {'path': str(target), 'content': 'hello'}, 'requested_worker': False})
    assert req.status_code == 200
    action_id = req.json()['item']['id']
    assert req.json()['item']['status'] in {'pending', 'approved'}
    if req.json()['item']['status'] == 'pending':
        ap = c.post(f'/api/actions/{action_id}/approve', json={'reason': 'ok'})
        assert ap.status_code == 200
    assert target.exists()
    assert target.read_text(encoding='utf-8') == 'hello'


def test_browser_domain_policy_enforcement():
    c = make_client()
    req = c.post('/api/actions', json={'run_id': 7003, 'agent_id': 0, 'action_class': 'browser', 'tool_name': 'browser_open_url', 'params': {'url': 'https://example.com'}, 'requested_worker': False})
    assert req.status_code == 200
    item = req.json()['item']
    assert item['status'] in {'pending', 'denied'}
