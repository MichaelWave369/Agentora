import json
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.phibuddy_bridge import router
from app.services import phibuddy_bridge as bridge
from app.services import phibuddy_bridge_cli as cli

KEY = "a" * 64


def events():
    def event(seq, kind, content):
        return dict(sequence=seq, schema_version=1, session_id="s", turn_id="t",
                    kind=kind, actor="buddy", content=content, created_at="2026-11-25 00:00:00")
    return [event(1, "turn_started", "private question"),
            event(2, "solo_answer", "synthetic answer"),
            event(3, "turn_completed", "")]


def encode(rows):
    return ("\n".join(json.dumps(row) for row in rows) + "\n").encode()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("AGENTORA_PHIBUDDY_BRIDGE_ENABLED", "1")
    monkeypatch.setenv("AGENTORA_PHIBUDDY_BRIDGE_KEY", KEY)
    app = FastAPI()
    app.include_router(router)
    # Override the ASGI peer for the loopback test; no external socket.
    async def local(scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=("127.0.0.1", 12345))
        await app(scope, receive, send)
    return TestClient(local, base_url="http://127.0.0.1:8088")


def test_roundtrip(client):
    packet = bridge.select(encode(events()), 2)
    assert "private question" not in str(packet)
    response = client.post("/api/phibuddy/advisory/preview", json=packet,
                           headers={"x-phibuddy-bridge-key": KEY})
    assert response.status_code == 200
    assert response.json() == bridge.validate(packet)
    assert response.json()["execution_authority"] is False
    assert response.json()["completion_verified"] is False


@pytest.mark.parametrize("change", ["wrong_key", "origin", "host", "disabled", "tamper", "oversize"])
def test_refusal(client, monkeypatch, change):
    packet = bridge.select(encode(events()), 2)
    headers = {"x-phibuddy-bridge-key": KEY}
    if change == "wrong_key":
        headers["x-phibuddy-bridge-key"] = "b" * 64
    elif change == "origin":
        headers["origin"] = "http://127.0.0.1:8088"
    elif change == "host":
        headers["host"] = "other:8088"
    elif change == "disabled":
        monkeypatch.delenv("AGENTORA_PHIBUDDY_BRIDGE_ENABLED")
    elif change == "tamper":
        packet["event"]["content"] = "changed"
    elif change == "oversize":
        packet["event"]["content"] = "x" * bridge.MAX_PACKET
    response = client.post("/api/phibuddy/advisory/preview", json=packet, headers=headers)
    assert response.status_code == {"wrong_key":403, "origin":403, "host":403,
                                    "disabled":404, "tamper":422, "oversize":413}[change]


@pytest.mark.parametrize("change", ["incomplete", "failed", "different_session", "reorder", "wrong_schema"])
def test_selection_refuses(change):
    rows = events()
    if change == "incomplete":
        rows.pop()
    elif change == "failed":
        rows[-1]["kind"] = "turn_failed"
    elif change == "different_session":
        rows[-1]["session_id"] = "other"
    elif change == "reorder":
        rows.reverse()
    else:
        rows[1]["schema_version"] = 2
    with pytest.raises(ValueError):
        bridge.select(encode(rows), 2)


def test_preview_no_network(tmp_path, capsys):
    path = tmp_path / "events.jsonl"
    path.write_bytes(encode(events()))
    with patch.object(cli, "send") as send:
        assert cli.main([str(path), "--sequence", "2"]) == 0
        send.assert_not_called()
    assert json.loads(capsys.readouterr().out)["state"] == "LOCAL_PREVIEW_ONLY"


def test_send_receipt_binding():
    packet = bridge.select(encode(events()), 2)
    with patch.object(cli.http.client, "HTTPConnection") as factory:
        response = factory.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = bridge.canonical(bridge.validate(packet))
        assert cli.send(packet, KEY) == bridge.validate(packet)
        factory.assert_called_once_with("127.0.0.1", 8088, timeout=15)
        response.read.return_value = b'{}'
        with pytest.raises(ValueError):
            cli.send(packet, KEY)
