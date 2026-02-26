from io import BytesIO
from .conftest import make_client


def test_attachment_upload_and_pdf_extract_route():
    c = make_client()
    t = c.post('/api/teams', json={'name':'MM','mode':'sequential','description':'','yaml_text':''}).json()
    run = c.post('/api/runs', json={'team_id': t['id'], 'prompt':'x', 'max_turns':1, 'max_seconds':10, 'token_budget':200, 'consensus_threshold':1}).json()
    pdf_bytes = b'%PDF-1.1\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF'
    up = c.post(f"/api/runs/{run['run_id']}/attachments", files={'file': ('a.pdf', BytesIO(pdf_bytes), 'application/pdf')})
    assert up.status_code == 200
    assert up.json()['ok'] is True
