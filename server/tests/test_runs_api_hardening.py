from .conftest import make_client


def test_pause_resume_missing_run_returns_404():
    client = make_client()
    pause = client.post('/api/runs/999999/pause')
    assert pause.status_code == 404

    resume = client.post('/api/runs/999999/resume')
    assert resume.status_code == 404
