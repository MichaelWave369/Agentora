from io import BytesIO
from .conftest import make_client


def test_voice_mock_endpoints():
    c = make_client()
    r = c.post('/api/voice/stt', files={'file': ('a.wav', BytesIO(b'RIFFfake'), 'audio/wav')})
    assert r.status_code == 200
