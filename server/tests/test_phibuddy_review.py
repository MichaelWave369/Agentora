import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import phibuddy_review as route
from app.services import phibuddy_review as review
from app.services import phibuddy_review_cli as cli
from app.services.phibuddy_bridge import canonical, select

KEY = "a" * 64
MODEL = "test:local"
ANSWER = {k: "synthetic " + k for k in review.FIELDS}


def raw_events(content="synthetic proposal"):
    rows = []
    for seq, kind, text in [(1, "turn_started", "private question"),
                            (2, "solo_answer", content), (3, "turn_completed", "")]:
        rows.append(dict(sequence=seq, schema_version=1, session_id="s", turn_id="t",
                         kind=kind, actor="buddy", content=text, created_at="2026-11-25"))
    return b"\n".join(canonical(row) for row in rows)


def packet(content="synthetic proposal", model=MODEL):
    return review.make_request(select(raw_events(content), 2), model)


def test_consent_binds_content_model_and_export(tmp_path, monkeypatch, capsys):
    req = packet()
    assert req["consent_sha256"] != packet("modified")["consent_sha256"]
    assert req["consent_sha256"] != packet(model="other:local")["consent_sha256"]
    path = tmp_path / "events.jsonl"
    path.write_bytes(raw_events())
    monkeypatch.setenv("AGENTORA_PHIBUDDY_BRIDGE_KEY", KEY)
    with patch.object(cli.http.client, "HTTPConnection") as conn:
        assert cli.main([str(path), "--sequence", "2", "--model", MODEL]) == 0
        preview = json.loads(capsys.readouterr().out)
        assert preview["request"] == req
        path.write_bytes(raw_events("changed"))
        assert cli.main([str(path), "--sequence", "2", "--model", MODEL,
                         "--approve-digest", req["consent_sha256"], "--confirm-offline"]) == 1
        conn.assert_not_called()


@pytest.mark.parametrize("model", ["x:cloud", "https://host:1", "untagged", ""])
def test_model_refusal(model):
    with pytest.raises(ValueError):
        packet(model=model)


@pytest.mark.parametrize("change", ["wrong_model", "unfinished", "tool_calls", "malformed", "redirect", "oversize", "extra_field"])
def test_provider_refusal(change):
    data = {"model": MODEL, "done": True, "message": {"role": "assistant", "content": json.dumps(ANSWER)}}
    status = 200
    if change == "wrong_model":
        data["model"] = "other:local"
    elif change == "unfinished":
        data["done"] = False
    elif change == "tool_calls":
        data["message"]["tool_calls"] = [{"function": "never"}]
    elif change == "malformed":
        data["message"]["content"] = "{"
    elif change == "redirect":
        status = 302
    elif change == "extra_field":
        data["message"]["content"] = json.dumps(dict(ANSWER, execution_authority=True))
    def handler(request):
        if change == "oversize":
            return httpx.Response(200, content=b"x" * (review.MAX_PROVIDER + 1))
        return httpx.Response(status, json=data)
    with pytest.raises(ValueError):
        asyncio.run(review.provider_review(packet(), httpx.MockTransport(handler)))


def test_provider_success():
    def handler(request):
        assert str(request.url) == "http://127.0.0.1:11434/api/chat"
        payload = json.loads(request.content)
        assert "tools" not in payload and "private question" not in str(payload)
        assert payload["model"] == MODEL
        return httpx.Response(200, json={"model": MODEL, "done": True, "message": {
            "role": "assistant", "content": json.dumps(ANSWER)}})
    result = asyncio.run(review.provider_review(packet(), httpx.MockTransport(handler)))
    assert result == review.receipt(packet(), ANSWER)
    assert result["execution_authority"] is False and result["offline_verified"] is False


@pytest.fixture
def client(monkeypatch):
    for key, value in {"AGENTORA_PHIBUDDY_BRIDGE_ENABLED": "1",
                       "AGENTORA_PHIBUDDY_REVIEW_ENABLED": "1",
                       "AGENTORA_PHIBUDDY_BRIDGE_KEY": KEY,
                       "AGENTORA_PHIBUDDY_REVIEW_MODELS": MODEL}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(route, "settings", SimpleNamespace(
        agentora_use_mock_ollama=False, ollama_url="http://127.0.0.1:11434"))
    app = FastAPI()
    app.include_router(route.router)
    async def local(scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, client=("127.0.0.1", 1234))
        await app(scope, receive, send)
    return TestClient(local, base_url="http://127.0.0.1:8088")


@pytest.mark.parametrize("change,status", [("disabled",404),("key",403),("origin",403),
    ("mock",503),("remote_provider",503),("allowlist",403),("tamper",422)])
def test_route_refuses_before_provider(client, monkeypatch, change, status):
    headers = {"x-phibuddy-bridge-key": KEY}
    req = packet()
    if change == "disabled":
        monkeypatch.delenv("AGENTORA_PHIBUDDY_REVIEW_ENABLED")
    elif change == "key":
        headers["x-phibuddy-bridge-key"] = "b" * 64
    elif change == "origin":
        headers["origin"] = "http://127.0.0.1:8088"
    elif change == "mock":
        route.settings.agentora_use_mock_ollama = True
    elif change == "remote_provider":
        route.settings.ollama_url = "https://example.invalid"
    elif change == "allowlist":
        monkeypatch.setenv("AGENTORA_PHIBUDDY_REVIEW_MODELS", "other:local")
    elif change == "tamper":
        req["model"] = "other:local"
    with patch.object(route, "provider_review", new_callable=AsyncMock) as provider:
        response = client.post("/api/phibuddy/advisory/review", json=req, headers=headers)
        assert response.status_code == status
        provider.assert_not_awaited()


def test_route_and_client_receipt(client):
    req = packet()
    result = review.receipt(req, ANSWER)
    with patch.object(route, "provider_review", new_callable=AsyncMock, return_value=result) as provider:
        response = client.post("/api/phibuddy/advisory/review", json=req,
                               headers={"x-phibuddy-bridge-key": KEY})
        assert response.status_code == 200 and response.json() == result
        provider.assert_awaited_once_with(req)
    with patch.object(cli.http.client, "HTTPConnection") as factory:
        response = factory.return_value.getresponse.return_value
        response.status = 200
        response.read.return_value = canonical(result)
        assert cli.send(req, KEY, req["consent_sha256"]) == result
        response.read.return_value = canonical(dict(result, execution_authority=True))
        with pytest.raises(ValueError):
            cli.send(req, KEY, req["consent_sha256"])
